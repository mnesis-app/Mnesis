import { app, BrowserWindow, dialog, shell, nativeImage, ipcMain } from 'electron'
import electronUpdater from 'electron-updater'
const { autoUpdater } = electronUpdater
import path from 'path'
import { fileURLToPath } from 'url'
import { spawn } from 'child_process'
import net from 'net'
import fs from 'fs'
import { createTray, updateTrayStatus, destroyTray } from './tray.js'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

const isDev = process.env.NODE_ENV === 'development'
const PREFERRED_REST_PORT = 7860
const PREFERRED_MCP_PORT = 7861
const MAX_RESTART_ATTEMPTS = 3
const HEALTH_POLL_INTERVAL_MS = 500
const HEALTH_TIMEOUT_SECS = 120

function publishSplashStatus(splash, payload = {}) {
    if (!splash || splash.isDestroyed()) return
    try {
        splash.webContents.send('splash:status', payload)
    } catch (_) {
        // Splash can be destroyed while startup is still unwinding.
    }
}

function prettyFileName(rawPath) {
    const value = String(rawPath || '').trim()
    if (!value) return ''
    return path.basename(value)
}

// --- Port Management ---
async function isPortAvailable(port) {
    return new Promise((resolve) => {
        const server = net.createServer()
        server.once('error', () => resolve(false))
        server.once('listening', () => { server.close(); resolve(true) })
        server.listen(port)
    })
}

async function findAvailablePort(preferred) {
    for (let port = preferred; port <= preferred + 10; port++) {
        if (await isPortAvailable(port)) return port
    }
    throw new Error(`No available port found starting from ${preferred}`)
}

// --- Backend Management ---
let backendProcess = null
let restartAttempts = 0
let REST_PORT = PREFERRED_REST_PORT
let MCP_PORT = PREFERRED_MCP_PORT
let mainWindowRef = null
let trayConflictInterval = null
let isQuitting = false

function getLogPath() {
    let logDir
    if (process.platform === 'darwin') {
        // macOS: ~/Library/Logs/Mnesis/backend.log
        logDir = path.join(app.getPath('logs'), 'Mnesis')
    } else if (process.platform === 'win32') {
        // Windows: %APPDATA%\Mnesis\Logs\backend.log (spec requirement)
        logDir = path.join(process.env.APPDATA || app.getPath('userData'), 'Mnesis', 'Logs')
    } else {
        logDir = path.join(app.getPath('userData'), 'Logs')
    }
    if (!fs.existsSync(logDir)) fs.mkdirSync(logDir, { recursive: true })
    return path.join(logDir, 'backend.log')
}

async function spawnBackend() {
    // Backend executable is at resources/backend/mnesis-backend
    // package.json extraResources copies backend/dist/* -> resources/backend/*
    const backendExe = path.join(
        process.resourcesPath, 'backend', 'mnesis-backend',
        process.platform === 'win32' ? 'mnesis-backend.exe' : 'mnesis-backend'
    )

    if (!fs.existsSync(backendExe)) {
        throw new Error(`Backend executable not found: ${backendExe}`)
    }

    // Ensure executables have +x bit set — electron-builder does not reliably preserve it on macOS.
    // This must happen BEFORE spawning the backend, because the backend's config_watcher checks
    // os.access(bridge, X_OK) to decide which path to write into claude_desktop_config.json.
    if (process.platform !== 'win32') {
        const bridgeExe = path.join(
            process.resourcesPath, 'backend', 'mcp-stdio-bridge', 'mcp-stdio-bridge'
        )
        try { fs.chmodSync(backendExe, 0o755) } catch (_) {}
        try { if (fs.existsSync(bridgeExe)) fs.chmodSync(bridgeExe, 0o755) } catch (_) {}
    }

    const logFile = getLogPath()
    const logStream = fs.createWriteStream(logFile, { flags: 'a' })
    logStream.on('error', (err) => console.error('[main] Log stream error:', err.message))

    // Write spawn diagnostics from Electron (captured even if backend produces no output)
    try {
        fs.appendFileSync(logFile, `\n[${new Date().toISOString()}] === Mnesis backend spawn ===\n`)
        fs.appendFileSync(logFile, `  Exe: ${backendExe}\n`)
        fs.appendFileSync(logFile, `  Exists: ${fs.existsSync(backendExe)}\n`)
        fs.appendFileSync(logFile, `  Platform: ${process.platform}\n`)
        fs.appendFileSync(logFile, `  CWD: ${process.resourcesPath}\n`)
        const bridgeExeForLog = path.join(process.resourcesPath, 'backend', 'mcp-stdio-bridge', 'mcp-stdio-bridge')
        fs.appendFileSync(logFile, `  BridgeExe: ${bridgeExeForLog}\n`)
        fs.appendFileSync(logFile, `  BridgeExists: ${fs.existsSync(bridgeExeForLog)}\n`)
    } catch (_) {}

    const env = {
        ...process.env,
        MNESIS_PORT: REST_PORT.toString(),
        MNESIS_MCP_PORT: MCP_PORT.toString(),
        MNESIS_BRIDGE_PATH: path.join(
            process.resourcesPath,
            'backend', 'mcp-stdio-bridge',
            process.platform === 'win32' ? 'mcp-stdio-bridge.exe' : 'mcp-stdio-bridge'
        )
    }

    const proc = spawn(backendExe, [], {
        env,
        cwd: process.resourcesPath,
        stdio: ['ignore', 'pipe', 'pipe']
    })

    proc.stdout.pipe(logStream)
    proc.stderr.pipe(logStream)

    proc.on('error', (err) => {
        console.error('Backend process error:', err)
    })

    proc.on('exit', (code, signal) => {
        backendProcess = null
        console.log(`Backend exited: code=${code} signal=${signal}`)
        // Write exit code to log file — visible even when backend crashes before producing output
        try {
            fs.appendFileSync(logFile, `[${new Date().toISOString()}] Backend exited: code=${code}, signal=${signal}\n`)
        } catch (_) {}

        // Auto-restart up to MAX_RESTART_ATTEMPTS times
        if (code !== 0 && code !== null && restartAttempts < MAX_RESTART_ATTEMPTS) {
            restartAttempts++
            console.log(`Auto-restart attempt ${restartAttempts}/${MAX_RESTART_ATTEMPTS}...`)
            setTimeout(() => spawnBackend().then(p => { backendProcess = p }), 5000)
        } else if (restartAttempts >= MAX_RESTART_ATTEMPTS) {
            // Check if the port is now occupied — helpful hint when dev server is running
            isPortAvailable(REST_PORT).then(available => {
                const portHint = !available
                    ? `\n\nPort ${REST_PORT} is in use by another process.\nQuit any running Mnesis dev server (npm run dev) or other app on that port.`
                    : ''
                const defenderHint = process.platform === 'win32'
                    ? '\n\nWindows: check Windows Security → Protection history for blocked files.'
                    : ''
                dialog.showErrorBox(
                    'Mnesis Backend Error',
                    `The memory service crashed and could not be restarted.${portHint}${defenderHint}\n\nExit code: ${code ?? 'unknown'}\n\nCheck logs at:\n${getLogPath()}`
                )
            })
        }
    })

    return proc
}

async function startBackend(splash = null) {
    if (isDev) {
        console.log('[DEV] Assuming backend is running externally on', REST_PORT)
        publishSplashStatus(splash, {
            stage: 'connecting',
            message: 'Connecting to development backend...',
            detail: `http://127.0.0.1:${REST_PORT}/health`,
            progress: null
        })
        return
    }

    try {
        REST_PORT = await findAvailablePort(PREFERRED_REST_PORT)
        MCP_PORT = await findAvailablePort(REST_PORT + 1 >= PREFERRED_MCP_PORT ? PREFERRED_MCP_PORT : REST_PORT + 1)
        console.log(`Starting backend — REST:${REST_PORT} MCP:${MCP_PORT}`)
        publishSplashStatus(splash, {
            stage: 'backend',
            message: 'Starting backend process...',
            detail: `REST ${REST_PORT} · MCP ${MCP_PORT}`,
            progress: 6
        })
    } catch (e) {
        dialog.showErrorBox('Initialization Error', e.message)
        app.quit()
        return
    }

    try {
        backendProcess = await spawnBackend()
        publishSplashStatus(splash, {
            stage: 'connecting',
            message: 'Backend started. Waiting for health check...',
            detail: `http://127.0.0.1:${REST_PORT}/health`,
            progress: 10
        })
    } catch (e) {
        dialog.showErrorBox('Startup Error', `Could not start backend.\n${e.message}`)
        app.quit()
    }
}

/**
 * Poll /health until model_ready: true
 * Per spec: "Poll every 500ms. backend responds 200 immediately but
 * model_ready: true only AFTER embedding model is fully loaded."
 */
async function waitForBackend(splash = null) {
    if (isDev) {
        publishSplashStatus(splash, {
            stage: 'ready',
            message: 'Backend ready (development mode).',
            detail: '',
            progress: 100
        })
        return true
    }

    const maxAttempts = (HEALTH_TIMEOUT_SECS * 1000) / HEALTH_POLL_INTERVAL_MS
    for (let i = 0; i < maxAttempts; i++) {
        try {
            const res = await fetch(`http://127.0.0.1:${REST_PORT}/health`)
            if (res.ok) {
                const json = await res.json()
                const modelStatus = String(json.model_status || '').trim().toLowerCase()
                const downloadPercent = Number(json.download_percent)
                const hasPercent = Number.isFinite(downloadPercent)
                const safePercent = hasPercent ? Math.max(0, Math.min(100, Math.round(downloadPercent))) : null
                let stage = 'connecting'
                let message = 'Preparing memory engine...'
                let detail = ''
                if (modelStatus === 'downloading') {
                    stage = 'downloading'
                    message = 'Downloading embedded model...'
                    detail = prettyFileName(json.download_file) || 'Preparing model files'
                } else if (modelStatus === 'loading') {
                    stage = 'loading'
                    message = 'Loading embedded model in memory...'
                    detail = 'Building inference runtime'
                } else if (modelStatus === 'error') {
                    stage = 'error'
                    message = 'Model initialization failed.'
                    detail = 'Check backend logs for details'
                } else if (json.model_ready === true) {
                    stage = 'ready'
                    message = 'Model ready. Launching app...'
                    detail = ''
                } else {
                    stage = 'connecting'
                    message = 'Connecting to backend...'
                    detail = 'Health endpoint reachable'
                }
                publishSplashStatus(splash, {
                    stage,
                    message,
                    detail,
                    progress: json.model_ready === true ? 100 : safePercent,
                })
                if (json.model_ready === true) {
                    console.log('Backend fully ready (model_ready: true)')
                    restartAttempts = 0
                    return true
                }
                // Still loading model — wait
            }
        } catch (_) {
            // Connection refused — backend not yet up
            publishSplashStatus(splash, {
                stage: 'connecting',
                message: 'Waiting for backend process...',
                detail: `Starting up... ${Math.round((i + 1) * HEALTH_POLL_INTERVAL_MS / 1000)}s`,
                progress: null
            })
        }
        await new Promise(r => setTimeout(r, HEALTH_POLL_INTERVAL_MS))
    }
    publishSplashStatus(splash, {
        stage: 'error',
        message: 'Startup timeout.',
        detail: `Backend was not ready after ${HEALTH_TIMEOUT_SECS}s`,
        progress: null
    })
    return false
}

// --- IPC: Expose ports to renderer (preload.js exposes these via contextBridge) ---
ipcMain.on('get-rest-port', (event) => { event.returnValue = REST_PORT })
ipcMain.on('get-mcp-port', (event) => { event.returnValue = MCP_PORT })

// IPC: Shell open external links — only http/https to prevent file:// or javascript: attacks
function safeOpenExternal(url) {
    try {
        const parsed = new URL(url)
        if (!['http:', 'https:'].includes(parsed.protocol)) return
    } catch { return }
    shell.openExternal(url)
}
ipcMain.on('open-external', (_, url) => { safeOpenExternal(url) })

// --- Window Management ---
function createWindow() {
    const mainWindow = new BrowserWindow({
        width: 1200,
        height: 800,
        minWidth: 900,
        minHeight: 600,
        webPreferences: {
            preload: path.join(__dirname, 'preload.js'),
            contextIsolation: true,
            nodeIntegration: false,
            webSecurity: true, // explicit — prevents CORS bypass and local file access
        },
        titleBarStyle: 'hiddenInset',
        backgroundColor: '#0a0a0a',
    })
    mainWindowRef = mainWindow

    // Content-Security-Policy — only enforced in production builds.
    // Dev uses Vite HMR which requires looser rules not suitable for production.
    if (!isDev) {
        mainWindow.webContents.session.webRequest.onHeadersReceived((details, callback) => {
            callback({
                responseHeaders: {
                    ...details.responseHeaders,
                    'Content-Security-Policy': [
                        `default-src 'self'; ` +
                        `connect-src 'self' http://127.0.0.1:${REST_PORT} ws://127.0.0.1:${REST_PORT} http://127.0.0.1:${MCP_PORT}; ` +
                        `script-src 'self'; ` +
                        `style-src 'self' 'unsafe-inline'; ` +
                        `img-src 'self' data: blob:; ` +
                        `font-src 'self' data:; ` +
                        `worker-src 'self' blob:;`
                    ]
                }
            })
        })
    }

    const uiUrl = isDev
        ? 'http://localhost:5173'
        : `http://127.0.0.1:${REST_PORT}`

    mainWindow.loadURL(uiUrl).catch((e) => {
        console.error('Failed to load UI:', e)
    })

    mainWindow.webContents.setWindowOpenHandler(({ url }) => {
        safeOpenExternal(url)
        return { action: 'deny' }
    })

    return mainWindow
}

function startTrayConflictPolling() {
    if (trayConflictInterval) clearInterval(trayConflictInterval)
    trayConflictInterval = setInterval(async () => {
        try {
            const res = await fetch(`http://127.0.0.1:${REST_PORT}/api/v1/conflicts/count`)
            if (!res.ok) return
            const json = await res.json()
            const pending = json?.pending ?? 0
            updateTrayStatus(pending > 0 ? 'conflict' : 'green', REST_PORT, () => mainWindowRef)
        } catch (_) {
            // Keep last status when polling fails.
        }
    }, 15000)
}

// --- Auto Updater ---
function setupAutoUpdater(win) {
    // Skip in dev — no packaged app to update
    if (isDev) {
        ipcMain.handle('updater:check', async () => ({ success: false, error: 'Update checks are disabled in development mode.' }))
        ipcMain.handle('updater:version', () => app.getVersion())
        return
    }

    autoUpdater.autoDownload = true
    autoUpdater.autoInstallOnAppQuit = true
    // Disable forced signature check in CI / unsigned builds; remove once signed
    autoUpdater.forceDevUpdateConfig = false

    autoUpdater.on('update-available', (info) => {
        console.log(`[updater] Update available: ${info.version}`)
    })

    autoUpdater.on('update-not-available', () => {
        console.log('[updater] App is up to date.')
    })

    autoUpdater.on('update-downloaded', (info) => {
        const isMac = process.platform === 'darwin'
        const choice = dialog.showMessageBoxSync(win, {
            type: 'info',
            title: 'Update ready — Mnesis',
            message: `Version ${info.version} is ready to install.`,
            detail: isMac
                ? 'Download the new version from GitHub Releases and replace the app. It will also update automatically on next launch.'
                : 'Click "Restart now" to apply the update, or it will be installed automatically on next launch.',
            buttons: isMac ? ['Download update', 'Later'] : ['Restart now', 'Later'],
            defaultId: 0,
            cancelId: 1,
        })
        if (choice === 0) {
            if (isMac) {
                shell.openExternal('https://github.com/mnesis-app/Mnesis/releases/latest')
            } else {
                autoUpdater.quitAndInstall(false /* isSilent */, true /* isForceRunAfter */)
            }
        }
    })

    autoUpdater.on('error', (err) => {
        // Non-fatal: network offline, unsigned build, no published release yet
        console.error('[updater] Error:', err?.message || err)
    })

    // IPC: manual "Check for updates" from Settings UI
    ipcMain.handle('updater:check', async () => {
        try {
            const result = await autoUpdater.checkForUpdates()
            return { success: true, updateInfo: result?.updateInfo || null }
        } catch (err) {
            return { success: false, error: err?.message || String(err) }
        }
    })

    // IPC: current version string for Settings UI
    ipcMain.handle('updater:version', () => app.getVersion())

    // Silent background check 8s after launch — avoids blocking startup
    setTimeout(() => {
        autoUpdater.checkForUpdates().catch((err) => {
            console.error('[updater] Background check failed:', err?.message || err)
        })
    }, 8000)
}

// --- App Lifecycle ---
app.whenReady().then(async () => {
    // macOS: Set dev dock icon
    if (process.platform === 'darwin') {
        const iconPath = path.join(__dirname, '../assets/icons/mnesis_dock.png')
        if (fs.existsSync(iconPath)) {
            app.dock.setIcon(nativeImage.createFromPath(iconPath))
        }
    }

    // 1 — Show splash immediately
    const splash = new BrowserWindow({
        width: 480,
        height: 340,
        backgroundColor: '#080808',
        frame: false,
        alwaysOnTop: true,
        webPreferences: {
            preload: path.join(__dirname, 'splash-preload.js'),
            contextIsolation: true,
            nodeIntegration: false
        }
    })
    splash.loadFile(path.join(__dirname, 'splash.html'))
    splash.center()
    publishSplashStatus(splash, {
        stage: 'backend',
        message: 'Initializing startup...',
        detail: 'Preparing local services',
        progress: 2
    })

    // 2 — Start backend
    await startBackend(splash)

    // 3 — Wait for backend + model ready
    console.log('Polling backend health (waiting for model_ready: true)...')
    const ready = await waitForBackend(splash)
    if (!ready) {
        dialog.showErrorBox(
            'Startup Error',
            `Mnesis did not start within ${HEALTH_TIMEOUT_SECS} seconds.\nCheck logs at:\n${getLogPath()}`
        )
        app.quit()
        return
    }

    // 4 — Launch main window, fade-out splash, create tray
    if (splash && !splash.isDestroyed()) {
        // Give the "ready" state a moment to render, then fade-out before destroy
        await new Promise(r => setTimeout(r, 120))
        try { splash.webContents.send('splash:close') } catch (_) {}
        await new Promise(r => setTimeout(r, 300))
        if (!splash.isDestroyed()) splash.destroy()
    }
    const mainWindow = createWindow()

    // Tray icon — shows the backend is ready
    createTray(REST_PORT, () => mainWindowRef)
    updateTrayStatus('green', REST_PORT, () => mainWindowRef)
    startTrayConflictPolling()

    // 5 — Auto-updater (background, non-blocking)
    setupAutoUpdater(mainWindow)

    mainWindow.on('close', (e) => {
        // On macOS, closing the window hides it rather than quitting —
        // unless the user explicitly quit (Cmd+Q / tray menu / app.quit()).
        if (process.platform === 'darwin' && !isQuitting) {
            e.preventDefault()
            mainWindow.hide()
        }
    })

    app.on('activate', () => {
        if (mainWindowRef && !mainWindowRef.isDestroyed()) {
            mainWindowRef.show()
        } else {
            createWindow()
        }
    })
})

app.on('before-quit', () => {
    isQuitting = true
})

app.on('window-all-closed', () => {
    if (process.platform !== 'darwin') app.quit()
})

app.on('will-quit', (e) => {
    restartAttempts = MAX_RESTART_ATTEMPTS // Prevent auto-restart on intentional quit
    if (backendProcess) {
        e.preventDefault()
        const proc = backendProcess
        backendProcess = null
        proc.kill('SIGTERM')
        // Wait up to 3s for graceful shutdown before force-quitting
        const timeout = setTimeout(() => { try { proc.kill('SIGKILL') } catch (_) {} }, 3000)
        proc.on('exit', () => {
            clearTimeout(timeout)
            if (trayConflictInterval) { clearInterval(trayConflictInterval); trayConflictInterval = null }
            destroyTray()
            app.exit()
        })
        return
    }
    if (trayConflictInterval) {
        clearInterval(trayConflictInterval)
        trayConflictInterval = null
    }
    destroyTray()
})

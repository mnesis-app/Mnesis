import { app, BrowserWindow, dialog, shell, nativeImage, ipcMain } from 'electron'
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
        process.resourcesPath, 'backend',
        process.platform === 'win32' ? 'mnesis-backend.exe' : 'mnesis-backend'
    )

    if (!fs.existsSync(backendExe)) {
        throw new Error(`Backend executable not found: ${backendExe}`)
    }

    const logFile = getLogPath()
    const logStream = fs.createWriteStream(logFile, { flags: 'a' })

    const env = {
        ...process.env,
        MNESIS_PORT: REST_PORT.toString(),
        MNESIS_MCP_PORT: MCP_PORT.toString()
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

        // Auto-restart up to MAX_RESTART_ATTEMPTS times
        if (code !== 0 && code !== null && restartAttempts < MAX_RESTART_ATTEMPTS) {
            restartAttempts++
            console.log(`Auto-restart attempt ${restartAttempts}/${MAX_RESTART_ATTEMPTS}...`)
            setTimeout(() => spawnBackend().then(p => { backendProcess = p }), 2000)
        } else if (restartAttempts >= MAX_RESTART_ATTEMPTS) {
            dialog.showErrorBox(
                'Mnesis Backend Error',
                `The memory service crashed and could not be restarted.\n\nCheck logs at:\n${getLogPath()}`
            )
        }
    })

    return proc
}

async function startBackend() {
    if (isDev) {
        console.log('[DEV] Assuming backend is running externally on', REST_PORT)
        return
    }

    try {
        REST_PORT = await findAvailablePort(PREFERRED_REST_PORT)
        MCP_PORT = await findAvailablePort(REST_PORT + 1 >= PREFERRED_MCP_PORT ? PREFERRED_MCP_PORT : REST_PORT + 1)
        console.log(`Starting backend — REST:${REST_PORT} MCP:${MCP_PORT}`)
    } catch (e) {
        dialog.showErrorBox('Initialization Error', e.message)
        app.quit()
        return
    }

    try {
        backendProcess = await spawnBackend()
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
async function waitForBackend() {
    if (isDev) return true

    const maxAttempts = (HEALTH_TIMEOUT_SECS * 1000) / HEALTH_POLL_INTERVAL_MS
    for (let i = 0; i < maxAttempts; i++) {
        try {
            const res = await fetch(`http://127.0.0.1:${REST_PORT}/health`)
            if (res.ok) {
                const json = await res.json()
                if (json.model_ready === true) {
                    console.log('Backend fully ready (model_ready: true)')
                    return true
                }
                // Still loading model — wait
            }
        } catch (_) {
            // Connection refused — backend not yet up
        }
        await new Promise(r => setTimeout(r, HEALTH_POLL_INTERVAL_MS))
    }
    return false
}

// --- IPC: Expose ports to renderer (preload.js exposes these via contextBridge) ---
ipcMain.on('get-rest-port', (event) => { event.returnValue = REST_PORT })
ipcMain.on('get-mcp-port', (event) => { event.returnValue = MCP_PORT })

// IPC: Shell open external links
ipcMain.on('open-external', (_, url) => { shell.openExternal(url) })

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
        },
        titleBarStyle: 'hiddenInset',
        backgroundColor: '#0a0a0a',
    })
    mainWindowRef = mainWindow

    const uiUrl = isDev
        ? 'http://localhost:5173'
        : `http://127.0.0.1:${REST_PORT}`

    mainWindow.loadURL(uiUrl).catch((e) => {
        console.error('Failed to load UI:', e)
    })

    mainWindow.webContents.setWindowOpenHandler(({ url }) => {
        shell.openExternal(url)
        return { action: 'deny' }
    })

    return mainWindow
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
        width: 300,
        height: 350,
        backgroundColor: '#0a0a0a',
        frame: false,
        alwaysOnTop: true,
        webPreferences: { nodeIntegration: false }
    })
    splash.loadFile(path.join(__dirname, 'splash.html'))
    splash.center()

    // 2 — Start backend
    await startBackend()

    // 3 — Wait for backend + model ready
    console.log('Polling backend health (waiting for model_ready: true)...')
    const ready = await waitForBackend()
    if (!ready) {
        dialog.showErrorBox(
            'Startup Error',
            `Mnesis did not start within ${HEALTH_TIMEOUT_SECS} seconds.\nCheck logs at:\n${getLogPath()}`
        )
        app.quit()
        return
    }

    // 4 — Launch main window, close splash, create tray
    if (splash && !splash.isDestroyed()) splash.destroy()
    const mainWindow = createWindow()

    // Tray icon — shows the backend is ready
    createTray(REST_PORT, () => mainWindowRef)
    updateTrayStatus('green', REST_PORT, () => mainWindowRef)

    mainWindow.on('close', (e) => {
        // On macOS, closing the window hides it rather than quitting
        if (process.platform === 'darwin') {
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

app.on('window-all-closed', () => {
    if (process.platform !== 'darwin') app.quit()
})

app.on('will-quit', () => {
    restartAttempts = MAX_RESTART_ATTEMPTS // Prevent auto-restart on intentional quit
    if (backendProcess) {
        backendProcess.kill()
        backendProcess = null
    }
    destroyTray()
})

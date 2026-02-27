// electron/tray.js — System Tray / Menu Bar Icon
// Shows Mnesis status in the macOS menu bar (or Windows system tray).
// Context menu: Open Mnesis, Copy Snapshot Token, Quit.

import electron from 'electron'
const { Tray, Menu, nativeImage, shell } = electron
import path from 'path'
import { fileURLToPath } from 'url'
import fs from 'fs'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

let tray = null

/**
 * Status dot states:
 *   green  — backend running, model ready
 *   yellow — backend starting / model loading
 *   red    — backend offline or error
 */
let currentStatus = 'yellow'

function getTrayIconPath(status) {
    const iconName = {
        green: 'tray_green.png',
        yellow: 'tray_yellow.png',
        red: 'tray_red.png',
        conflict: 'tray_red.png',
    }[status] || 'tray_yellow.png'

    const iconPath = path.join(__dirname, '../assets/icons', iconName)
    // Fall back to a text template icon if images not generated yet
    return fs.existsSync(iconPath) ? iconPath : null
}

function buildContextMenu(restPort, getMainWindow) {
    const statusLabel = currentStatus === 'green'
        ? '● Ready'
        : currentStatus === 'yellow'
            ? '◐ Loading…'
            : currentStatus === 'conflict'
                ? '● Conflicts Pending'
                : '● Offline';

    return Menu.buildFromTemplate([
        {
            label: 'Open Mnesis',
            click: () => {
                const win = getMainWindow()
                if (win) {
                    win.show()
                    win.focus()
                }
            }
        },
        { type: 'separator' },
        {
            label: 'Copy Memory Snapshot URL',
            click: async () => {
                try {
                    const res = await fetch(`http://127.0.0.1:${restPort}/api/v1/admin/snapshot-token`)
                    const data = await res.json()
                    const token = data.token || ''
                    const url = `http://127.0.0.1:${restPort}/api/v1/snapshot/text?token=${token}`
                    const { clipboard } = await import('electron')
                    clipboard.writeText(url)
                } catch (_) { }
            }
        },
        {
            label: 'Open Logs…',
            click: () => {
                const logDir = process.platform === 'darwin'
                    ? path.join(electron.app.getPath('logs'), 'Mnesis')
                    : path.join(process.env.APPDATA || electron.app.getPath('userData'), 'Mnesis', 'Logs')
                shell.openPath(logDir)
            }
        },
        { type: 'separator' },
        {
            label: `Status: ${statusLabel}`,
            enabled: false,
        },
        { type: 'separator' },
        {
            label: 'Quit Mnesis',
            click: () => {
                electron.app.quit()
            }
        }
    ])
}

/**
 * Create the system tray icon.
 * @param {number} restPort
 * @param {() => import('electron').BrowserWindow | null} getMainWindow
 */
export function createTray(restPort, getMainWindow) {
    const iconPath = getTrayIconPath('yellow')
    let icon

    if (iconPath) {
        icon = nativeImage.createFromPath(iconPath)
        // Resize to 22×22 for macOS menu bar
        if (process.platform === 'darwin') {
            icon = icon.resize({ width: 22, height: 22 })
            icon.setTemplateImage(false)
        }
    } else {
        // Fallback: empty 1×1 transparent icon
        icon = nativeImage.createEmpty()
    }

    tray = new Tray(icon)
    tray.setToolTip('Mnesis — Memory Layer')

    const updateMenu = () => {
        tray.setContextMenu(buildContextMenu(restPort, getMainWindow))
    }
    updateMenu()

    tray.on('click', () => {
        const win = getMainWindow()
        if (win) {
            win.isVisible() ? win.hide() : win.show()
        }
    })

    return tray
}

/**
 * Update the tray icon to reflect current backend status.
 * @param {'green'|'yellow'|'red'|'conflict'} status
 * @param {number} restPort
 * @param {() => import('electron').BrowserWindow | null} getMainWindow
 */
export function updateTrayStatus(status, restPort, getMainWindow) {
    if (!tray || tray.isDestroyed()) return
    currentStatus = status

    const iconPath = getTrayIconPath(status)
    if (iconPath) {
        const icon = nativeImage.createFromPath(iconPath)
        tray.setImage(process.platform === 'darwin' ? icon.resize({ width: 22, height: 22 }) : icon)
    }

    tray.setContextMenu(buildContextMenu(restPort, getMainWindow))
}

export function destroyTray() {
    if (tray && !tray.isDestroyed()) {
        tray.destroy()
        tray = null
    }
}

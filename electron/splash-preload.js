const { contextBridge, ipcRenderer } = require('electron')

const statusListeners = new Set()
const closeListeners  = new Set()

ipcRenderer.on('splash:status', (_event, payload) => {
    for (const cb of statusListeners) {
        try {
            cb(payload || {})
        } catch (_) {
            // Ignore listener errors to keep splash updates flowing.
        }
    }
})

ipcRenderer.on('splash:close', () => {
    for (const cb of closeListeners) {
        try {
            cb()
        } catch (_) {
            // Ignore listener errors.
        }
    }
})

contextBridge.exposeInMainWorld('splashAPI', {
    onStatus: (callback) => {
        if (typeof callback !== 'function') return () => {}
        statusListeners.add(callback)
        return () => statusListeners.delete(callback)
    },
    onClose: (callback) => {
        if (typeof callback !== 'function') return () => {}
        closeListeners.add(callback)
        return () => closeListeners.delete(callback)
    },
})

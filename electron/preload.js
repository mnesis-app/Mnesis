const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('electronAPI', {
    // Dynamic port: set by main process before window loads
    getRestPort: () => ipcRenderer.sendSync('get-rest-port'),
    getMcpPort: () => ipcRenderer.sendSync('get-mcp-port'),

    // Shell
    openExternal: (url) => ipcRenderer.send('open-external', url),

    // Auto-updater
    checkForUpdates: () => ipcRenderer.invoke('updater:check'),
    getAppVersion: () => ipcRenderer.invoke('updater:version'),
})

import { contextBridge, ipcRenderer } from 'electron'

contextBridge.exposeInMainWorld('electronAPI', {
    // Dynamic port: set by main process before window loads
    getRestPort: () => ipcRenderer.sendSync('get-rest-port'),
    getMcpPort: () => ipcRenderer.sendSync('get-mcp-port'),

    // Shell
    openExternal: (url: string) => ipcRenderer.send('open-external', url),
})

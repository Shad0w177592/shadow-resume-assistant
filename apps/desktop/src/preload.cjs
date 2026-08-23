const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("shadowDesktop", {
  health: () => ipcRenderer.invoke("backend:health"),
  request: (path, method = "GET", body) =>
    ipcRenderer.invoke("backend:request", { path, method, body }),
  pickDocument: () => ipcRenderer.invoke("file:pick-document"),
  pickPhoto: () => ipcRenderer.invoke("file:pick-photo"),
  pickBackup: () => ipcRenderer.invoke("file:pick-backup"),
  changeDataDirectory: () => ipcRenderer.invoke("data:change-directory"),
  transcribeAudio: (bytes, mediaType = "audio/webm") =>
    ipcRenderer.invoke("audio:transcribe", { bytes, mediaType }),
  platform: process.platform,
});

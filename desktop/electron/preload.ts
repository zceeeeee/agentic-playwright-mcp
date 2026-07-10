import { contextBridge, ipcRenderer } from "electron";

contextBridge.exposeInMainWorld("desktopAgent", {
  expandChat: () => ipcRenderer.invoke("pet:expand"),
  collapseChat: () => ipcRenderer.invoke("pet:collapse"),
  isExpanded: () => ipcRenderer.invoke("pet:is-expanded"),
  openDashboard: () => ipcRenderer.invoke("dashboard:open"),
  setPetPosition: (x: number, y: number) => ipcRenderer.invoke("pet:set-position", { x, y }),
  setWindowPosition: (x: number, y: number) => ipcRenderer.invoke("window:set-position", { x, y }),
  getWindowBounds: () => ipcRenderer.invoke("window:get-bounds"),
  showPetMenu: () => ipcRenderer.invoke("pet:show-menu"),
  restartBackend: () => ipcRenderer.invoke("backend:restart"),
  getBackendConfig: () => ipcRenderer.invoke("backend:config"),
  getSettings: () => ipcRenderer.invoke("settings:get"),
  saveSettings: (settings: Record<string, unknown>) => ipcRenderer.invoke("settings:save", settings),
  quitApp: () => ipcRenderer.invoke("app:quit"),
  onBackendLog: (callback: (message: string) => void) => {
    const listener = (_event: Electron.IpcRendererEvent, message: string) => callback(message);
    ipcRenderer.on("backend:log", listener);
    return () => ipcRenderer.removeListener("backend:log", listener);
  },
  onExpandedChange: (callback: (expanded: boolean) => void) => {
    const listener = (_event: Electron.IpcRendererEvent, value: boolean) => callback(value);
    ipcRenderer.on("pet:expanded", listener);
    return () => ipcRenderer.removeListener("pet:expanded", listener);
  },
  onBackendRestarted: (callback: () => void) => {
    const listener = () => callback();
    ipcRenderer.on("backend:restarted", listener);
    return () => ipcRenderer.removeListener("backend:restarted", listener);
  }
});

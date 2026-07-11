import { contextBridge, ipcRenderer } from "electron";

contextBridge.exposeInMainWorld("desktopAgent", {
  expandChat: () => ipcRenderer.invoke("pet:expand"),
  collapseChat: () => ipcRenderer.invoke("pet:collapse"),
  isExpanded: () => ipcRenderer.invoke("pet:is-expanded"),
  openDashboard: (section?: string) => ipcRenderer.invoke("dashboard:open", section),
  setPetPosition: (x: number, y: number) => ipcRenderer.invoke("pet:set-position", { x, y }),
  resizeExpandedChat: (
    edge: string,
    deltaX: number,
    deltaY: number,
    persist = false
  ) => ipcRenderer.invoke("pet:resize-expanded", { edge, deltaX, deltaY }, persist),
  getWindowBounds: () => ipcRenderer.invoke("window:get-bounds"),
  showPetMenu: () => ipcRenderer.invoke("pet:show-menu"),
  restartBackend: () => ipcRenderer.invoke("backend:restart"),
  getBackendConfig: () => ipcRenderer.invoke("backend:config"),
  getSettings: () => ipcRenderer.invoke("settings:get"),
  saveSettings: (settings: Record<string, unknown>) => ipcRenderer.invoke("settings:save", settings),
  getAppearancePreferences: () => ipcRenderer.invoke("appearance:get-preferences"),
  setSkin: (skinId: string) => ipcRenderer.invoke("appearance:set-skin", skinId),
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
  },
  onAppearanceChanged: (callback: (preferences: { version: 1; skinId: string }) => void) => {
    const listener = (
      _event: Electron.IpcRendererEvent,
      preferences: { version: 1; skinId: string }
    ) => callback(preferences);
    ipcRenderer.on("appearance:changed", listener);
    return () => ipcRenderer.removeListener("appearance:changed", listener);
  },
  onDashboardNavigate: (callback: (section: string) => void) => {
    const listener = (_event: Electron.IpcRendererEvent, section: string) => callback(section);
    ipcRenderer.on("dashboard:navigate", listener);
    return () => ipcRenderer.removeListener("dashboard:navigate", listener);
  }
});

import { contextBridge, ipcRenderer } from "electron";
import type {
  AppearancePreferences,
  AppearanceUpdatePatch,
  PetSkinId,
  UpdateAppearanceOptions
} from "./appearanceModel.js";

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
  getActiveConversation: () => ipcRenderer.invoke("conversation:get-active"),
  setActiveConversation: (conversationId: string) => ipcRenderer.invoke("conversation:set-active", conversationId),
  getSettings: () => ipcRenderer.invoke("settings:get"),
  saveSettings: (settings: Record<string, unknown>) => ipcRenderer.invoke("settings:save", settings),
  getAppearancePreferences: () => ipcRenderer.invoke("appearance:get-preferences"),
  updateAppearancePreferences: (
    patch: AppearanceUpdatePatch,
    options?: UpdateAppearanceOptions
  ) => ipcRenderer.invoke("appearance:update-preferences", patch, options),
  setSkin: (skinId: PetSkinId) =>
    ipcRenderer.invoke("appearance:update-preferences", { skinId }, {}),
  deletePaletteHistory: (historyId: string) =>
    ipcRenderer.invoke("appearance:delete-palette-history", historyId),
  clearPaletteHistory: () => ipcRenderer.invoke("appearance:clear-palette-history"),
  openExternal: (url: string) => ipcRenderer.invoke("app:open-external", url),
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
  onActiveConversationChange: (callback: (conversationId: string) => void) => {
    const listener = (_event: Electron.IpcRendererEvent, conversationId: string) => callback(conversationId);
    ipcRenderer.on("conversation:changed", listener);
    return () => ipcRenderer.removeListener("conversation:changed", listener);
  },
  onAppearanceChanged: (callback: (preferences: AppearancePreferences) => void) => {
    const listener = (
      _event: Electron.IpcRendererEvent,
      preferences: AppearancePreferences
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

import {
  app,
  BrowserWindow,
  ipcMain,
  Menu,
  nativeImage,
  safeStorage,
  screen,
  shell,
  Tray
} from "electron";
import { ChildProcessWithoutNullStreams, spawn } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs";
import net from "node:net";
import path from "node:path";
import { pathToFileURL } from "node:url";
import {
  getCompactShapeForSkin,
  getDefaultAppearancePreferences,
  mergeAndValidateAppearancePreferences,
  readAppearancePreferences,
  writeAppearancePreferences,
  type AppearancePreferences,
  type AppearanceUpdatePatch,
  type UpdateAppearanceOptions
} from "./appearance.js";
import {
  clampChatBounds,
  DEFAULT_CHAT_SIZE,
  parseChatSize,
  resizeChatBoundsBy,
  type ResizeEdge,
  type WindowSize
} from "./windowGeometry.js";
import { applyAlwaysOnTopToWindow } from "./windowBehavior.js";
import { forwardUtf8Logs, withUtf8PythonEnvironment } from "./backendLogging.js";

const COMPACT_SIZE = 80;

let petWindow: BrowserWindow | null = null;
let dashboardWindow: BrowserWindow | null = null;
let tray: Tray | null = null;
let backend: ChildProcessWithoutNullStreams | null = null;
let backendPort = 0;
let backendToken = "";
let expanded = false;
let compactBounds = { x: 0, y: 0, width: COMPACT_SIZE, height: COMPACT_SIZE };
let expandedSize: WindowSize = { ...DEFAULT_CHAT_SIZE };
let expandedAnchor = { right: true, bottom: true };
let quitting = false;
let appearancePreferences: AppearancePreferences = getDefaultAppearancePreferences();
let correctingExpandedPosition = false;
let expandedMoveSettleTimer: NodeJS.Timeout | null = null;
let activeConversationId: string | null = null;

const projectRoot = path.resolve(__dirname, "..", "..");
const desktopRoot = path.resolve(__dirname, "..");

function userFile(name: string): string {
  return path.join(app.getPath("userData"), name);
}

function readJson<T>(file: string, fallback: T): T {
  try {
    return JSON.parse(fs.readFileSync(file, "utf8")) as T;
  } catch {
    return fallback;
  }
}

function writeJson(file: string, value: unknown): void {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, JSON.stringify(value, null, 2), "utf8");
}

function clampCompactPosition(x: number, y: number): { x: number; y: number } {
  const display = screen.getDisplayNearestPoint({ x, y });
  const area = display.workArea;
  return {
    x: Math.min(Math.max(Math.round(x), area.x), area.x + area.width - COMPACT_SIZE),
    y: Math.min(Math.max(Math.round(y), area.y), area.y + area.height - COMPACT_SIZE)
  };
}

function initialCompactBounds(): typeof compactBounds {
  const saved = readJson<{ x?: number; y?: number }>(userFile("pet-position.json"), {});
  if (typeof saved.x === "number" && typeof saved.y === "number") {
    const point = clampCompactPosition(saved.x, saved.y);
    return { ...point, width: COMPACT_SIZE, height: COMPACT_SIZE };
  }
  const area = screen.getPrimaryDisplay().workArea;
  return {
    x: area.x + area.width - COMPACT_SIZE - 24,
    y: area.y + area.height - COMPACT_SIZE - 24,
    width: COMPACT_SIZE,
    height: COMPACT_SIZE
  };
}

function initialExpandedSize(): WindowSize {
  return parseChatSize(readJson(userFile("chat-window-size.json"), DEFAULT_CHAT_SIZE));
}

function syncCompactAnchorFromExpanded(bounds: Electron.Rectangle, persist = true): void {
  const anchorX = expandedAnchor.right
    ? bounds.x + bounds.width - COMPACT_SIZE
    : bounds.x;
  const anchorY = expandedAnchor.bottom
    ? bounds.y + bounds.height - COMPACT_SIZE
    : bounds.y;
  const point = clampCompactPosition(anchorX, anchorY);
  compactBounds = { ...point, width: COMPACT_SIZE, height: COMPACT_SIZE };
  if (persist) writeJson(userFile("pet-position.json"), point);
}

function applyPetAlwaysOnTop(enabled: boolean, bringToFront = false): void {
  if (!petWindow || petWindow.isDestroyed()) return;
  try {
    applyAlwaysOnTopToWindow(petWindow, enabled, process.platform, bringToFront);
  } catch (error) {
    broadcastLog(`Unable to apply always-on-top preference: ${String(error)}`);
  }
}

function clearExpandedMoveSettleTimer(): void {
  if (!expandedMoveSettleTimer) return;
  clearTimeout(expandedMoveSettleTimer);
  expandedMoveSettleTimer = null;
}

function settleExpandedWindowPosition(): void {
  clearExpandedMoveSettleTimer();
  if (!petWindow || petWindow.isDestroyed() || !expanded || correctingExpandedPosition) return;

  const currentBounds = petWindow.getBounds();
  const display = screen.getDisplayMatching(currentBounds);
  const nextBounds = clampChatBounds(currentBounds, display.workArea);
  const changed =
    nextBounds.x !== currentBounds.x ||
    nextBounds.y !== currentBounds.y ||
    nextBounds.width !== currentBounds.width ||
    nextBounds.height !== currentBounds.height;

  if (changed) {
    correctingExpandedPosition = true;
    try {
      petWindow.setBounds(nextBounds, false);
      applyExpandedShape(nextBounds);
    } finally {
      correctingExpandedPosition = false;
    }
  }
  syncCompactAnchorFromExpanded(changed ? nextBounds : currentBounds);
}

function scheduleExpandedWindowSettle(): void {
  if (!expanded || correctingExpandedPosition) return;
  clearExpandedMoveSettleTimer();
  expandedMoveSettleTimer = setTimeout(settleExpandedWindowPosition, 120);
}

function rendererUrl(view: "pet" | "dashboard", section?: string): string {
  const url = pathToFileURL(path.join(desktopRoot, "dist", "index.html"));
  url.searchParams.set("view", view);
  if (section) url.searchParams.set("section", section);
  return url.toString();
}

function createPetWindow(): void {
  compactBounds = initialCompactBounds();
  expandedSize = initialExpandedSize();
  petWindow = new BrowserWindow({
    ...compactBounds,
    frame: false,
    transparent: true,
    resizable: false,
    alwaysOnTop: appearancePreferences.alwaysOnTop,
    skipTaskbar: true,
    hasShadow: false,
    show: false,
    backgroundColor: "#00000000",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true
    }
  });
  applyPetAlwaysOnTop(appearancePreferences.alwaysOnTop);
  petWindow.loadURL(rendererUrl("pet"));
  petWindow.once("ready-to-show", () => {
    petWindow?.show();
    applyPetAlwaysOnTop(appearancePreferences.alwaysOnTop);
  });
  petWindow.on("closed", () => {
    clearExpandedMoveSettleTimer();
    petWindow = null;
  });
  petWindow.on("move", scheduleExpandedWindowSettle);
  petWindow.on("moved", () => {
    if (!expanded) return;
    settleExpandedWindowPosition();
  });
  applyCompactShape();
}

function applyCompactShape(): void {
  if (!petWindow || expanded || typeof petWindow.setShape !== "function") return;
  try {
    petWindow.setShape(getCompactShapeForSkin(appearancePreferences.skinId, COMPACT_SIZE));
  } catch {
    // setShape is not available on every platform/backend.
  }
}

function applyExpandedShape(bounds: Pick<Electron.Rectangle, "width" | "height">): void {
  if (!petWindow || !expanded || typeof petWindow.setShape !== "function") return;
  try {
    petWindow.setShape([{ x: 0, y: 0, width: bounds.width, height: bounds.height }]);
  } catch {
    // Ignore unsupported shape updates.
  }
}

function persistExpandedBounds(bounds: Electron.Rectangle): void {
  expandedSize = { width: bounds.width, height: bounds.height };
  writeJson(userFile("chat-window-size.json"), expandedSize);
  syncCompactAnchorFromExpanded(bounds);
}

function expandPet(): void {
  if (!petWindow || expanded) return;
  compactBounds = { ...petWindow.getBounds(), width: COMPACT_SIZE, height: COMPACT_SIZE };
  const display = screen.getDisplayMatching(compactBounds);
  const area = display.workArea;
  const rightAnchored = compactBounds.x + COMPACT_SIZE / 2 > area.x + area.width / 2;
  const bottomAnchored = compactBounds.y + COMPACT_SIZE / 2 > area.y + area.height / 2;
  expandedAnchor = { right: rightAnchored, bottom: bottomAnchored };
  const size = parseChatSize(expandedSize);
  const width = Math.min(size.width, area.width);
  const height = Math.min(size.height, area.height);
  const x = rightAnchored
    ? Math.max(area.x, compactBounds.x + COMPACT_SIZE - width)
    : Math.min(compactBounds.x, area.x + area.width - width);
  const y = bottomAnchored
    ? Math.max(area.y, compactBounds.y + COMPACT_SIZE - height)
    : Math.min(compactBounds.y, area.y + area.height - height);
  expanded = true;
  const bounds = { x, y, width, height };
  applyExpandedShape(bounds);
  petWindow.setBounds(bounds, true);
  applyPetAlwaysOnTop(appearancePreferences.alwaysOnTop);
  petWindow.webContents.send("pet:expanded", true);
}

function collapsePet(): void {
  if (!petWindow || !expanded) return;
  clearExpandedMoveSettleTimer();
  const targetWindow = petWindow;
  persistExpandedBounds(targetWindow.getBounds());
  expanded = false;
  targetWindow.webContents.send("pet:expanded", false);
  const point = clampCompactPosition(compactBounds.x, compactBounds.y);
  compactBounds = { ...point, width: COMPACT_SIZE, height: COMPACT_SIZE };
  targetWindow.setBounds(compactBounds, true);
  applyCompactShape();
  applyPetAlwaysOnTop(appearancePreferences.alwaysOnTop);
  setTimeout(() => {
    if (!expanded && !targetWindow.isDestroyed()) {
      targetWindow.webContents.send("pet:expanded", false);
      targetWindow.webContents.invalidate();
    }
  }, 100);
}

function normalizeDashboardSection(value: unknown): string | undefined {
  const allowed = new Set([
    "chat", "history", "appearance", "api", "models", "skills",
    "browser", "permissions", "logs", "about"
  ]);
  if (value === "models") return "api";
  return typeof value === "string" && allowed.has(value) ? value : undefined;
}

function createDashboardWindow(section?: string): BrowserWindow {
  const targetSection = normalizeDashboardSection(section);
  if (expanded) collapsePet();
  if (dashboardWindow && !dashboardWindow.isDestroyed()) {
    dashboardWindow.show();
    dashboardWindow.focus();
    if (targetSection) dashboardWindow.webContents.send("dashboard:navigate", targetSection);
    return dashboardWindow;
  }
  dashboardWindow = new BrowserWindow({
    width: 1000,
    height: 720,
    minWidth: 820,
    minHeight: 600,
    title: "桌面智能体控制台",
    backgroundColor: "#f4f6f8",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true
    }
  });
  dashboardWindow.setMenuBarVisibility(false);
  dashboardWindow.loadURL(rendererUrl("dashboard", targetSection));
  dashboardWindow.on("closed", () => {
    dashboardWindow = null;
  });
  return dashboardWindow;
}

function broadcastLog(message: string): void {
  for (const win of [petWindow, dashboardWindow]) {
    if (win && !win.isDestroyed()) win.webContents.send("backend:log", message);
  }
}

function broadcastAppearanceChanged(preferences: AppearancePreferences): void {
  for (const win of [petWindow, dashboardWindow]) {
    if (win && !win.isDestroyed()) {
      win.webContents.send("appearance:changed", preferences);
    }
  }
}

function broadcastActiveConversation(conversationId: string): void {
  for (const win of [petWindow, dashboardWindow]) {
    if (win && !win.isDestroyed()) {
      win.webContents.send("conversation:changed", conversationId);
    }
  }
}

function setActiveConversation(conversationId: unknown): string {
  if (typeof conversationId !== "string" || !conversationId.trim()) {
    throw new TypeError("Conversation id is required");
  }
  const normalized = conversationId.trim();
  if (activeConversationId !== normalized) {
    activeConversationId = normalized;
    broadcastActiveConversation(normalized);
  }
  return normalized;
}

function updateAppearancePreferences(
  patch: AppearanceUpdatePatch,
  options: UpdateAppearanceOptions = {}
): AppearancePreferences {
  const previous = appearancePreferences;
  const next = mergeAndValidateAppearancePreferences(previous, patch, options);
  appearancePreferences = writeAppearancePreferences(userFile("ui-preferences.json"), next);

  if (previous.alwaysOnTop !== appearancePreferences.alwaysOnTop) {
    applyPetAlwaysOnTop(
      appearancePreferences.alwaysOnTop,
      appearancePreferences.alwaysOnTop
    );
  }
  if (previous.skinId !== appearancePreferences.skinId) {
    applyCompactShape();
    applyPetAlwaysOnTop(appearancePreferences.alwaysOnTop);
  }
  updateTrayMenu();
  broadcastAppearanceChanged(appearancePreferences);
  return appearancePreferences;
}

function deletePaletteHistory(historyId: unknown): AppearancePreferences {
  if (typeof historyId !== "string" || !historyId.trim()) return appearancePreferences;
  const next = {
    ...appearancePreferences,
    paletteHistory: appearancePreferences.paletteHistory.filter((item) => item.id !== historyId)
  };
  appearancePreferences = writeAppearancePreferences(userFile("ui-preferences.json"), next);
  broadcastAppearanceChanged(appearancePreferences);
  return appearancePreferences;
}

function clearPaletteHistory(): AppearancePreferences {
  if (!appearancePreferences.paletteHistory.length) return appearancePreferences;
  appearancePreferences = writeAppearancePreferences(userFile("ui-preferences.json"), {
    ...appearancePreferences,
    paletteHistory: []
  });
  broadcastAppearanceChanged(appearancePreferences);
  return appearancePreferences;
}

function settingsForBackend(): NodeJS.ProcessEnv {
  const stored = readJson<Record<string, string>>(userFile("settings.json"), {});
  let apiKey = "";
  if (stored.apiKeyEncrypted && safeStorage.isEncryptionAvailable()) {
    try {
      apiKey = safeStorage.decryptString(Buffer.from(stored.apiKeyEncrypted, "base64"));
    } catch {
      apiKey = "";
    }
  }
  const provider = stored.provider || "openai";
  const env = withUtf8PythonEnvironment({
    ...process.env,
    DESKTOP_AGENT_TOKEN: backendToken,
    AGENT_DESKTOP_RESOURCES_PATH: process.resourcesPath,
    LLM_PROVIDER: provider,
    BROWSER_HEADLESS: stored.browserHeadless || "false",
    DESKTOP_AGENT_MAX_STEPS: stored.maxSteps || "20",
    USE_CLOAKBROWSER: stored.useCloakBrowser || "true"
  });
  if (provider === "anthropic") {
    env.ANTHROPIC_API_KEY = apiKey || process.env.ANTHROPIC_API_KEY;
    env.ANTHROPIC_BASE_URL = stored.baseUrl || process.env.ANTHROPIC_BASE_URL;
    env.ANTHROPIC_MODEL = stored.model || process.env.ANTHROPIC_MODEL;
  } else {
    env.OPENAI_API_KEY = apiKey || process.env.OPENAI_API_KEY;
    env.OPENAI_BASE_URL = stored.baseUrl || process.env.OPENAI_BASE_URL;
    env.OPENAI_MODEL = stored.model || process.env.OPENAI_MODEL;
  }
  return env;
}

async function freePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.on("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      const port = typeof address === "object" && address ? address.port : 0;
      server.close(() => resolve(port));
    });
  });
}

async function startBackend(): Promise<void> {
  backendPort = await freePort();
  backendToken = crypto.randomBytes(32).toString("hex");
  const venvPython = path.join(projectRoot, ".venv", "Scripts", "python.exe");
  const python = process.env.PYTHON_EXECUTABLE || (fs.existsSync(venvPython) ? venvPython : "python");
  backend = spawn(
    python,
    ["-m", "src.desktop.api", "--host", "127.0.0.1", "--port", String(backendPort)],
    { cwd: projectRoot, env: settingsForBackend(), windowsHide: true }
  );
  forwardUtf8Logs(backend.stdout, broadcastLog);
  forwardUtf8Logs(backend.stderr, broadcastLog);
  backend.on("exit", (code) => {
    broadcastLog(`Agent backend stopped (${code ?? "unknown"})`);
    backend = null;
  });
}

async function restartBackend(): Promise<void> {
  if (backend) {
    backend.kill();
    backend = null;
  }
  await startBackend();
  for (const win of [petWindow, dashboardWindow]) {
    win?.webContents.send("backend:restarted", { port: backendPort, token: backendToken });
  }
}

function showPetWindow(): void {
  if (!petWindow || petWindow.isDestroyed()) return;
  petWindow.show();
  applyPetAlwaysOnTop(appearancePreferences.alwaysOnTop);
  try {
    petWindow.moveTop();
  } catch {
    // moveTop is unavailable on Wayland.
  }
  petWindow.focus();
}

function updateTrayMenu(): void {
  if (!tray || tray.isDestroyed()) return;
  tray.setContextMenu(
    Menu.buildFromTemplate([
      { label: "显示桌面宠物", click: showPetWindow },
      { label: "展开聊天", click: expandPet },
      { label: "打开控制台", click: () => createDashboardWindow() },
      {
        label: "始终置顶",
        type: "checkbox",
        checked: appearancePreferences.alwaysOnTop,
        click: (item) => updateAppearancePreferences({ alwaysOnTop: item.checked })
      },
      { type: "separator" },
      { label: "重启 Agent", click: () => void restartBackend() },
      { label: "隐藏", click: () => petWindow?.hide() },
      {
        label: "退出程序",
        click: () => {
          quitting = true;
          app.quit();
        }
      }
    ])
  );
}

function createTray(): void {
  const iconPath = path.join(desktopRoot, "assets", "tray-icon.svg");
  const image = nativeImage.createFromPath(iconPath).resize({ width: 20, height: 20 });
  tray = new Tray(image);
  tray.setToolTip("桌面智能体");
  updateTrayMenu();
  tray.on("click", showPetWindow);
}

function showPetMenu(): void {
  Menu.buildFromTemplate([
    { label: expanded ? "收起聊天" : "展开聊天", click: expanded ? collapsePet : expandPet },
    { label: "打开控制台", click: () => createDashboardWindow() },
    { label: "隐藏", click: () => petWindow?.hide() },
    { label: "重启 Agent", click: () => void restartBackend() },
    { type: "separator" },
    {
      label: "退出程序",
      click: () => {
        quitting = true;
        app.quit();
      }
    }
  ]).popup({ window: petWindow || undefined });
}

function registerIpc(): void {
  ipcMain.handle("pet:expand", () => expandPet());
  ipcMain.handle("pet:collapse", () => collapsePet());
  ipcMain.handle("pet:is-expanded", () => expanded);
  ipcMain.handle("pet:show-menu", () => showPetMenu());
  ipcMain.handle("dashboard:open", (_event, section: unknown) => createDashboardWindow(normalizeDashboardSection(section)));
  ipcMain.handle("window:get-bounds", (event) => BrowserWindow.fromWebContents(event.sender)?.getBounds());
  ipcMain.handle(
    "pet:resize-expanded",
    (
      event,
      request: { edge?: unknown; deltaX?: unknown; deltaY?: unknown },
      persist = false
    ) => {
      const sourceWindow = BrowserWindow.fromWebContents(event.sender);
      if (!petWindow || sourceWindow !== petWindow || !expanded) {
        return sourceWindow?.getBounds() ?? null;
      }
      const currentBounds = petWindow.getBounds();
      const area = screen.getDisplayMatching(currentBounds).workArea;
      const validEdges = new Set<ResizeEdge>(["n", "ne", "e", "se", "s", "sw", "w", "nw"]);
      const edge = typeof request?.edge === "string" && validEdges.has(request.edge as ResizeEdge)
        ? request.edge as ResizeEdge
        : null;
      if (!edge) return currentBounds;
      const deltaX = typeof request.deltaX === "number" ? request.deltaX : 0;
      const deltaY = typeof request.deltaY === "number" ? request.deltaY : 0;
      const nextBounds = resizeChatBoundsBy(currentBounds, edge, deltaX, deltaY, area);
      petWindow.setBounds(nextBounds);
      applyExpandedShape(nextBounds);
      expandedSize = { width: nextBounds.width, height: nextBounds.height };
      syncCompactAnchorFromExpanded(nextBounds, persist);
      if (persist) writeJson(userFile("chat-window-size.json"), expandedSize);
      petWindow.webContents.invalidate();
      return nextBounds;
    }
  );
  ipcMain.handle("pet:set-position", (_event, point: { x: number; y: number }) => {
    if (!petWindow || expanded) return compactBounds;
    const next = clampCompactPosition(point.x, point.y);
    compactBounds = { ...next, width: COMPACT_SIZE, height: COMPACT_SIZE };
    petWindow.setPosition(next.x, next.y);
    writeJson(userFile("pet-position.json"), next);
    return compactBounds;
  });
  ipcMain.handle("backend:config", () => ({ port: backendPort, token: backendToken }));
  ipcMain.handle("backend:restart", () => restartBackend());
  ipcMain.handle("conversation:get-active", () => activeConversationId);
  ipcMain.handle("conversation:set-active", (_event, conversationId: unknown) =>
    setActiveConversation(conversationId)
  );
  ipcMain.handle("settings:get", () => {
    const settings = readJson<Record<string, string>>(userFile("settings.json"), {});
    const maxSteps = Math.min(100, Math.max(5, Math.round(Number(settings.maxSteps || "20")) || 20));
    return {
      provider: settings.provider || "openai",
      baseUrl: settings.baseUrl || "https://api.openai.com/v1",
      model: settings.model || "gpt-4o-mini",
      temperature: Number(settings.temperature || "0.2"),
      requestTimeout: Number(settings.requestTimeout || "60"),
      browserHeadless: settings.browserHeadless === "true",
      maxSteps,
      useCloakBrowser: settings.useCloakBrowser !== "false",
      apiKeyMasked: settings.apiKeyEncrypted ? "已安全保存" : ""
    };
  });
  ipcMain.handle("settings:save", async (_event, incoming: Record<string, unknown>) => {
    const existing = readJson<Record<string, string>>(userFile("settings.json"), {});
    const apiKey = String(incoming.apiKey || "").trim();
    if (apiKey) {
      if (!safeStorage.isEncryptionAvailable()) throw new Error("系统安全存储不可用");
      existing.apiKeyEncrypted = safeStorage.encryptString(apiKey).toString("base64");
    }
    existing.provider = String(incoming.provider || "openai");
    existing.baseUrl = String(incoming.baseUrl || "");
    existing.model = String(incoming.model || "");
    existing.temperature = String(incoming.temperature ?? 0.2);
    existing.requestTimeout = String(incoming.requestTimeout ?? 60);
    existing.browserHeadless = String(Boolean(incoming.browserHeadless));
    existing.maxSteps = String(
      Math.min(100, Math.max(5, Math.round(Number(incoming.maxSteps ?? 20)) || 20))
    );
    existing.useCloakBrowser = String(incoming.useCloakBrowser !== false);
    writeJson(userFile("settings.json"), existing);
    await restartBackend();
    return { ok: true, apiKeyMasked: existing.apiKeyEncrypted ? "已安全保存" : "" };
  });
  ipcMain.handle("appearance:get-preferences", () => appearancePreferences);
  ipcMain.handle(
    "appearance:update-preferences",
    (_event, patch: AppearanceUpdatePatch, options?: UpdateAppearanceOptions) =>
      updateAppearancePreferences(patch, options)
  );
  ipcMain.handle("appearance:delete-palette-history", (_event, historyId: unknown) =>
    deletePaletteHistory(historyId)
  );
  ipcMain.handle("appearance:clear-palette-history", () => clearPaletteHistory());
  ipcMain.handle("app:open-external", async (_event, url: unknown) => {
    if (typeof url !== "string" || !/^https:\/\//i.test(url)) {
      throw new TypeError("Only HTTPS links can be opened externally");
    }
    await shell.openExternal(url);
  });
  ipcMain.handle("app:quit", () => {
    quitting = true;
    app.quit();
  });
}

app.on("window-all-closed", () => {
  if (quitting) app.quit();
});

app.on("before-quit", () => {
  quitting = true;
  backend?.kill();
});

app.whenReady().then(async () => {
  const appearanceFile = userFile("ui-preferences.json");
  appearancePreferences = writeAppearancePreferences(
    appearanceFile,
    readAppearancePreferences(appearanceFile)
  );
  registerIpc();
  await startBackend();
  createPetWindow();
  createTray();
});

import {
  app,
  BrowserWindow,
  ipcMain,
  Menu,
  nativeImage,
  safeStorage,
  screen,
  Tray
} from "electron";
import { ChildProcessWithoutNullStreams, spawn } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs";
import net from "node:net";
import path from "node:path";
import { pathToFileURL } from "node:url";

const COMPACT_SIZE = 80;
const EXPANDED_WIDTH = 400;
const EXPANDED_HEIGHT = 600;

let petWindow: BrowserWindow | null = null;
let dashboardWindow: BrowserWindow | null = null;
let tray: Tray | null = null;
let backend: ChildProcessWithoutNullStreams | null = null;
let backendPort = 0;
let backendToken = "";
let expanded = false;
let compactBounds = { x: 0, y: 0, width: COMPACT_SIZE, height: COMPACT_SIZE };
let expandedAnchor = { right: true, bottom: true };
let quitting = false;

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

function syncCompactAnchorFromExpanded(bounds: Electron.Rectangle): void {
  const anchorX = expandedAnchor.right
    ? bounds.x + bounds.width - COMPACT_SIZE
    : bounds.x;
  const anchorY = expandedAnchor.bottom
    ? bounds.y + bounds.height - COMPACT_SIZE
    : bounds.y;
  const point = clampCompactPosition(anchorX, anchorY);
  compactBounds = { ...point, width: COMPACT_SIZE, height: COMPACT_SIZE };
  writeJson(userFile("pet-position.json"), point);
}

function rendererUrl(view: "pet" | "dashboard"): string {
  const url = pathToFileURL(path.join(desktopRoot, "dist", "index.html"));
  url.searchParams.set("view", view);
  return url.toString();
}

function createPetWindow(): void {
  compactBounds = initialCompactBounds();
  petWindow = new BrowserWindow({
    ...compactBounds,
    frame: false,
    transparent: true,
    resizable: false,
    alwaysOnTop: true,
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
  petWindow.setAlwaysOnTop(true, "floating");
  petWindow.loadURL(rendererUrl("pet"));
  petWindow.once("ready-to-show", () => petWindow?.show());
  petWindow.on("closed", () => {
    petWindow = null;
  });
  petWindow.on("moved", () => {
    if (!petWindow || !expanded) return;
    syncCompactAnchorFromExpanded(petWindow.getBounds());
  });
  applyCompactShape();
}

function applyCompactShape(): void {
  if (!petWindow || expanded || typeof petWindow.setShape !== "function") return;
  const rects: Electron.Rectangle[] = [];
  for (let y = 0; y < COMPACT_SIZE; y += 4) {
    const dy = y + 2 - COMPACT_SIZE / 2;
    const half = Math.sqrt(Math.max(0, (COMPACT_SIZE / 2) ** 2 - dy ** 2));
    rects.push({
      x: Math.round(COMPACT_SIZE / 2 - half),
      y,
      width: Math.max(1, Math.round(half * 2)),
      height: 4
    });
  }
  try {
    petWindow.setShape(rects);
  } catch {
    // setShape is not available on every platform/backend.
  }
}

function expandPet(): void {
  if (!petWindow || expanded) return;
  compactBounds = { ...petWindow.getBounds(), width: COMPACT_SIZE, height: COMPACT_SIZE };
  const display = screen.getDisplayMatching(compactBounds);
  const area = display.workArea;
  const rightAnchored = compactBounds.x + COMPACT_SIZE / 2 > area.x + area.width / 2;
  const bottomAnchored = compactBounds.y + COMPACT_SIZE / 2 > area.y + area.height / 2;
  expandedAnchor = { right: rightAnchored, bottom: bottomAnchored };
  const x = rightAnchored
    ? Math.max(area.x, compactBounds.x + COMPACT_SIZE - EXPANDED_WIDTH)
    : Math.min(compactBounds.x, area.x + area.width - EXPANDED_WIDTH);
  const y = bottomAnchored
    ? Math.max(area.y, compactBounds.y + COMPACT_SIZE - EXPANDED_HEIGHT)
    : Math.min(compactBounds.y, area.y + area.height - EXPANDED_HEIGHT);
  expanded = true;
  try {
    petWindow.setShape([{ x: 0, y: 0, width: EXPANDED_WIDTH, height: EXPANDED_HEIGHT }]);
  } catch {
    // Ignore unsupported shape reset.
  }
  petWindow.setBounds({ x, y, width: EXPANDED_WIDTH, height: EXPANDED_HEIGHT }, true);
  petWindow.webContents.send("pet:expanded", true);
}

function collapsePet(): void {
  if (!petWindow || !expanded) return;
  expanded = false;
  const point = clampCompactPosition(compactBounds.x, compactBounds.y);
  compactBounds = { ...point, width: COMPACT_SIZE, height: COMPACT_SIZE };
  petWindow.setBounds(compactBounds, true);
  applyCompactShape();
  petWindow.webContents.send("pet:expanded", false);
}

function createDashboardWindow(): BrowserWindow {
  if (dashboardWindow && !dashboardWindow.isDestroyed()) {
    dashboardWindow.show();
    dashboardWindow.focus();
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
  dashboardWindow.loadURL(rendererUrl("dashboard"));
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
  const env: NodeJS.ProcessEnv = {
    ...process.env,
    DESKTOP_AGENT_TOKEN: backendToken,
    LLM_PROVIDER: provider,
    BROWSER_HEADLESS: stored.browserHeadless || "false"
  };
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
  backend.stdout.on("data", (chunk) => broadcastLog(String(chunk).trim()));
  backend.stderr.on("data", (chunk) => broadcastLog(String(chunk).trim()));
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

function createTray(): void {
  const iconPath = path.join(desktopRoot, "assets", "tray-icon.svg");
  const image = nativeImage.createFromPath(iconPath).resize({ width: 20, height: 20 });
  tray = new Tray(image);
  tray.setToolTip("桌面智能体");
  tray.setContextMenu(
    Menu.buildFromTemplate([
      { label: "展开聊天", click: expandPet },
      { label: "打开控制台", click: () => createDashboardWindow() },
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
  tray.on("click", () => {
    petWindow?.show();
    petWindow?.focus();
  });
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
  ipcMain.handle("dashboard:open", () => createDashboardWindow());
  ipcMain.handle("window:get-bounds", (event) => BrowserWindow.fromWebContents(event.sender)?.getBounds());
  ipcMain.handle("window:set-position", (event, point: { x: number; y: number }) => {
    const window = BrowserWindow.fromWebContents(event.sender);
    if (!window) return null;
    const bounds = window.getBounds();
    const display = screen.getDisplayNearestPoint({
      x: Math.round(point.x + bounds.width / 2),
      y: Math.round(point.y + bounds.height / 2)
    });
    const area = display.workArea;
    const x = Math.min(Math.max(Math.round(point.x), area.x), area.x + area.width - bounds.width);
    const y = Math.min(Math.max(Math.round(point.y), area.y), area.y + area.height - bounds.height);
    window.setPosition(x, y);
    if (window === petWindow && expanded) {
      syncCompactAnchorFromExpanded(window.getBounds());
    }
    return window.getBounds();
  });
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
  ipcMain.handle("settings:get", () => {
    const settings = readJson<Record<string, string>>(userFile("settings.json"), {});
    return {
      provider: settings.provider || "openai",
      baseUrl: settings.baseUrl || "https://api.openai.com/v1",
      model: settings.model || "gpt-4o-mini",
      temperature: Number(settings.temperature || "0.2"),
      requestTimeout: Number(settings.requestTimeout || "60"),
      browserHeadless: settings.browserHeadless === "true",
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
    writeJson(userFile("settings.json"), existing);
    await restartBackend();
    return { ok: true, apiKeyMasked: existing.apiKeyEncrypted ? "已安全保存" : "" };
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
  registerIpc();
  await startBackend();
  createPetWindow();
  createTray();
});

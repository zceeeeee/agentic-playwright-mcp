import type { DesktopSettings } from "../types";

let backendConfig: { port: number; token: string } | null = null;

export async function refreshBackendConfig(): Promise<void> {
  backendConfig = await window.desktopAgent.getBackendConfig();
}

async function config() {
  if (!backendConfig) await refreshBackendConfig();
  return backendConfig!;
}

export async function apiRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const current = await config();
  const response = await fetch(`http://127.0.0.1:${current.port}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${current.token}`,
      ...(init.headers || {})
    }
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(body.detail || `HTTP ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export async function eventSocket(): Promise<WebSocket> {
  const current = await config();
  return new WebSocket(`ws://127.0.0.1:${current.port}/api/events?token=${current.token}`);
}

export const desktopSettings = {
  get: () => window.desktopAgent.getSettings(),
  save: (settings: DesktopSettings) => window.desktopAgent.saveSettings(settings)
};

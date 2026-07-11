export type AgentVisualState =
  | "idle"
  | "running"
  | "waiting_confirmation"
  | "success"
  | "error";

export type PetSkinId = "classic" | "animated-cat" | "maltese";

export type DashboardSection =
  | "chat"
  | "history"
  | "appearance"
  | "api"
  | "models"
  | "skills"
  | "browser"
  | "permissions"
  | "logs"
  | "about";

export interface AppearancePreferences {
  version: 1;
  skinId: PetSkinId;
}

export type ChatMessageType =
  | "user"
  | "assistant"
  | "system"
  | "progress"
  | "confirmation"
  | "error"
  | "result";

export interface ChatMessage {
  id: string;
  conversation_id: string;
  task_id?: string | null;
  role: "user" | "assistant" | "system";
  type: ChatMessageType;
  content: string;
  metadata?: Record<string, unknown>;
  created_at: string;
}

export interface Conversation {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  last_message?: string;
  task_status?: string;
}

export interface ConfirmationRequest {
  confirmation_id: string;
  task_id?: string;
  title: string;
  message: string;
  risk_level: string;
  prompt_type: "choice" | "input" | "confirm_value" | "confirmation";
  skill_name?: string;
  parameter_name?: string;
  current_value?: string | null;
  input_label?: string;
  input_required?: boolean;
  input_placeholder?: string;
  fields?: Array<Record<string, unknown>>;
  options?: ConfirmationOption[];
  actions?: ConfirmationOption[];
  status: "pending" | "approved" | "rejected";
  comment?: string;
  selected_value?: string;
  action_id?: string;
}

export interface ConfirmationOption {
  id: string;
  label: string;
  value?: string | null;
  description?: string;
}

export interface BackendEvent {
  event_id: string;
  type: string;
  task_id?: string | null;
  conversation_id?: string | null;
  timestamp: string;
  payload: Record<string, any>;
}

export interface RuntimeInfo {
  provider: string;
  model: string;
  api_key_masked: string;
  browser_headless: boolean;
}

export interface DesktopSettings {
  provider: string;
  apiKey?: string;
  apiKeyMasked?: string;
  baseUrl: string;
  model: string;
  temperature: number;
  requestTimeout: number;
  browserHeadless: boolean;
}

export interface DesktopBridge {
  expandChat(): Promise<void>;
  collapseChat(): Promise<void>;
  isExpanded(): Promise<boolean>;
  openDashboard(section?: DashboardSection): Promise<void>;
  setPetPosition(x: number, y: number): Promise<void>;
  resizeExpandedChat(
    edge: "n" | "ne" | "e" | "se" | "s" | "sw" | "w" | "nw",
    deltaX: number,
    deltaY: number,
    persist?: boolean
  ): Promise<{ x: number; y: number; width: number; height: number } | null>;
  getWindowBounds(): Promise<{ x: number; y: number; width: number; height: number }>;
  showPetMenu(): Promise<void>;
  restartBackend(): Promise<void>;
  getBackendConfig(): Promise<{ port: number; token: string }>;
  getSettings(): Promise<DesktopSettings>;
  saveSettings(settings: DesktopSettings): Promise<{ ok: boolean; apiKeyMasked: string }>;
  getAppearancePreferences(): Promise<AppearancePreferences>;
  setSkin(skinId: PetSkinId): Promise<AppearancePreferences>;
  quitApp(): Promise<void>;
  onBackendLog(callback: (message: string) => void): () => void;
  onExpandedChange(callback: (expanded: boolean) => void): () => void;
  onBackendRestarted(callback: () => void): () => void;
  onAppearanceChanged(callback: (preferences: AppearancePreferences) => void): () => void;
  onDashboardNavigate(callback: (section: DashboardSection) => void): () => void;
}

declare global {
  interface Window {
    desktopAgent: DesktopBridge;
  }
}

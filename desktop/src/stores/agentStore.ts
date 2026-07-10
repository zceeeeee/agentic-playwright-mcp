import { create } from "zustand";
import { apiRequest, eventSocket, refreshBackendConfig } from "../services/api";
import type {
  AgentVisualState,
  BackendEvent,
  ChatMessage,
  ConfirmationRequest,
  Conversation,
  RuntimeInfo
} from "../types";

interface AgentStore {
  visualState: AgentVisualState;
  currentConversationId: string | null;
  currentTaskId: string | null;
  conversations: Conversation[];
  messages: ChatMessage[];
  confirmations: ConfirmationRequest[];
  runtime: RuntimeInfo | null;
  backendConnected: boolean;
  initialized: boolean;
  logs: string[];
  initialize(): Promise<void>;
  reconnect(): Promise<void>;
  openConversation(id: string): Promise<void>;
  createConversation(): Promise<void>;
  renameConversation(id: string, title: string): Promise<void>;
  deleteConversation(id: string): Promise<void>;
  clearHistory(): Promise<void>;
  sendMessage(content: string): Promise<void>;
  approveConfirmation(id: string, value?: string, actionId?: string, comment?: string): Promise<void>;
  rejectConfirmation(id: string, comment?: string): Promise<void>;
  cancelCurrentTask(): Promise<void>;
  clearError(): void;
  handleBackendEvent(event: BackendEvent): void;
  addLog(message: string): void;
}

let socket: WebSocket | null = null;
let reconnectTimer: number | null = null;
const seenEvents = new Set<string>();

function dedupe(messages: ChatMessage[]): ChatMessage[] {
  const map = new Map<string, ChatMessage>();
  for (const message of messages) map.set(message.id, message);
  return Array.from(map.values()).sort((a, b) => a.created_at.localeCompare(b.created_at));
}

async function connectEvents(handle: (event: BackendEvent) => void, setConnected: (value: boolean) => void) {
  if (socket) socket.close();
  socket = await eventSocket();
  socket.onopen = () => setConnected(true);
  socket.onmessage = (message) => {
    const event = JSON.parse(message.data) as BackendEvent;
    if (seenEvents.has(event.event_id)) return;
    seenEvents.add(event.event_id);
    if (seenEvents.size > 2000) seenEvents.clear();
    handle(event);
  };
  socket.onclose = () => {
    setConnected(false);
    if (reconnectTimer !== null) window.clearTimeout(reconnectTimer);
    reconnectTimer = window.setTimeout(() => {
      void refreshBackendConfig()
        .then(() => connectEvents(handle, setConnected))
        .catch(() => undefined);
    }, 1500);
  };
}

export const useAgentStore = create<AgentStore>((set, get) => ({
  visualState: "idle",
  currentConversationId: null,
  currentTaskId: null,
  conversations: [],
  messages: [],
  confirmations: [],
  runtime: null,
  backendConnected: false,
  initialized: false,
  logs: [],

  initialize: async () => {
    if (get().initialized) return;
    await refreshBackendConfig();
    let conversations: Conversation[] = [];
    for (let attempt = 0; attempt < 20; attempt += 1) {
      try {
        conversations = await apiRequest<Conversation[]>("/api/conversations");
        break;
      } catch {
        await new Promise((resolve) => window.setTimeout(resolve, 250));
      }
    }
    if (!conversations.length) {
      const created = await apiRequest<Conversation>("/api/conversations", {
        method: "POST",
        body: JSON.stringify({ title: "新会话" })
      });
      conversations = [created];
    }
    const currentConversationId = conversations[0].id;
    const [messages, runtime] = await Promise.all([
      apiRequest<ChatMessage[]>(`/api/conversations/${currentConversationId}/messages`),
      apiRequest<RuntimeInfo>("/api/runtime")
    ]);
    set({ conversations, currentConversationId, messages, runtime, initialized: true });
    await connectEvents(get().handleBackendEvent, (backendConnected) => set({ backendConnected }));
  },

  reconnect: async () => {
    socket?.close();
    socket = null;
    await refreshBackendConfig();
    set({ backendConnected: false });
    await connectEvents(get().handleBackendEvent, (backendConnected) => set({ backendConnected }));
    const runtime = await apiRequest<RuntimeInfo>("/api/runtime");
    set({ runtime });
  },

  openConversation: async (id) => {
    const messages = await apiRequest<ChatMessage[]>(`/api/conversations/${id}/messages`);
    set({ currentConversationId: id, messages, confirmations: [] });
  },

  createConversation: async () => {
    const conversation = await apiRequest<Conversation>("/api/conversations", {
      method: "POST",
      body: JSON.stringify({ title: "新会话" })
    });
    set((state) => ({
      conversations: [conversation, ...state.conversations],
      currentConversationId: conversation.id,
      messages: [],
      confirmations: []
    }));
  },

  renameConversation: async (id, title) => {
    await apiRequest(`/api/conversations/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ title })
    });
    set((state) => ({
      conversations: state.conversations.map((item) => item.id === id ? { ...item, title } : item)
    }));
  },

  deleteConversation: async (id) => {
    await apiRequest(`/api/conversations/${id}`, { method: "DELETE" });
    const remaining = get().conversations.filter((item) => item.id !== id);
    set({ conversations: remaining });
    if (get().currentConversationId === id) {
      if (remaining.length) await get().openConversation(remaining[0].id);
      else await get().createConversation();
    }
  },

  clearHistory: async () => {
    await apiRequest("/api/conversations", { method: "DELETE" });
    set({ conversations: [], messages: [], currentConversationId: null });
    await get().createConversation();
  },

  sendMessage: async (content) => {
    const trimmed = content.trim();
    if (!trimmed) return;
    let conversationId = get().currentConversationId;
    if (!conversationId) {
      await get().createConversation();
      conversationId = get().currentConversationId;
    }
    const optimistic: ChatMessage = {
      id: `optimistic_${Date.now()}`,
      conversation_id: conversationId!,
      role: "user",
      type: "user",
      content: trimmed,
      created_at: new Date().toISOString()
    };
    set((state) => ({ messages: [...state.messages, optimistic], visualState: "running" }));
    const task = await apiRequest<{ id: string }>("/api/tasks", {
      method: "POST",
      body: JSON.stringify({ conversation_id: conversationId, content: trimmed, attachments: [] })
    });
    set({ currentTaskId: task.id });
  },

  approveConfirmation: async (id, value = "", actionId = "approve", comment = "") => {
    await apiRequest(`/api/confirmations/${id}/approve`, {
      method: "POST",
      body: JSON.stringify({ value, action_id: actionId, comment })
    });
  },

  rejectConfirmation: async (id, comment = "") => {
    await apiRequest(`/api/confirmations/${id}/reject`, {
      method: "POST",
      body: JSON.stringify({ comment })
    });
  },

  cancelCurrentTask: async () => {
    const taskId = get().currentTaskId;
    if (!taskId) return;
    await apiRequest(`/api/tasks/${taskId}/cancel`, { method: "POST" });
  },

  clearError: () => set({ visualState: "idle" }),

  handleBackendEvent: (event) => {
    const state = get();
    if (event.conversation_id && state.currentConversationId && event.conversation_id !== state.currentConversationId) {
      if (event.type === "agent_state_changed" && event.payload.state === "waiting_confirmation") {
        set({ visualState: "waiting_confirmation" });
      }
      return;
    }
    if (event.type === "agent_state_changed") {
      set({ visualState: event.payload.state as AgentVisualState });
      return;
    }
    if (event.type === "task_started") {
      set({ currentTaskId: event.task_id || null, visualState: "running" });
      return;
    }
    if (event.type === "task_cancelled") {
      set({ currentTaskId: null, visualState: "idle" });
      return;
    }
    if (event.type === "task_succeeded" || event.type === "task_failed") {
      set({ currentTaskId: null });
    }
    if (event.type === "assistant_message") {
      const incoming = event.payload.message as ChatMessage;
      set((current) => {
        const withoutOptimistic = incoming.role === "user"
          ? current.messages.filter((message) => !(message.id.startsWith("optimistic_") && message.content === incoming.content))
          : current.messages;
        return { messages: dedupe([...withoutOptimistic, incoming]) };
      });
      return;
    }
    if (event.type === "task_progress" && event.payload.stored_message) {
      set((current) => ({
        messages: dedupe([...current.messages, event.payload.stored_message as ChatMessage])
      }));
      return;
    }
    if (event.type === "confirmation_required") {
      const confirmation: ConfirmationRequest = {
        confirmation_id: event.payload.confirmation_id,
        task_id: event.task_id || undefined,
        title: event.payload.title,
        message: event.payload.message,
        risk_level: event.payload.risk_level,
        prompt_type: event.payload.prompt_type || "confirmation",
        skill_name: event.payload.skill_name,
        parameter_name: event.payload.parameter_name,
        current_value: event.payload.current_value,
        input_label: event.payload.input_label,
        input_required: event.payload.input_required,
        input_placeholder: event.payload.input_placeholder,
        fields: event.payload.fields,
        options: event.payload.options,
        actions: event.payload.actions,
        status: "pending"
      };
      set((current) => ({
        confirmations: [...current.confirmations.filter((item) => item.confirmation_id !== confirmation.confirmation_id), confirmation],
        visualState: "waiting_confirmation"
      }));
      return;
    }
    if (event.type === "confirmation_resolved") {
      set((current) => ({
        confirmations: current.confirmations.map((item) => item.confirmation_id === event.payload.confirmation_id
          ? {
              ...item,
              status: event.payload.status,
              comment: event.payload.comment,
              selected_value: event.payload.value,
              action_id: event.payload.action_id
            }
          : item)
      }));
    }
  },

  addLog: (message) => set((state) => ({ logs: [...state.logs.slice(-499), message] }))
}));

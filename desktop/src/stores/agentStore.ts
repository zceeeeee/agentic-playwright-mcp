import { create } from "zustand";
import { apiRequest, eventSocket, refreshBackendConfig } from "../services/api.js";
import type {
  AgentVisualState,
  BackendEvent,
  ChatMessage,
  ConfirmationRequest,
  Conversation,
  RuntimeInfo
} from "../types.js";

interface AgentStore {
  visualState: AgentVisualState;
  currentConversationId: string | null;
  conversationBusyId: string | null;
  conversationError: string | null;
  currentTaskId: string | null;
  chatDraft: string;
  conversations: Conversation[];
  messages: ChatMessage[];
  confirmations: ConfirmationRequest[];
  runtime: RuntimeInfo | null;
  backendConnected: boolean;
  initialized: boolean;
  logs: string[];
  initialize(): Promise<void>;
  reconnect(): Promise<void>;
  openConversation(id: string): Promise<boolean>;
  syncConversation(id: string): Promise<void>;
  createConversation(): Promise<void>;
  renameConversation(id: string, title: string): Promise<boolean>;
  deleteConversation(id: string): Promise<boolean>;
  clearHistory(): Promise<void>;
  setChatDraft(content: string): void;
  sendMessage(content: string): Promise<void>;
  approveConfirmation(id: string, value?: string, actionId?: string, comment?: string): Promise<void>;
  rejectConfirmation(id: string, comment?: string): Promise<void>;
  cancelCurrentTask(taskId?: string): Promise<void>;
  clearError(): void;
  handleBackendEvent(event: BackendEvent): void;
  addLog(message: string): void;
}

let socket: WebSocket | null = null;
let reconnectTimer: number | null = null;
let conversationSyncTimer: number | null = null;
let errorVisualStateTimer: number | null = null;
let pendingConversationId: string | null = null;
const seenEvents = new Set<string>();
const supersededTaskIds = new Set<string>();
const activeTaskStatuses = new Set(["queued", "running", "waiting_confirmation"]);
const ERROR_VISUAL_STATE_DURATION_MS = 10_000;

function cancelErrorVisualStateReset(): void {
  if (errorVisualStateTimer === null) return;
  window.clearTimeout(errorVisualStateTimer);
  errorVisualStateTimer = null;
}

function scheduleErrorVisualStateReset(reset: () => void): void {
  cancelErrorVisualStateReset();
  errorVisualStateTimer = window.setTimeout(() => {
    errorVisualStateTimer = null;
    reset();
  }, ERROR_VISUAL_STATE_DURATION_MS);
}

interface TaskSummary {
  id: string;
  conversation_id: string;
  status: string;
}

function activeTaskFrom(tasks: TaskSummary[]): TaskSummary | null {
  return tasks.find((task) => activeTaskStatuses.has(task.status)) || null;
}

function visualStateFor(task: TaskSummary | null): AgentVisualState {
  if (task?.status === "waiting_confirmation") return "waiting_confirmation";
  return task ? "running" : "idle";
}

async function loadConversationSnapshot(conversationId: string) {
  const [messages, tasks] = await Promise.all([
    apiRequest<ChatMessage[]>(`/api/conversations/${conversationId}/messages`),
    apiRequest<TaskSummary[]>(`/api/tasks?conversation_id=${encodeURIComponent(conversationId)}`)
  ]);
  const activeTask = activeTaskFrom(tasks);
  return { messages: dedupe(messages), activeTask, visualState: visualStateFor(activeTask) };
}

async function stopConversationResources(conversationId: string): Promise<void> {
  const tasks = await apiRequest<TaskSummary[]>(
    `/api/tasks?conversation_id=${encodeURIComponent(conversationId)}`
  );
  const activeTasks = tasks.filter((task) => activeTaskStatuses.has(task.status));
  await Promise.all(activeTasks.map(async (task) => {
    try {
      await apiRequest(`/api/tasks/${task.id}/cancel`, { method: "POST" });
    } catch {
      // A task may finish between listing and cancellation.
    }
  }));
  await apiRequest("/api/browser/close", { method: "POST" });
}

function dedupe(messages: ChatMessage[]): ChatMessage[] {
  const map = new Map<string, ChatMessage>();
  for (const message of messages) map.set(message.id, message);
  const unique = Array.from(map.values());
  const taskAnchors = new Map<string, string>();
  for (const message of unique) {
    if (!message.task_id) continue;
    const current = taskAnchors.get(message.task_id);
    if (!current || message.created_at < current) taskAnchors.set(message.task_id, message.created_at);
  }
  return unique.sort((a, b) => {
    const anchorA = a.task_id ? taskAnchors.get(a.task_id) || a.created_at : a.created_at;
    const anchorB = b.task_id ? taskAnchors.get(b.task_id) || b.created_at : b.created_at;
    const anchorOrder = anchorA.localeCompare(anchorB);
    if (anchorOrder) return anchorOrder;
    if (a.task_id && a.task_id === b.task_id) return a.created_at.localeCompare(b.created_at);
    return a.created_at.localeCompare(b.created_at) || a.id.localeCompare(b.id);
  });
}

function eventBelongsToCurrentTask(event: BackendEvent, currentTaskId: string | null): boolean {
  return !event.task_id || !currentTaskId || event.task_id === currentTaskId;
}

function markTasksSuperseded(messages: ChatMessage[], currentTaskId: string | null): void {
  if (currentTaskId) supersededTaskIds.add(currentTaskId);
  for (const message of messages) {
    if (message.task_id) supersededTaskIds.add(message.task_id);
  }
  while (supersededTaskIds.size > 2000) {
    const oldest = supersededTaskIds.values().next().value as string | undefined;
    if (!oldest) break;
    supersededTaskIds.delete(oldest);
  }
}

async function connectEvents(handle: (event: BackendEvent) => void, setConnected: (value: boolean) => void) {
  if (reconnectTimer !== null) {
    window.clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
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
  conversationBusyId: null,
  conversationError: null,
  currentTaskId: null,
  chatDraft: "",
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
    const sharedConversationId = await window.desktopAgent.getActiveConversation();
    const currentConversationId = conversations.some((item) => item.id === sharedConversationId)
      ? sharedConversationId!
      : conversations[0].id;
    const [snapshot, runtime] = await Promise.all([
      loadConversationSnapshot(currentConversationId),
      apiRequest<RuntimeInfo>("/api/runtime")
    ]);
    set({
      conversations,
      currentConversationId,
      messages: snapshot.messages,
      currentTaskId: snapshot.activeTask?.id || null,
      visualState: snapshot.visualState,
      runtime,
      initialized: true
    });
    await window.desktopAgent.setActiveConversation(currentConversationId);
    await connectEvents(get().handleBackendEvent, (backendConnected) => set({ backendConnected }));
  },

  reconnect: async () => {
    if (reconnectTimer !== null) {
      window.clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    socket?.close();
    socket = null;
    await refreshBackendConfig();
    set({ backendConnected: false });
    await connectEvents(get().handleBackendEvent, (backendConnected) => set({ backendConnected }));
    const runtime = await apiRequest<RuntimeInfo>("/api/runtime");
    set({ runtime });
  },

  openConversation: async (id) => {
    if (get().conversationBusyId) return false;
    if (get().currentConversationId === id) return true;
    set({ conversationBusyId: id, conversationError: null });
    try {
      const previousId = get().currentConversationId;
      if (previousId) await stopConversationResources(previousId);
      const snapshot = await loadConversationSnapshot(id);
      set({
        currentConversationId: id,
        messages: snapshot.messages,
        currentTaskId: snapshot.activeTask?.id || null,
        visualState: snapshot.visualState,
        confirmations: []
      });
      await window.desktopAgent.setActiveConversation(id);
      return true;
    } catch (error) {
      set({ conversationError: error instanceof Error ? error.message : "无法打开历史会话" });
      return false;
    } finally {
      set((state) => ({ conversationBusyId: state.conversationBusyId === id ? null : state.conversationBusyId }));
    }
  },

  syncConversation: async (id) => {
    if (!id || get().currentConversationId === id) return;
    if (!get().initialized || get().conversationBusyId) {
      pendingConversationId = id;
      if (conversationSyncTimer !== null) window.clearTimeout(conversationSyncTimer);
      conversationSyncTimer = window.setTimeout(() => {
        conversationSyncTimer = null;
        const pendingId = pendingConversationId;
        pendingConversationId = null;
        if (pendingId) void get().syncConversation(pendingId);
      }, 120);
      return;
    }
    set({ conversationBusyId: id, conversationError: null });
    try {
      const [conversations, snapshot] = await Promise.all([
        apiRequest<Conversation[]>("/api/conversations"),
        loadConversationSnapshot(id)
      ]);
      if (!conversations.some((item) => item.id === id)) return;
      set({
        conversations,
        currentConversationId: id,
        messages: snapshot.messages,
        currentTaskId: snapshot.activeTask?.id || null,
        visualState: snapshot.visualState,
        confirmations: []
      });
    } catch (error) {
      set({ conversationError: error instanceof Error ? error.message : "无法同步当前会话" });
    } finally {
      set((state) => ({ conversationBusyId: state.conversationBusyId === id ? null : state.conversationBusyId }));
    }
  },

  createConversation: async () => {
    if (get().conversationBusyId) return;
    set({ conversationBusyId: "new", conversationError: null });
    try {
      const previousId = get().currentConversationId;
      if (previousId) await stopConversationResources(previousId);
      const conversation = await apiRequest<Conversation>("/api/conversations", {
        method: "POST",
        body: JSON.stringify({ title: "新会话" })
      });
      set((state) => ({
        conversations: [conversation, ...state.conversations],
        currentConversationId: conversation.id,
        currentTaskId: null,
        visualState: "idle",
        messages: [],
        confirmations: []
      }));
      await window.desktopAgent.setActiveConversation(conversation.id);
    } catch (error) {
      set({ conversationError: error instanceof Error ? error.message : "新建会话失败" });
    } finally {
      set({ conversationBusyId: null });
    }
  },

  renameConversation: async (id, title) => {
    if (get().conversationBusyId) return false;
    const normalizedTitle = title.trim();
    if (!normalizedTitle) return false;
    set({ conversationBusyId: id, conversationError: null });
    try {
      await apiRequest(`/api/conversations/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ title: normalizedTitle })
      });
      set((state) => ({
        conversations: state.conversations.map((item) => item.id === id ? { ...item, title: normalizedTitle } : item)
      }));
      return true;
    } catch (error) {
      set({ conversationError: error instanceof Error ? error.message : "会话名称保存失败" });
      return false;
    } finally {
      set((state) => ({ conversationBusyId: state.conversationBusyId === id ? null : state.conversationBusyId }));
    }
  },

  deleteConversation: async (id) => {
    if (get().conversationBusyId) return false;
    set({ conversationBusyId: id, conversationError: null });
    try {
      const state = get();
      const remaining = state.conversations.filter((item) => item.id !== id);
      if (state.currentConversationId !== id) {
        await apiRequest(`/api/conversations/${id}`, { method: "DELETE" });
        set({ conversations: remaining });
        return true;
      }

      await stopConversationResources(id);
      let nextConversation: Conversation;
      let nextSnapshot = {
        messages: [] as ChatMessage[],
        activeTask: null as TaskSummary | null,
        visualState: "idle" as AgentVisualState
      };
      if (remaining.length) {
        nextConversation = remaining[0];
        nextSnapshot = await loadConversationSnapshot(nextConversation.id);
      } else {
        nextConversation = await apiRequest<Conversation>("/api/conversations", {
          method: "POST",
          body: JSON.stringify({ title: "新会话" })
        });
      }
      await apiRequest(`/api/conversations/${id}`, { method: "DELETE" });
      set({
        conversations: remaining.length ? remaining : [nextConversation],
        currentConversationId: nextConversation.id,
        currentTaskId: nextSnapshot.activeTask?.id || null,
        visualState: nextSnapshot.visualState,
        messages: nextSnapshot.messages,
        confirmations: []
      });
      await window.desktopAgent.setActiveConversation(nextConversation.id);
      return true;
    } catch (error) {
      set({ conversationError: error instanceof Error ? error.message : "会话删除失败" });
      return false;
    } finally {
      set((state) => ({ conversationBusyId: state.conversationBusyId === id ? null : state.conversationBusyId }));
    }
  },

  clearHistory: async () => {
    if (get().conversationBusyId) return;
    set({ conversationBusyId: "all", conversationError: null });
    try {
      const previousId = get().currentConversationId;
      if (previousId) await stopConversationResources(previousId);
      await apiRequest("/api/conversations", { method: "DELETE" });
      const conversation = await apiRequest<Conversation>("/api/conversations", {
        method: "POST",
        body: JSON.stringify({ title: "新会话" })
      });
      set({
        conversations: [conversation],
        messages: [],
        currentConversationId: conversation.id,
        currentTaskId: null,
        visualState: "idle",
        confirmations: []
      });
      await window.desktopAgent.setActiveConversation(conversation.id);
    } catch (error) {
      set({ conversationError: error instanceof Error ? error.message : "历史记录清空失败" });
    } finally {
      set({ conversationBusyId: null });
    }
  },

  setChatDraft: (chatDraft) => set({ chatDraft }),

  sendMessage: async (content) => {
    const trimmed = content.trim();
    if (!trimmed) return;
    let conversationId = get().currentConversationId;
    if (!conversationId) {
      await get().createConversation();
      conversationId = get().currentConversationId;
    }
    const previousState = get();
    markTasksSuperseded(previousState.messages, previousState.currentTaskId);
    if (previousState.currentTaskId && conversationId) {
      await stopConversationResources(conversationId);
      set({ currentTaskId: null, visualState: "idle", confirmations: [] });
    }
    const optimistic: ChatMessage = {
      id: `optimistic_${Date.now()}`,
      conversation_id: conversationId!,
      role: "user",
      type: "user",
      content: trimmed,
      created_at: new Date().toISOString()
    };
    set((state) => ({
      messages: [...state.messages, optimistic],
      confirmations: [],
      visualState: "running"
    }));
    const task = await apiRequest<{ id: string }>("/api/tasks", {
      method: "POST",
      body: JSON.stringify({ conversation_id: conversationId, content: trimmed, attachments: [] })
    });
    set((state) => ({
      currentTaskId: task.id,
      messages: dedupe(state.messages.map((message) => message.id === optimistic.id
        ? { ...message, task_id: task.id }
        : message))
    }));
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

  cancelCurrentTask: async (explicitTaskId) => {
    const taskId = explicitTaskId || get().currentTaskId;
    if (!taskId) return;
    // 乐观更新：立即显示取消状态和消息，后端会在检查点自行停止
    const conversationId = get().currentConversationId;
    const optimisticCancel: ChatMessage = {
      id: `optimistic_cancel_${Date.now()}`,
      conversation_id: conversationId || "",
      task_id: taskId,
      role: "system",
      type: "system",
      content: "任务已取消",
      created_at: new Date().toISOString()
    };
    cancelErrorVisualStateReset();
    set((state) => ({
      messages: [...state.messages, optimisticCancel],
      currentTaskId: null,
      visualState: "idle"
    }));
    void apiRequest(`/api/tasks/${taskId}/cancel`, { method: "POST" });
  },

  clearError: () => {
    cancelErrorVisualStateReset();
    set({ visualState: "idle" });
  },

  handleBackendEvent: (event) => {
    const state = get();
    if (event.conversation_id && state.currentConversationId && event.conversation_id !== state.currentConversationId) return;
    if (event.task_id && supersededTaskIds.has(event.task_id)) return;
    if (event.type === "agent_state_changed") {
      if (!eventBelongsToCurrentTask(event, state.currentTaskId)) return;
      const visualState = event.payload.state as AgentVisualState;
      cancelErrorVisualStateReset();
      set({ visualState });
      if (visualState === "error") {
        scheduleErrorVisualStateReset(() => {
          if (get().visualState === "error") set({ visualState: "idle" });
        });
      }
      return;
    }
    if (event.type === "task_created") {
      if (!eventBelongsToCurrentTask(event, state.currentTaskId)) return;
      cancelErrorVisualStateReset();
      set({ currentTaskId: event.task_id || null, visualState: "running" });
      return;
    }
    if (event.type === "task_started") {
      if (!eventBelongsToCurrentTask(event, state.currentTaskId)) return;
      cancelErrorVisualStateReset();
      set({ currentTaskId: event.task_id || null, visualState: "running" });
      return;
    }
    if (event.type === "task_cancelled") {
      if (!eventBelongsToCurrentTask(event, state.currentTaskId)) return;
      cancelErrorVisualStateReset();
      set({ currentTaskId: null, visualState: "idle" });
      return;
    }
    if (event.type === "task_succeeded") {
      if (!eventBelongsToCurrentTask(event, state.currentTaskId)) return;
      cancelErrorVisualStateReset();
      set({ currentTaskId: null });
    }
    if (event.type === "task_failed") {
      if (!eventBelongsToCurrentTask(event, state.currentTaskId)) return;
      set({ currentTaskId: null, visualState: "error" });
      scheduleErrorVisualStateReset(() => {
        if (get().visualState === "error") set({ visualState: "idle" });
      });
      return;
    }
    if (event.type === "assistant_message") {
      const incoming = event.payload.message as ChatMessage;
      set((current) => {
        const withoutOptimistic = current.messages.filter((message) => {
          // 过滤乐观用户消息
          if (incoming.role === "user" && message.id.startsWith("optimistic_") && message.content === incoming.content) return false;
          // 过滤乐观取消消息
          if (message.id.startsWith("optimistic_cancel_") && incoming.role === "system" && message.content === incoming.content) return false;
          return true;
        });
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
        default_value: event.payload.default_value,
        default_label: event.payload.default_label,
        input_label: event.payload.input_label,
        input_required: event.payload.input_required,
        input_placeholder: event.payload.input_placeholder,
        fields: event.payload.fields,
        options: event.payload.options,
        actions: event.payload.actions,
        non_blocking: Boolean(event.payload.non_blocking),
        status: "pending"
      };
      set((current) => ({
        confirmations: [...current.confirmations.filter((item) => item.confirmation_id !== confirmation.confirmation_id), confirmation],
        visualState: confirmation.non_blocking ? current.visualState : "waiting_confirmation"
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

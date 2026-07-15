import assert from "node:assert/strict";
import test from "node:test";
import { useAgentStore } from "../src/stores/agentStore.js";
import type { ChatMessage, Conversation } from "../src/types.js";

function installDesktopBridge() {
  const activeChanges: string[] = [];
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: {
      desktopAgent: {
        getBackendConfig: async () => ({ port: 43210, token: "test-token" }),
        getActiveConversation: async () => activeChanges.at(-1) || null,
        setActiveConversation: async (conversationId: string) => {
          activeChanges.push(conversationId);
          return conversationId;
        },
        onActiveConversationChange: () => () => undefined
      },
      setTimeout,
      clearTimeout
    }
  });
  return activeChanges;
}

function jsonResponse(value: unknown): Response {
  return {
    ok: true,
    json: async () => value
  } as Response;
}

test("deleting the active conversation prepares the next conversation first", async () => {
  installDesktopBridge();
  const conversations: Conversation[] = [
    { id: "conversation-a", title: "A", created_at: "1", updated_at: "2" },
    { id: "conversation-b", title: "B", created_at: "1", updated_at: "1" }
  ];
  const nextMessages: ChatMessage[] = [{
    id: "message-b",
    conversation_id: "conversation-b",
    role: "assistant",
    type: "assistant",
    content: "下一会话",
    created_at: "1"
  }];
  const calls: string[] = [];
  globalThis.fetch = (async (input: string | URL | Request, init?: RequestInit) => {
    const url = String(input);
    calls.push(`${init?.method || "GET"} ${url}`);
    if (url.includes("/api/tasks?conversation_id=")) return jsonResponse([]);
    if (url.endsWith("/api/conversations/conversation-b/messages")) {
      return jsonResponse(nextMessages);
    }
    return jsonResponse({ ok: true });
  }) as typeof fetch;
  useAgentStore.setState({
    conversations,
    currentConversationId: "conversation-a",
    messages: [],
    confirmations: [],
    conversationBusyId: null,
    conversationError: null
  });

  assert.equal(await useAgentStore.getState().deleteConversation("conversation-a"), true);
  assert.match(calls[0], /tasks\?conversation_id=conversation-a$/);
  assert.match(calls[1], /POST .*\/api\/browser\/close$/);
  assert.ok(calls.some((call) => /conversation-b\/messages$/.test(call)));
  assert.ok(calls.some((call) => /DELETE .*conversation-a$/.test(call)));
  assert.equal(useAgentStore.getState().currentConversationId, "conversation-b");
  assert.deepEqual(useAgentStore.getState().messages, nextMessages);
  assert.equal(useAgentStore.getState().conversationBusyId, null);
});

test("conversation rename and selection update the visible state", async () => {
  installDesktopBridge();
  const messages: ChatMessage[] = [{
    id: "message-c",
    conversation_id: "conversation-c",
    role: "user",
    type: "user",
    content: "内容",
    created_at: "1"
  }];
  globalThis.fetch = (async (input: string | URL | Request, init?: RequestInit) => {
    const url = String(input);
    if ((init?.method || "GET") === "PATCH") return jsonResponse({ ok: true });
    if (url.includes("/api/tasks?conversation_id=")) return jsonResponse([]);
    if (url.endsWith("/messages")) return jsonResponse(messages);
    return jsonResponse({ ok: true });
  }) as typeof fetch;
  useAgentStore.setState({
    conversations: [{ id: "conversation-c", title: "旧名称", created_at: "1", updated_at: "1" }],
    currentConversationId: null,
    messages: [],
    conversationBusyId: null,
    conversationError: null
  });

  assert.equal(await useAgentStore.getState().renameConversation("conversation-c", "新名称"), true);
  assert.equal(useAgentStore.getState().conversations[0].title, "新名称");
  assert.equal(await useAgentStore.getState().openConversation("conversation-c"), true);
  assert.equal(useAgentStore.getState().currentConversationId, "conversation-c");
  assert.deepEqual(useAgentStore.getState().messages, messages);
});

test("remote conversation selection restores its running task without stopping resources", async () => {
  installDesktopBridge();
  const conversations: Conversation[] = [
    { id: "conversation-a", title: "A", created_at: "1", updated_at: "1" },
    { id: "conversation-b", title: "B", created_at: "1", updated_at: "2" }
  ];
  const messages: ChatMessage[] = [
    {
      id: "old-user",
      conversation_id: "conversation-b",
      task_id: "task-old",
      role: "user",
      type: "user",
      content: "旧任务",
      created_at: "1"
    },
    {
      id: "message-b",
      conversation_id: "conversation-b",
      task_id: "task-b",
      role: "user",
      type: "user",
      content: "运行中的任务",
      created_at: "2"
    },
    {
      id: "old-answer",
      conversation_id: "conversation-b",
      task_id: "task-old",
      role: "assistant",
      type: "assistant",
      content: "迟到的旧任务回答",
      created_at: "3"
    }
  ];
  const calls: string[] = [];
  globalThis.fetch = (async (input: string | URL | Request) => {
    const url = String(input);
    calls.push(url);
    if (url.endsWith("/api/conversations")) return jsonResponse(conversations);
    if (url.endsWith("/api/conversations/conversation-b/messages")) return jsonResponse(messages);
    if (url.includes("/api/tasks?conversation_id=conversation-b")) {
      return jsonResponse([{ id: "task-b", conversation_id: "conversation-b", status: "running" }]);
    }
    return jsonResponse({ ok: true });
  }) as typeof fetch;
  useAgentStore.setState({
    initialized: true,
    conversations,
    currentConversationId: "conversation-a",
    currentTaskId: "task-a",
    messages: [],
    confirmations: [],
    conversationBusyId: null,
    conversationError: null
  });

  await useAgentStore.getState().syncConversation("conversation-b");

  assert.equal(useAgentStore.getState().currentConversationId, "conversation-b");
  assert.equal(useAgentStore.getState().currentTaskId, "task-b");
  assert.equal(useAgentStore.getState().visualState, "running");
  assert.deepEqual(
    useAgentStore.getState().messages.map((message) => message.id),
    ["old-user", "old-answer", "message-b"]
  );
  assert.equal(calls.some((url) => url.includes("/api/browser/close")), false);
});

test("local conversation switch cancels old tasks and closes the browser before publishing selection", async () => {
  const activeChanges = installDesktopBridge();
  const calls: string[] = [];
  globalThis.fetch = (async (input: string | URL | Request, init?: RequestInit) => {
    const url = String(input);
    calls.push(`${init?.method || "GET"} ${url}`);
    if (url.includes("/api/tasks?conversation_id=conversation-a")) {
      return jsonResponse([{ id: "task-a", conversation_id: "conversation-a", status: "running" }]);
    }
    if (url.includes("/api/tasks?conversation_id=conversation-b")) return jsonResponse([]);
    if (url.endsWith("/api/conversations/conversation-b/messages")) return jsonResponse([]);
    return jsonResponse({ ok: true });
  }) as typeof fetch;
  useAgentStore.setState({
    conversations: [
      { id: "conversation-a", title: "A", created_at: "1", updated_at: "1" },
      { id: "conversation-b", title: "B", created_at: "1", updated_at: "2" }
    ],
    currentConversationId: "conversation-a",
    currentTaskId: "task-a",
    conversationBusyId: null,
    conversationError: null
  });

  assert.equal(await useAgentStore.getState().openConversation("conversation-b"), true);
  const cancelIndex = calls.findIndex((call) => /POST .*\/api\/tasks\/task-a\/cancel$/.test(call));
  const closeIndex = calls.findIndex((call) => /POST .*\/api\/browser\/close$/.test(call));
  const loadIndex = calls.findIndex((call) => /conversation-b\/messages$/.test(call));
  assert.ok(cancelIndex >= 0);
  assert.ok(closeIndex > cancelIndex);
  assert.ok(loadIndex > closeIndex);
  assert.deepEqual(activeChanges, ["conversation-b"]);
});

test("confirmation cancellation can target its own task", async () => {
  installDesktopBridge();
  const calls: string[] = [];
  globalThis.fetch = (async (input: string | URL | Request, init?: RequestInit) => {
    calls.push(`${init?.method || "GET"} ${String(input)}`);
    return jsonResponse({ ok: true });
  }) as typeof fetch;
  useAgentStore.setState({ currentTaskId: "task-current" });

  await useAgentStore.getState().cancelCurrentTask("task-confirmation");

  assert.equal(calls.length, 1);
  assert.match(calls[0], /POST .*\/api\/tasks\/task-confirmation\/cancel$/);
});

test("starting a new task stops the previous task and closes its browser first", async () => {
  installDesktopBridge();
  const calls: string[] = [];
  globalThis.fetch = (async (input: string | URL | Request, init?: RequestInit) => {
    const url = String(input);
    calls.push(`${init?.method || "GET"} ${url}`);
    if (url.includes("/api/tasks?conversation_id=conversation-a")) {
      return jsonResponse([{ id: "task-old", conversation_id: "conversation-a", status: "running" }]);
    }
    if (url.endsWith("/api/tasks") && init?.method === "POST") return jsonResponse({ id: "task-new" });
    return jsonResponse({ ok: true });
  }) as typeof fetch;
  useAgentStore.setState({
    currentConversationId: "conversation-a",
    currentTaskId: "task-old",
    visualState: "running",
    messages: [],
    confirmations: [{
      confirmation_id: "confirm-old",
      task_id: "task-old",
      title: "旧确认",
      message: "旧任务确认",
      risk_level: "medium",
      prompt_type: "confirmation",
      status: "approved"
    }]
  });

  await useAgentStore.getState().sendMessage("新的任务");

  const cancelIndex = calls.findIndex((call) => /POST .*\/api\/tasks\/task-old\/cancel$/.test(call));
  const closeIndex = calls.findIndex((call) => /POST .*\/api\/browser\/close$/.test(call));
  const createIndex = calls.findIndex((call) => /POST .*\/api\/tasks$/.test(call));
  assert.ok(cancelIndex >= 0);
  assert.ok(closeIndex > cancelIndex);
  assert.ok(createIndex > closeIndex);
  assert.equal(useAgentStore.getState().currentTaskId, "task-new");
  assert.deepEqual(useAgentStore.getState().confirmations, []);
});

test("late events from a superseded task cannot enter the new task output", async () => {
  installDesktopBridge();
  globalThis.fetch = (async (input: string | URL | Request, init?: RequestInit) => {
    const url = String(input);
    if (url.includes("/api/tasks?conversation_id=conversation-a")) {
      return jsonResponse([{ id: "task-late-old", conversation_id: "conversation-a", status: "running" }]);
    }
    if (url.endsWith("/api/tasks") && init?.method === "POST") {
      return jsonResponse({ id: "task-late-new" });
    }
    return jsonResponse({ ok: true });
  }) as typeof fetch;
  useAgentStore.setState({
    currentConversationId: "conversation-a",
    currentTaskId: "task-late-old",
    visualState: "running",
    confirmations: [],
    messages: [
      {
        id: "old-user",
        conversation_id: "conversation-a",
        task_id: "task-late-old",
        role: "user",
        type: "user",
        content: "旧任务",
        created_at: "2026-01-01T00:00:01.000Z"
      }
    ]
  });

  await useAgentStore.getState().sendMessage("新任务");

  useAgentStore.getState().handleBackendEvent({
    event_id: "late-answer",
    type: "assistant_message",
    task_id: "task-late-old",
    conversation_id: "conversation-a",
    timestamp: "2026-01-01T00:00:03.000Z",
    payload: {
      message: {
        id: "old-answer",
        conversation_id: "conversation-a",
        task_id: "task-late-old",
        role: "assistant",
        type: "assistant",
        content: "旧任务回答",
        created_at: "2026-01-01T00:00:03.000Z"
      }
    }
  });
  useAgentStore.getState().handleBackendEvent({
    event_id: "late-progress",
    type: "task_progress",
    task_id: "task-late-old",
    conversation_id: "conversation-a",
    timestamp: "2026-01-01T00:00:03.500Z",
    payload: {
      stored_message: {
        id: "old-progress",
        conversation_id: "conversation-a",
        task_id: "task-late-old",
        role: "system",
        type: "progress",
        content: "旧任务日志",
        created_at: "2026-01-01T00:00:03.500Z"
      }
    }
  });
  useAgentStore.getState().handleBackendEvent({
    event_id: "late-confirmation",
    type: "confirmation_required",
    task_id: "task-late-old",
    conversation_id: "conversation-a",
    timestamp: "2026-01-01T00:00:03.750Z",
    payload: {
      confirmation_id: "confirm-late-old",
      title: "旧确认",
      message: "旧任务确认",
      risk_level: "medium"
    }
  });
  useAgentStore.getState().handleBackendEvent({
    event_id: "late-cancel",
    type: "task_cancelled",
    task_id: "task-late-old",
    conversation_id: "conversation-a",
    timestamp: "2026-01-01T00:00:04.000Z",
    payload: {}
  });
  useAgentStore.getState().handleBackendEvent({
    event_id: "late-state",
    type: "agent_state_changed",
    task_id: "task-late-old",
    conversation_id: "conversation-a",
    timestamp: "2026-01-01T00:00:05.000Z",
    payload: { state: "idle" }
  });
  useAgentStore.getState().handleBackendEvent({
    event_id: "late-start",
    type: "task_started",
    task_id: "task-late-old",
    conversation_id: "conversation-a",
    timestamp: "2026-01-01T00:00:06.000Z",
    payload: { state: "running" }
  });

  assert.deepEqual(
    useAgentStore.getState().messages.map((message) => message.content),
    ["旧任务", "新任务"]
  );
  assert.deepEqual(useAgentStore.getState().confirmations, []);
  assert.equal(useAgentStore.getState().currentTaskId, "task-late-new");
  assert.equal(useAgentStore.getState().visualState, "running");
});

test("wechat history events stay outside persisted chat messages", () => {
  installDesktopBridge();
  useAgentStore.setState({
    currentConversationId: "conversation-sensitive",
    currentTaskId: "task-sensitive",
    messages: [],
    confirmations: [],
    wechatHistoryResults: []
  });

  useAgentStore.getState().handleBackendEvent({
    event_id: "wechat-history-1",
    type: "wechat_history_result",
    task_id: "task-sensitive",
    conversation_id: "conversation-sensitive",
    timestamp: "2026-07-15T00:00:00.000Z",
    payload: {
      result_id: "sensitive-1",
      chat: "张三",
      chat_type: "private",
      is_group: false,
      count: 1,
      messages: [{
        timestamp: 1,
        time: "2026-07-15 08:00:00",
        sender: "张三",
        content: "敏感原文",
        type: "text",
        local_id: 1
      }],
      meta: { status: "ok", unknown_shards_count: 0 },
      warnings: [],
      sensitive: true,
      persist: false
    }
  });

  assert.deepEqual(useAgentStore.getState().messages, []);
  assert.equal(useAgentStore.getState().wechatHistoryResults.length, 1);
  assert.equal(
    useAgentStore.getState().wechatHistoryResults[0].messages[0].content,
    "敏感原文"
  );
});

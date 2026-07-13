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
  const messages: ChatMessage[] = [{
    id: "message-b",
    conversation_id: "conversation-b",
    role: "user",
    type: "user",
    content: "运行中的任务",
    created_at: "1"
  }];
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
  assert.deepEqual(useAgentStore.getState().messages, messages);
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

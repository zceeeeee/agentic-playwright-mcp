import { Send, Square } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { useAgentStore } from "../stores/agentStore";
import { collectCommandHistory, navigateCommandHistory } from "../utils/commandHistory";
import { getEnterKeyAction } from "../utils/keyboard";

export function ChatInput() {
  const content = useAgentStore((state) => state.chatDraft);
  const setContent = useAgentStore((state) => state.setChatDraft);
  const sendMessage = useAgentStore((state) => state.sendMessage);
  const cancel = useAgentStore((state) => state.cancelCurrentTask);
  const currentTaskId = useAgentStore((state) => state.currentTaskId);
  const conversationBusyId = useAgentStore((state) => state.conversationBusyId);
  const messages = useAgentStore((state) => state.messages);
  const commandHistory = useMemo(() => collectCommandHistory(messages), [messages]);
  const [historyIndex, setHistoryIndex] = useState<number | null>(null);
  const draftBeforeHistory = useRef("");

  async function submit() {
    const value = content.trim();
    if (!value || conversationBusyId) return;
    await sendMessage(value);
    setContent("");
    setHistoryIndex(null);
    draftBeforeHistory.current = "";
  }

  function browseHistory(direction: "previous" | "next") {
    const next = navigateCommandHistory(
      commandHistory,
      content,
      historyIndex,
      draftBeforeHistory.current,
      direction
    );
    setContent(next.value);
    setHistoryIndex(next.index);
    draftBeforeHistory.current = next.draft;
  }

  return (
    <div className="chat-input-wrap">
      {currentTaskId ? (
        <button className="stop-task" onClick={() => void cancel()}>
          <Square size={14} fill="currentColor" />停止任务
        </button>
      ) : null}
      <div className="chat-input-row">
        <span className="command-prompt" aria-hidden="true">&gt;_</span>
        <textarea
          value={content}
          rows={2}
          placeholder={currentTaskId ? "发送补充信息" : "输入任务内容"}
          aria-label={currentTaskId ? "发送补充信息" : "输入任务内容"}
          onChange={(event) => {
            setContent(event.target.value);
            setHistoryIndex(null);
            draftBeforeHistory.current = event.target.value;
          }}
          onKeyDown={(event) => {
            if (!event.nativeEvent.isComposing && !event.ctrlKey && !event.altKey && !event.metaKey) {
              if (event.key === "ArrowUp" && commandHistory.length) {
                event.preventDefault();
                browseHistory("previous");
                return;
              }
              if (event.key === "ArrowDown" && historyIndex !== null) {
                event.preventDefault();
                browseHistory("next");
                return;
              }
            }
            const action = getEnterKeyAction(event.key, event.ctrlKey, event.nativeEvent.isComposing);
            if (action === "submit") {
              event.preventDefault();
              void submit();
            }
          }}
        />
        <button className="icon-command send-button" title="发送" disabled={!content.trim() || Boolean(conversationBusyId)} onClick={() => void submit()}>
          <Send size={18} />
        </button>
      </div>
    </div>
  );
}

import { Send, Square } from "lucide-react";
import { useAgentStore } from "../stores/agentStore";
import { getEnterKeyAction } from "../utils/keyboard";

export function ChatInput() {
  const content = useAgentStore((state) => state.chatDraft);
  const setContent = useAgentStore((state) => state.setChatDraft);
  const sendMessage = useAgentStore((state) => state.sendMessage);
  const cancel = useAgentStore((state) => state.cancelCurrentTask);
  const currentTaskId = useAgentStore((state) => state.currentTaskId);
  const conversationBusyId = useAgentStore((state) => state.conversationBusyId);

  async function submit() {
    const value = content.trim();
    if (!value || conversationBusyId) return;
    await sendMessage(value);
    setContent("");
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
          onChange={(event) => setContent(event.target.value)}
          onKeyDown={(event) => {
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

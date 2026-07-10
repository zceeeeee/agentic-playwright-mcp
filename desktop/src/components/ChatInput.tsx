import { useState } from "react";
import { Send, Square } from "lucide-react";
import { useAgentStore } from "../stores/agentStore";

export function ChatInput() {
  const [content, setContent] = useState("");
  const sendMessage = useAgentStore((state) => state.sendMessage);
  const cancel = useAgentStore((state) => state.cancelCurrentTask);
  const currentTaskId = useAgentStore((state) => state.currentTaskId);

  async function submit() {
    const value = content.trim();
    if (!value) return;
    setContent("");
    await sendMessage(value);
  }

  return (
    <div className="chat-input-wrap">
      {currentTaskId ? (
        <button className="stop-task" onClick={() => void cancel()}>
          <Square size={14} fill="currentColor" />停止任务
        </button>
      ) : null}
      <div className="chat-input-row">
        <textarea
          value={content}
          rows={2}
          placeholder={currentTaskId ? "发送补充信息" : "输入任务内容"}
          onChange={(event) => setContent(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              void submit();
            }
          }}
        />
        <button className="icon-command send-button" title="发送" disabled={!content.trim()} onClick={() => void submit()}>
          <Send size={18} />
        </button>
      </div>
    </div>
  );
}

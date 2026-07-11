import { MessageSquarePlus, Pencil, Trash2, X } from "lucide-react";
import { useAgentStore } from "../stores/agentStore";

export function HistoryPanel({ onClose }: { onClose: () => void }) {
  const store = useAgentStore();

  return (
    <aside className="history-panel">
      <header className="draggable-header">
        <strong>历史会话</strong>
        <div className="toolbar-actions" data-no-drag>
          <button title="新建会话" onClick={() => void store.createConversation()}><MessageSquarePlus size={17} /></button>
          <button title="关闭历史" onClick={onClose}><X size={17} /></button>
        </div>
      </header>
      <div className="history-list">
        {store.conversations.map((conversation) => (
          <div className={`history-row ${store.currentConversationId === conversation.id ? "active" : ""}`} key={conversation.id}>
            <button className="history-main" onClick={() => { void store.openConversation(conversation.id); onClose(); }}>
              <strong>{conversation.title}</strong>
              <span>{conversation.last_message || "暂无消息"}</span>
            </button>
            <button title="重命名" onClick={() => {
              const title = window.prompt("新的会话标题", conversation.title);
              if (title?.trim()) void store.renameConversation(conversation.id, title.trim());
            }}><Pencil size={14} /></button>
            <button title="删除" onClick={() => {
              if (window.confirm(`删除会话“${conversation.title}”？`)) void store.deleteConversation(conversation.id);
            }}><Trash2 size={14} /></button>
          </div>
        ))}
      </div>
      <button className="clear-history" onClick={() => {
        if (window.confirm("清空全部历史记录？此操作不能撤销。")) void store.clearHistory();
      }}>清空全部历史</button>
    </aside>
  );
}

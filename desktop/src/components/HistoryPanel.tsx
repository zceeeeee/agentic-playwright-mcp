import { useState } from "react";
import { Check, LoaderCircle, MessageSquarePlus, Pencil, Trash2, X } from "lucide-react";
import { useAgentStore } from "../stores/agentStore";

export function HistoryPanel({ onClose }: { onClose: () => void }) {
  const store = useAgentStore();
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState("");

  async function selectConversation(id: string) {
    if (editingId || store.conversationBusyId) return;
    if (store.currentConversationId === id) {
      onClose();
      return;
    }
    if (await store.openConversation(id)) onClose();
  }

  function startEditing(id: string, title: string) {
    if (store.conversationBusyId) return;
    setEditingId(id);
    setEditingTitle(title);
  }

  async function saveTitle() {
    if (!editingId || !editingTitle.trim()) return;
    if (await store.renameConversation(editingId, editingTitle)) {
      setEditingId(null);
      setEditingTitle("");
    }
  }

  return (
    <aside className="history-panel">
      <header className="draggable-header">
        <strong>历史会话</strong>
        <div className="toolbar-actions" data-no-drag>
          <button title="新建会话" disabled={Boolean(store.conversationBusyId)} onClick={() => void store.createConversation()}><MessageSquarePlus size={17} /></button>
          <button title="关闭历史" onClick={onClose}><X size={17} /></button>
        </div>
      </header>
      <div className="history-list">
        {store.conversations.map((conversation) => {
          const editing = editingId === conversation.id;
          const busy = store.conversationBusyId === conversation.id;
          return (
            <div className={`history-row ${store.currentConversationId === conversation.id ? "active" : ""} ${editing ? "editing" : ""}`} key={conversation.id}>
              {editing ? (
                <input
                  className="history-title-input"
                  aria-label="会话名称"
                  value={editingTitle}
                  maxLength={120}
                  autoFocus
                  onChange={(event) => setEditingTitle(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      event.preventDefault();
                      void saveTitle();
                    } else if (event.key === "Escape") {
                      setEditingId(null);
                    }
                  }}
                />
              ) : (
                <button className="history-main" disabled={Boolean(store.conversationBusyId)} onClick={() => void selectConversation(conversation.id)}>
                  <strong>{conversation.title}</strong>
                  <span>{conversation.last_message || "暂无消息"}</span>
                </button>
              )}
              {editing ? (
                <button title="保存名称" disabled={busy || !editingTitle.trim()} onClick={() => void saveTitle()}>{busy ? <LoaderCircle className="spin" size={14} /> : <Check size={14} />}</button>
              ) : (
                <button title="编辑名称" disabled={Boolean(store.conversationBusyId)} onClick={() => startEditing(conversation.id, conversation.title)}><Pencil size={14} /></button>
              )}
              {editing ? (
                <button title="取消编辑" disabled={busy} onClick={() => setEditingId(null)}><X size={14} /></button>
              ) : (
                <button title="删除会话" disabled={Boolean(store.conversationBusyId)} onClick={() => {
                  if (window.confirm(`删除会话“${conversation.title}”？`)) void store.deleteConversation(conversation.id);
                }}>{busy ? <LoaderCircle className="spin" size={14} /> : <Trash2 size={14} />}</button>
              )}
            </div>
          );
        })}
        {store.conversationError ? <p className="history-error" role="alert">{store.conversationError}</p> : null}
      </div>
      <button className="clear-history" disabled={Boolean(store.conversationBusyId)} onClick={() => {
        if (window.confirm("清空全部历史记录？此操作不能撤销。")) void store.clearHistory();
      }}>清空全部历史</button>
    </aside>
  );
}

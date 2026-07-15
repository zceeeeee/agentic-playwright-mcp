import { useState } from "react";
import { AlertTriangle, Bot, ChevronDown, ChevronUp, Clock3, MessagesSquare } from "lucide-react";
import { useAgentStore } from "../stores/agentStore";
import type { WeChatHistoryMessage, WeChatHistoryResult } from "../types/wechatHistory";

const typeLabels: Record<string, string> = {
  image: "[图片]",
  voice: "[语音]",
  video: "[视频]",
  sticker: "[表情]",
  location: "[位置]",
  link: "[链接]",
  file: "[文件]",
  call: "[通话]",
  system: "[系统消息]"
};

function senderName(message: WeChatHistoryMessage): string {
  return message.sender_group_nickname
    || message.sender_contact_display
    || message.sender
    || "未知发送者";
}

function messageContent(message: WeChatHistoryMessage): string {
  const prefix = typeLabels[message.type] || "";
  if (message.type === "text") return message.content || "[空消息]";
  return [prefix || `[${message.type || "未知类型"}]`, message.content].filter(Boolean).join(" ");
}

function HistoryMessage({ message }: { message: WeChatHistoryMessage }) {
  const [expanded, setExpanded] = useState(false);
  const content = messageContent(message);
  const long = content.length > 500;
  const visible = long && !expanded ? `${content.slice(0, 500)}…` : content;
  return (
    <article className="wechat-history-message">
      <header>
        <strong>{senderName(message)}</strong>
        <time>{message.time || "时间未知"}</time>
      </header>
      <p>{visible}</p>
      {long ? (
        <button className="text-action" onClick={() => setExpanded((value) => !value)}>
          {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          {expanded ? "收起" : "展开全文"}
        </button>
      ) : null}
    </article>
  );
}

export function WeChatHistoryCard({
  result,
  compact = true
}: {
  result: WeChatHistoryResult;
  compact?: boolean;
}) {
  const loadEarlier = useAgentStore((state) => state.loadEarlierWechatHistory);
  const summarize = useAgentStore((state) => state.summarizeWechatHistory);
  const runtime = useAgentStore((state) => state.runtime);
  const [loading, setLoading] = useState(false);
  const [summaryPrompt, setSummaryPrompt] = useState(false);
  const [error, setError] = useState("");
  const visibleMessages = compact ? result.messages.slice(0, 50) : result.messages;
  const chatType = result.chat_type === "group" ? "群聊" : result.chat_type === "private" ? "私聊" : result.chat_type;

  async function loadMore() {
    setLoading(true);
    setError("");
    try {
      await loadEarlier(result.result_id, 50);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "加载更早记录失败");
    } finally {
      setLoading(false);
    }
  }

  async function confirmSummary() {
    setLoading(true);
    setError("");
    try {
      await summarize(result.result_id);
      setSummaryPrompt(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "AI 总结失败");
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="wechat-history-card" aria-label={`微信历史记录：${result.chat}`}>
      <header className="wechat-history-heading">
        <MessagesSquare size={19} aria-hidden="true" />
        <div>
          <strong>微信历史记录</strong>
          <span>{result.chat} · {chatType || "类型未知"} · {result.count} 条</span>
        </div>
        <span className="sensitive-badge">仅本机临时显示</span>
      </header>

      <div className="wechat-history-messages">
        {visibleMessages.map((message, index) => (
          <HistoryMessage
            key={`${message.local_id ?? "message"}-${message.timestamp ?? "time"}-${index}`}
            message={message}
          />
        ))}
        {!visibleMessages.length ? <p className="empty-sensitive-result">该范围内没有消息。</p> : null}
      </div>

      {result.warnings.map((warning) => (
        <div className="wechat-history-warning" key={warning}>
          <AlertTriangle size={16} aria-hidden="true" />
          <span>{warning}</span>
        </div>
      ))}
      {compact && result.messages.length > 50 ? (
        <div className="wechat-history-info"><Clock3 size={15} />小窗口仅展示前 50 条，请在完整控制台查看全部记录。</div>
      ) : null}
      {error ? <div className="wechat-history-error">{error}</div> : null}

      {summaryPrompt ? (
        <div className="wechat-summary-confirmation">
          <strong>允许 AI 分析这些聊天记录？</strong>
          <p>原文将发送给当前配置的 {runtime?.provider || "AI"} / {runtime?.model || "当前模型"}。总结可以保存，原文仍不会写入历史。</p>
          <div>
            <button className="button-primary" disabled={loading} onClick={() => void confirmSummary()}><Bot size={15} />确认并总结</button>
            <button className="button-secondary" disabled={loading} onClick={() => setSummaryPrompt(false)}>取消</button>
          </div>
        </div>
      ) : null}

      <footer className="wechat-history-actions">
        <button className="button-secondary" disabled={loading} onClick={() => void loadMore()}>
          <ChevronDown size={15} />{loading ? "处理中" : "加载更早 50 条"}
        </button>
        <button className="button-secondary" disabled={loading || summaryPrompt} onClick={() => setSummaryPrompt(true)}>
          <Bot size={15} />允许 AI 总结
        </button>
      </footer>
    </section>
  );
}

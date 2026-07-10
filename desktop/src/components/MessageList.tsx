import { useEffect, useRef } from "react";
import { useAgentStore } from "../stores/agentStore";
import { ConfirmationCard } from "./ConfirmationCard";
import { MessageItem } from "./MessageItem";

export function MessageList() {
  const messages = useAgentStore((state) => state.messages);
  const confirmations = useAgentStore((state) => state.confirmations);
  const sendMessage = useAgentStore((state) => state.sendMessage);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages.length, confirmations.length]);

  const lastUserMessage = [...messages].reverse().find((message) => message.role === "user");

  return (
    <div className="message-list" aria-live="polite">
      {!messages.length && !confirmations.length ? (
        <div className="empty-chat">
          <strong>输入一个任务开始</strong>
          <span>执行进度、确认请求和最终结果会显示在这里。</span>
        </div>
      ) : null}
      {messages.map((message) => (
        <MessageItem
          key={message.id}
          message={message}
          onRetry={lastUserMessage ? () => void sendMessage(lastUserMessage.content) : undefined}
        />
      ))}
      {confirmations.map((confirmation) => (
        <ConfirmationCard key={confirmation.confirmation_id} confirmation={confirmation} />
      ))}
      <div ref={endRef} />
    </div>
  );
}

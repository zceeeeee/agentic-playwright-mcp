import { useState } from "react";
import { ChevronDown, History, Maximize2, MoreHorizontal, Wifi, WifiOff } from "lucide-react";
import { useAgentStore } from "../stores/agentStore";
import { useWindowDrag } from "../hooks/useWindowDrag";
import { ChatInput } from "./ChatInput";
import { HistoryPanel } from "./HistoryPanel";
import { MessageList } from "./MessageList";

const labels = {
  idle: "空闲",
  running: "正在执行",
  waiting_confirmation: "等待确认",
  success: "已完成",
  error: "执行失败"
};

export function ChatPanel({ dashboard = false }: { dashboard?: boolean }) {
  const [historyOpen, setHistoryOpen] = useState(false);
  const state = useAgentStore((store) => store.visualState);
  const runtime = useAgentStore((store) => store.runtime);
  const connected = useAgentStore((store) => store.backendConnected);
  const windowDrag = useWindowDrag(!dashboard);

  return (
    <section className={`chat-panel ${dashboard ? "dashboard-chat" : ""}`}>
      <header className={`chat-header ${dashboard ? "" : "draggable-header"}`} {...windowDrag}>
        <div className={`mini-pet state-${state}`} aria-hidden="true" />
        <div className="agent-heading">
          <strong>桌面智能体</strong>
          <span>{labels[state]} · {runtime?.model || "规则模式"}</span>
        </div>
        <div className="toolbar-actions">
          <span className="connection-indicator" title={connected ? "后端已连接" : "后端连接中"}>
            {connected ? <Wifi size={15} /> : <WifiOff size={15} />}
          </span>
          <button title="历史记录" onClick={() => setHistoryOpen(true)}><History size={17} /></button>
          {!dashboard ? <button title="打开完整控制台" onClick={() => void window.desktopAgent.openDashboard()}><Maximize2 size={17} /></button> : null}
          {!dashboard ? <button title="收起" onClick={() => void window.desktopAgent.collapseChat()}><ChevronDown size={18} /></button> : null}
          <button title="更多" onClick={() => void window.desktopAgent.showPetMenu()}><MoreHorizontal size={18} /></button>
        </div>
      </header>
      <MessageList />
      <ChatInput />
      {historyOpen ? <HistoryPanel onClose={() => setHistoryOpen(false)} /> : null}
    </section>
  );
}

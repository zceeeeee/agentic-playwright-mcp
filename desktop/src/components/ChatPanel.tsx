import { useState } from "react";
import { ChevronDown, History, Maximize2, MoreHorizontal, Settings, Wifi, WifiOff } from "lucide-react";
import { AGENT_STATE_LABELS } from "../skins/skinRegistry";
import { useAgentStore } from "../stores/agentStore";
import { useAppearanceStore } from "../stores/appearanceStore";
import { ChatInput } from "./ChatInput";
import { HistoryPanel } from "./HistoryPanel";
import { MessageList } from "./MessageList";
import { PetAvatar } from "./PetAvatar";
import { WindowResizeHandles } from "./WindowResizeHandles";

export function ChatPanel({ dashboard = false }: { dashboard?: boolean }) {
  const [historyOpen, setHistoryOpen] = useState(false);
  const state = useAgentStore((store) => store.visualState);
  const runtime = useAgentStore((store) => store.runtime);
  const connected = useAgentStore((store) => store.backendConnected);
  const skinId = useAppearanceStore((store) => store.skinId);

  return (
    <section className={`chat-panel ${dashboard ? "dashboard-chat" : ""}`}>
      <header className={`chat-header ${dashboard ? "" : "draggable-header"}`}>
        <PetAvatar skinId={skinId} state={state} variant="mini" />
        <div className="agent-heading">
          <strong>桌面智能体</strong>
          <span>{AGENT_STATE_LABELS[state]} · {runtime?.model || "规则模式"}</span>
        </div>
        <div className="toolbar-actions" data-no-drag>
          <span className="connection-indicator" data-no-drag title={connected ? "后端已连接" : "后端连接中"}>
            {connected ? <Wifi size={15} /> : <WifiOff size={15} />}
          </span>
          <button title="历史记录" onClick={() => setHistoryOpen(true)}><History size={17} /></button>
          <button title="外观与皮肤" aria-label="打开外观与皮肤设置" onClick={() => void window.desktopAgent.openDashboard("appearance")}><Settings size={17} /></button>
          {!dashboard ? <button title="打开完整控制台" onClick={() => void window.desktopAgent.openDashboard()}><Maximize2 size={17} /></button> : null}
          {!dashboard ? <button title="收起" onClick={() => void window.desktopAgent.collapseChat()}><ChevronDown size={18} /></button> : null}
          <button title="更多" onClick={() => void window.desktopAgent.showPetMenu()}><MoreHorizontal size={18} /></button>
        </div>
      </header>
      <MessageList compact={!dashboard} />
      <ChatInput />
      {historyOpen ? <HistoryPanel onClose={() => setHistoryOpen(false)} /> : null}
      {!dashboard ? <WindowResizeHandles /> : null}
    </section>
  );
}

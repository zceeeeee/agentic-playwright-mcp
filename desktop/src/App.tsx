import { useEffect, useState } from "react";
import { ChatPanel } from "./components/ChatPanel";
import { PetCircle } from "./components/PetCircle";
import { DashboardPage } from "./pages/DashboardPage";
import { useAgentStore } from "./stores/agentStore";
import { useAppearanceStore } from "./stores/appearanceStore";
import { applyAppearanceToDocument } from "./utils/applyAppearance";

export default function App() {
  const view = new URLSearchParams(window.location.search).get("view") || "pet";
  const initialize = useAgentStore((state) => state.initialize);
  const reconnect = useAgentStore((state) => state.reconnect);
  const syncConversation = useAgentStore((state) => state.syncConversation);
  const addLog = useAgentStore((state) => state.addLog);
  const initializeAppearance = useAppearanceStore((state) => state.initializeAppearance);
  const disposeAppearance = useAppearanceStore((state) => state.disposeAppearance);
  const skinId = useAppearanceStore((state) => state.skinId);
  const palette = useAppearanceStore((state) => state.palette);
  const typography = useAppearanceStore((state) => state.typography);
  const [expanded, setExpanded] = useState(view === "dashboard");

  useEffect(() => {
    document.title = view === "dashboard" ? "桌面智能体控制台" : "桌面智能体";
    void initialize();
    const removeLog = window.desktopAgent.onBackendLog(addLog);
    const removeExpanded = window.desktopAgent.onExpandedChange(setExpanded);
    const removeRestarted = window.desktopAgent.onBackendRestarted(() => void reconnect());
    const removeConversation = window.desktopAgent.onActiveConversationChange(
      (conversationId) => void syncConversation(conversationId)
    );
    if (view === "pet") void window.desktopAgent.isExpanded().then(setExpanded);
    return () => {
      removeLog();
      removeExpanded();
      removeRestarted();
      removeConversation();
    };
  }, [addLog, initialize, reconnect, syncConversation, view]);

  useEffect(() => {
    void initializeAppearance();
    return disposeAppearance;
  }, [disposeAppearance, initializeAppearance]);

  useEffect(() => {
    document.documentElement.dataset.petSkin = skinId;
  }, [skinId]);

  useEffect(() => {
    applyAppearanceToDocument(palette, typography);
  }, [palette, typography]);

  if (view === "dashboard") return <DashboardPage />;
  return expanded ? <ChatPanel /> : <PetCircle />;
}

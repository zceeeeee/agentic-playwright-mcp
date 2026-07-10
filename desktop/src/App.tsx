import { useEffect, useState } from "react";
import { ChatPanel } from "./components/ChatPanel";
import { PetCircle } from "./components/PetCircle";
import { DashboardPage } from "./pages/DashboardPage";
import { useAgentStore } from "./stores/agentStore";

export default function App() {
  const view = new URLSearchParams(window.location.search).get("view") || "pet";
  const initialize = useAgentStore((state) => state.initialize);
  const reconnect = useAgentStore((state) => state.reconnect);
  const addLog = useAgentStore((state) => state.addLog);
  const [expanded, setExpanded] = useState(view === "dashboard");

  useEffect(() => {
    document.title = view === "dashboard" ? "桌面智能体控制台" : "桌面智能体";
    void initialize();
    const removeLog = window.desktopAgent.onBackendLog(addLog);
    const removeExpanded = window.desktopAgent.onExpandedChange(setExpanded);
    const removeRestarted = window.desktopAgent.onBackendRestarted(() => void reconnect());
    if (view === "pet") void window.desktopAgent.isExpanded().then(setExpanded);
    return () => {
      removeLog();
      removeExpanded();
      removeRestarted();
    };
  }, [addLog, initialize, reconnect, view]);

  if (view === "dashboard") return <DashboardPage />;
  return expanded ? <ChatPanel /> : <PetCircle />;
}

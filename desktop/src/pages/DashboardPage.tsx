import { useEffect, useState } from "react";
import {
  Bot,
  BrainCircuit,
  FileClock,
  History,
  Info,
  KeyRound,
  ListTree,
  LockKeyhole,
  MessageSquare,
  MonitorCog,
  RefreshCw,
  Save,
  ScrollText,
  Trash2
} from "lucide-react";
import { apiRequest, desktopSettings } from "../services/api";
import { useAgentStore } from "../stores/agentStore";
import type { DesktopSettings } from "../types";
import { ChatPanel } from "../components/ChatPanel";

type Section = "chat" | "history" | "api" | "models" | "skills" | "browser" | "permissions" | "logs" | "about";

const navigation: Array<{ id: Section; label: string; icon: typeof Bot }> = [
  { id: "chat", label: "聊天", icon: MessageSquare },
  { id: "history", label: "历史任务", icon: History },
  { id: "api", label: "API 配置", icon: KeyRound },
  { id: "models", label: "模型配置", icon: BrainCircuit },
  { id: "skills", label: "技能管理", icon: ListTree },
  { id: "browser", label: "浏览器设置", icon: MonitorCog },
  { id: "permissions", label: "权限设置", icon: LockKeyhole },
  { id: "logs", label: "运行日志", icon: ScrollText },
  { id: "about", label: "关于产品", icon: Info }
];

interface SkillInfo {
  id: string;
  name: string;
  type: string;
  description: string;
  version: string;
}

export function DashboardPage() {
  const [section, setSection] = useState<Section>("chat");
  const state = useAgentStore();

  return (
    <main className="dashboard-shell">
      <aside className="dashboard-nav">
        <div className="dashboard-brand"><Bot size={22} /><strong>桌面智能体</strong></div>
        <nav>
          {navigation.map((item) => {
            const Icon = item.icon;
            return (
              <button className={section === item.id ? "active" : ""} key={item.id} onClick={() => setSection(item.id)}>
                <Icon size={17} />{item.label}
              </button>
            );
          })}
        </nav>
        <div className={`backend-status ${state.backendConnected ? "online" : "offline"}`}>
          <span />{state.backendConnected ? "Agent 已连接" : "正在重连"}
        </div>
      </aside>
      <section className="dashboard-content">
        {section === "chat" ? <ChatPanel dashboard /> : null}
        {section === "history" ? <HistoryView /> : null}
        {section === "api" || section === "models" || section === "browser" ? <SettingsView initialSection={section} /> : null}
        {section === "skills" ? <SkillsView /> : null}
        {section === "permissions" ? <PermissionsView /> : null}
        {section === "logs" ? <LogsView /> : null}
        {section === "about" ? <AboutView /> : null}
      </section>
    </main>
  );
}

function PageHeading({ title, description }: { title: string; description: string }) {
  return <header className="page-heading"><h1>{title}</h1><p>{description}</p></header>;
}

function HistoryView() {
  const store = useAgentStore();
  const [tasks, setTasks] = useState<Array<Record<string, string>>>([]);
  useEffect(() => { void apiRequest<Array<Record<string, string>>>("/api/tasks").then(setTasks); }, []);
  return (
    <div className="page-view">
      <PageHeading title="历史任务" description="查看会话和任务执行结果。" />
      <div className="history-toolbar">
        <button className="button-primary" onClick={() => void store.createConversation()}>新建会话</button>
        <button className="button-secondary danger-text" onClick={() => {
          if (window.confirm("清空全部历史记录？")) void store.clearHistory();
        }}><Trash2 size={15} />清空历史</button>
      </div>
      <div className="task-table" role="table">
        <div className="task-table-head" role="row"><span>任务</span><span>状态</span><span>开始时间</span><span>结束时间</span></div>
        {tasks.map((task) => (
          <div className="task-table-row" role="row" key={task.id}>
            <span>{task.id}</span><span className={`status-text status-${task.status}`}>{task.status}</span>
            <span>{formatDate(task.started_at || task.created_at)}</span><span>{formatDate(task.finished_at)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function SettingsView({ initialSection }: { initialSection: "api" | "models" | "browser" }) {
  const reconnect = useAgentStore((state) => state.reconnect);
  const [settings, setSettings] = useState<DesktopSettings>({
    provider: "openai", baseUrl: "", model: "", temperature: 0.2, requestTimeout: 60, browserHeadless: false
  });
  const [saved, setSaved] = useState(false);
  useEffect(() => { void desktopSettings.get().then(setSettings); }, []);

  async function save() {
    const result = await desktopSettings.save(settings);
    setSettings((current) => ({ ...current, apiKey: "", apiKeyMasked: result.apiKeyMasked }));
    setSaved(true);
    window.setTimeout(() => setSaved(false), 2500);
    await reconnect();
  }

  const title = initialSection === "api" ? "API 配置" : initialSection === "models" ? "模型配置" : "浏览器设置";
  return (
    <div className="page-view settings-view">
      <PageHeading title={title} description="配置保存在系统加密存储中，保存后 Agent 会自动重启。" />
      {initialSection === "api" ? (
        <div className="settings-form">
          <label>API Provider<select value={settings.provider} onChange={(event) => setSettings({ ...settings, provider: event.target.value })}><option value="openai">OpenAI 兼容</option><option value="anthropic">Anthropic</option></select></label>
          <label>API Key<input type="password" value={settings.apiKey || ""} placeholder={settings.apiKeyMasked || "输入 API Key"} onChange={(event) => setSettings({ ...settings, apiKey: event.target.value })} /></label>
          <label>Base URL<input value={settings.baseUrl} onChange={(event) => setSettings({ ...settings, baseUrl: event.target.value })} /></label>
        </div>
      ) : null}
      {initialSection === "models" ? (
        <div className="settings-form">
          <label>Model<input value={settings.model} onChange={(event) => setSettings({ ...settings, model: event.target.value })} /></label>
          <label>Temperature<div className="range-row"><input type="range" min="0" max="2" step="0.1" value={settings.temperature} onChange={(event) => setSettings({ ...settings, temperature: Number(event.target.value) })} /><output>{settings.temperature.toFixed(1)}</output></div></label>
          <label>Request Timeout（秒）<input type="number" min="5" max="600" value={settings.requestTimeout} onChange={(event) => setSettings({ ...settings, requestTimeout: Number(event.target.value) })} /></label>
        </div>
      ) : null}
      {initialSection === "browser" ? (
        <div className="settings-form">
          <label className="toggle-row"><span><strong>无头模式</strong><small>后台运行浏览器，不显示窗口</small></span><input type="checkbox" checked={settings.browserHeadless} onChange={(event) => setSettings({ ...settings, browserHeadless: event.target.checked })} /></label>
          <button className="button-secondary" onClick={() => void apiRequest("/api/browser/close", { method: "POST" })}>关闭当前浏览器</button>
        </div>
      ) : null}
      <button className="button-primary save-settings" onClick={() => void save()}><Save size={16} />{saved ? "已保存" : "保存设置"}</button>
    </div>
  );
}

function SkillsView() {
  const [skills, setSkills] = useState<SkillInfo[]>([]);
  useEffect(() => { void apiRequest<SkillInfo[]>("/api/skills").then(setSkills); }, []);
  return (
    <div className="page-view">
      <PageHeading title="技能管理" description={`当前已载入 ${skills.length} 个技能。`} />
      <div className="skill-list">
        {skills.map((skill) => <div className="skill-row" key={skill.id}><div><strong>{skill.name}</strong><span>{skill.description || skill.id}</span></div><code>{skill.version}</code></div>)}
      </div>
    </div>
  );
}

function PermissionsView() {
  const [confirmSensitive, setConfirmSensitive] = useState(true);
  const [allowDownloads, setAllowDownloads] = useState(false);
  return (
    <div className="page-view">
      <PageHeading title="权限设置" description="控制自动化任务可以执行的操作。" />
      <div className="settings-form">
        <label className="toggle-row"><span><strong>敏感操作需要确认</strong><small>提交、发布和删除操作会显示确认卡片</small></span><input type="checkbox" checked={confirmSensitive} onChange={(event) => setConfirmSensitive(event.target.checked)} /></label>
        <label className="toggle-row"><span><strong>允许自动下载</strong><small>允许任务把网页文件保存到本机</small></span><input type="checkbox" checked={allowDownloads} onChange={(event) => setAllowDownloads(event.target.checked)} /></label>
      </div>
    </div>
  );
}

function LogsView() {
  const logs = useAgentStore((state) => state.logs);
  return (
    <div className="page-view logs-view">
      <PageHeading title="运行日志" description="显示桌面后端的实时输出。" />
      <pre>{logs.length ? logs.join("\n") : "暂无日志"}</pre>
    </div>
  );
}

function AboutView() {
  return (
    <div className="page-view about-view">
      <PageHeading title="关于产品" description="Agentic Playwright MCP 桌面智能体" />
      <dl><dt>桌面端版本</dt><dd>0.1.0</dd><dt>后端</dt><dd>Python · FastAPI · Playwright</dd><dt>数据存储</dt><dd>本机 SQLite</dd><dt>浏览器界面</dt><dd>仅显示目标网页，不注入 Agent UI</dd></dl>
    </div>
  );
}

function formatDate(value?: string) {
  if (!value) return "-";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN");
}

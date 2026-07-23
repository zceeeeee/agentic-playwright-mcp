import { useEffect, useReducer, useState } from "react";
import {
  ArrowRight,
  BarChart3,
  Bot,
  Eye,
  EyeOff,
  GitFork,
  History,
  Info,
  KeyRound,
  ListTree,
  LoaderCircle,
  LockKeyhole,
  MessageSquare,
  MonitorCog,
  Palette,
  PlugZap,
  Save,
  Search,
  ScrollText,
  Trash2
} from "lucide-react";
import { apiRequest, desktopSettings } from "../services/api";
import { useAgentStore } from "../stores/agentStore";
import type { DesktopSettings } from "../types";
import { ChatPanel } from "../components/ChatPanel";
import { AppearanceSettings } from "../components/AppearanceSettings";
import { ConsoleView } from "../components/ConsoleView";
import type { DashboardSection } from "../types";
import { filterAndGroupSkills, type SkillInfo } from "../utils/skillCatalog";
import { BRAND } from "../branding";
import {
  apiConnectionTestReducer,
  initialApiConnectionTestState
} from "../utils/apiConnectionTestState";

const navigation: Array<{ id: DashboardSection; label: string; icon: typeof Bot }> = [
  { id: "chat", label: "聊天", icon: MessageSquare },
  { id: "history", label: "历史任务", icon: History },
  { id: "console", label: "控制台", icon: BarChart3 },
  { id: "appearance", label: "外观与皮肤", icon: Palette },
  { id: "api", label: "API 与模型", icon: KeyRound },
  { id: "skills", label: "技能管理", icon: ListTree },
  { id: "browser", label: "浏览器设置", icon: MonitorCog },
  { id: "permissions", label: "权限设置", icon: LockKeyhole },
  { id: "logs", label: "运行日志", icon: ScrollText },
  { id: "about", label: "关于产品", icon: Info }
];

export function DashboardPage() {
  const requestedSection = new URLSearchParams(window.location.search).get("section");
  const normalizedRequestedSection = requestedSection === "models" ? "api" : requestedSection;
  const initialSection = navigation.some((item) => item.id === normalizedRequestedSection)
    ? normalizedRequestedSection as DashboardSection
    : "chat";
  const [section, setSection] = useState<DashboardSection>(initialSection);
  const state = useAgentStore();

  useEffect(() => window.desktopAgent.onDashboardNavigate((nextSection) => {
    setSection(nextSection === "models" ? "api" : nextSection);
  }), []);

  return (
    <main className="dashboard-shell">
      <aside className="dashboard-nav">
        <div className="dashboard-brand"><img src={BRAND.logoPath} alt="" /><strong>{BRAND.name}</strong></div>
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
        {section === "history" ? <HistoryView onOpenConversation={() => setSection("chat")} /> : null}
        {section === "console" ? <ConsoleView /> : null}
        {section === "appearance" ? <AppearanceSettings /> : null}
        {section === "api" || section === "browser" ? <SettingsView initialSection={section} /> : null}
        {section === "skills" ? <SkillsView onImportCommand={(command) => {
          state.setChatDraft(command);
          setSection("chat");
        }} /> : null}
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

function HistoryView({ onOpenConversation }: { onOpenConversation: () => void }) {
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
          <button
            className={`task-table-row ${task.conversation_id === store.currentConversationId ? "active" : ""}`}
            role="row"
            aria-label={`打开任务 ${task.id}`}
            key={task.id}
            onClick={() => void store.openConversation(task.conversation_id).then((opened) => {
              if (opened) onOpenConversation();
            })}
          >
            <span>{task.id}</span><span className={`status-text status-${task.status}`}>{task.status}</span>
            <span>{formatDate(task.started_at || task.created_at)}</span><span>{formatDate(task.finished_at)}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

function SettingsView({ initialSection }: { initialSection: "api" | "browser" }) {
  const reconnect = useAgentStore((state) => state.reconnect);
  const [settings, setSettings] = useState<DesktopSettings>({
    provider: "openai",
    baseUrl: "",
    model: "",
    temperature: 0.2,
    requestTimeout: 60,
    browserHeadless: false,
    maxSteps: 20,
    useCloakBrowser: true,
    exploreOcrEnabled: true,
    exploreVisionEnabled: false
  });
  const [saved, setSaved] = useState(false);
  const [showApiKey, setShowApiKey] = useState(false);
  const [connectionTest, dispatchConnectionTest] = useReducer(
    apiConnectionTestReducer,
    initialApiConnectionTestState
  );
  useEffect(() => { void desktopSettings.get().then(setSettings); }, []);

  function updateTestedSetting(patch: Partial<DesktopSettings>) {
    dispatchConnectionTest({ type: "edit" });
    setSettings((current) => ({ ...current, ...patch }));
  }

  async function save() {
    const result = await desktopSettings.save(settings);
    setSettings((current) => ({ ...current, apiKey: "", apiKeyMasked: result.apiKeyMasked }));
    setSaved(true);
    window.setTimeout(() => setSaved(false), 2500);
    await reconnect();
  }

  async function testConnection() {
    if (!settings.apiKey?.trim()) {
      dispatchConnectionTest({
        type: "fail",
        message: "请输入当前 API Key 后再测试",
        elapsedMs: 0
      });
      return;
    }
    if (!settings.baseUrl.trim()) {
      dispatchConnectionTest({
        type: "fail",
        message: "请输入 Base URL 后再测试",
        elapsedMs: 0
      });
      return;
    }
    if (!settings.model.trim()) {
      dispatchConnectionTest({
        type: "fail",
        message: "请输入 Model 后再测试",
        elapsedMs: 0
      });
      return;
    }

    dispatchConnectionTest({ type: "start" });
    try {
      const result = await desktopSettings.test(settings);
      dispatchConnectionTest({
        type: result.ok ? "succeed" : "fail",
        message: result.message,
        elapsedMs: result.elapsedMs
      });
    } catch {
      dispatchConnectionTest({
        type: "fail",
        message: "连通测试失败，请重试",
        elapsedMs: 0
      });
    }
  }

  const title = initialSection === "api" ? "API 与模型配置" : "浏览器设置";
  const testingConnection = connectionTest.status === "testing";
  return (
    <div className="page-view settings-view">
      <PageHeading title={title} description="配置保存在系统加密存储中，保存后 Agent 会自动重启。" />
      {initialSection === "api" ? (
        <div className="settings-form">
          <section className="settings-section">
            <h2>服务连接</h2>
            <label>API Provider<select disabled={testingConnection} value={settings.provider} onChange={(event) => updateTestedSetting({ provider: event.target.value })}><option value="openai">OpenAI 兼容</option><option value="anthropic">Anthropic</option></select></label>
            <label>API Key<span className="password-input-row"><input disabled={testingConnection} type={showApiKey ? "text" : "password"} value={settings.apiKey || ""} placeholder={settings.apiKeyMasked || "输入 API Key"} onChange={(event) => updateTestedSetting({ apiKey: event.target.value })} /><button type="button" title={showApiKey ? "隐藏 API Key" : "显示 API Key"} aria-label={showApiKey ? "隐藏 API Key" : "显示 API Key"} onClick={() => setShowApiKey((visible) => !visible)}>{showApiKey ? <EyeOff size={17} /> : <Eye size={17} />}</button></span></label>
            <label>Base URL<input disabled={testingConnection} value={settings.baseUrl} onChange={(event) => updateTestedSetting({ baseUrl: event.target.value })} /></label>
          </section>
          <section className="settings-section">
            <h2>模型参数</h2>
            <label>Model<input disabled={testingConnection} value={settings.model} onChange={(event) => updateTestedSetting({ model: event.target.value })} /></label>
            <label>Temperature<div className="range-row"><input type="range" min="0" max="2" step="0.1" value={settings.temperature} onChange={(event) => setSettings({ ...settings, temperature: Number(event.target.value) })} /><output>{settings.temperature.toFixed(1)}</output></div></label>
            <label>Request Timeout（秒）<input disabled={testingConnection} type="number" min="5" max="600" value={settings.requestTimeout} onChange={(event) => updateTestedSetting({ requestTimeout: Number(event.target.value) })} /></label>
          </section>
          <section className="settings-section">
            <h2>Explore 功能</h2>
            <label className="toggle-row"><span><strong>视觉模型</strong><small>当 ARIA 和 OCR 都无法定位时，调用视觉模型分析截图。需要配置视觉模型 API Key。</small></span><input type="checkbox" checked={settings.exploreVisionEnabled} onChange={(event) => setSettings({ ...settings, exploreVisionEnabled: event.target.checked })} /></label>
            <label className="toggle-row"><span><strong>文字识别 (OCR)</strong><small>在 ARIA 快照信息不足时，使用 Windows OCR 识别页面文字作为兜底定位方案。仅 Windows 生效。</small></span><input type="checkbox" checked={settings.exploreOcrEnabled} onChange={(event) => setSettings({ ...settings, exploreOcrEnabled: event.target.checked })} /></label>
          </section>
        </div>
      ) : null}
      {initialSection === "browser" ? (
        <div className="settings-form">
          <label className="toggle-row"><span><strong>无头模式</strong><small>后台运行浏览器，不显示窗口</small></span><input type="checkbox" checked={settings.browserHeadless} onChange={(event) => setSettings({ ...settings, browserHeadless: event.target.checked })} /></label>
          <label className="toggle-row"><span><strong>启用 CloakBrowser</strong><small>使用带反检测能力的浏览器引擎；关闭后使用 Chromium。</small></span><input type="checkbox" checked={settings.useCloakBrowser} onChange={(event) => setSettings({ ...settings, useCloakBrowser: event.target.checked })} /></label>
          <label>最大循环步数<input type="number" min="5" max="100" step="1" value={settings.maxSteps} onChange={(event) => setSettings({ ...settings, maxSteps: Number(event.target.value) })} /><small className="field-help">单个任务最多执行 5–100 步，默认 20 步。</small></label>
          <label>日志级别<select value={settings.logLevel} onChange={(event) => setSettings({ ...settings, logLevel: event.target.value as DesktopSettings["logLevel"] })}><option value="DEBUG">DEBUG（详细调试）</option><option value="INFO">INFO（常规信息）</option><option value="WARNING">WARNING（仅警告）</option><option value="ERROR">ERROR（仅错误）</option></select><small className="field-help">DEBUG 可查看 LLM 请求/响应等详细信息，保存后需重启生效。</small></label>
          <button className="button-secondary" onClick={() => void apiRequest("/api/browser/close", { method: "POST" })}>关闭当前浏览器</button>
        </div>
      ) : null}
      <div className="settings-actions">
        {initialSection === "api" ? (
          <button className="button-secondary" disabled={testingConnection} onClick={() => void testConnection()}>
            {testingConnection ? <LoaderCircle className="spin" size={16} /> : <PlugZap size={16} />}
            {testingConnection ? "测试中" : "测试连通性"}
          </button>
        ) : null}
        <button className="button-primary save-settings" onClick={() => void save()}><Save size={16} />{saved ? "已保存" : "保存设置"}</button>
      </div>
      {initialSection === "api" && connectionTest.status !== "idle" ? (
        <p
          className={`connection-test-status ${connectionTest.status}`}
          role={connectionTest.status === "error" ? "alert" : "status"}
          aria-live="polite"
        >
          {connectionTest.message}
          {connectionTest.status === "success" ? `（${connectionTest.elapsedMs} ms）` : ""}
        </p>
      ) : null}
    </div>
  );
}

function SkillsView({ onImportCommand }: { onImportCommand: (command: string) => void }) {
  const [skills, setSkills] = useState<SkillInfo[]>([]);
  const [query, setQuery] = useState("");
  useEffect(() => { void apiRequest<SkillInfo[]>("/api/skills").then(setSkills); }, []);
  const groups = filterAndGroupSkills(skills, query);
  const visibleCount = groups.reduce((total, group) => total + group.skills.length, 0);
  return (
    <div className="page-view skills-view">
      <PageHeading title="技能管理" description={`按网站归类，技能数量较多的网站排在前面。当前显示 ${visibleCount}/${skills.length} 个技能。`} />
      <label className="skill-search"><Search size={17} /><input type="search" value={query} placeholder="搜索网站、技能或命令格式" onChange={(event) => setQuery(event.target.value)} /></label>
      <div className="skill-site-list">
        {groups.map((group) => (
          <section className="skill-site-group" key={group.id}>
            <header><h2>{group.label}</h2><span>{group.skills.length} 个技能</span></header>
            <div className="skill-list">
              {group.skills.map((skill) => (
                <button className="skill-row" key={skill.id} onClick={() => onImportCommand(skill.command_template)}>
                  <span className="skill-row-copy"><strong>{skill.name}</strong><span>{skill.description || skill.id}</span><code>{skill.command_template}</code></span>
                  <span className="skill-import-action">导入聊天<ArrowRight size={15} /></span>
                </button>
              ))}
            </div>
          </section>
        ))}
        {!groups.length ? <p className="empty-skill-search">没有匹配的技能。</p> : null}
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
      <section className="about-identity">
        <img src={BRAND.logoPath} alt={`${BRAND.name} Logo`} />
        <div><h1>{BRAND.name}</h1><p>{BRAND.tagline}</p></div>
      </section>
      <p className="about-description">{BRAND.description} FeatherDesk 把技能路由、Playwright 自动化、视觉探索和桌面宠物交互整合在同一套本地工作流中。</p>
      <dl><dt>桌面端版本</dt><dd>{BRAND.version}</dd><dt>后端</dt><dd>Python · FastAPI · Playwright</dd><dt>数据存储</dt><dd>本机 SQLite</dd><dt>浏览器界面</dt><dd>仅显示目标网页，不注入 Agent UI</dd><dt>GitHub 仓库</dt><dd><button className="external-link" onClick={() => void window.desktopAgent.openExternal(BRAND.repositoryUrl)}><GitFork size={16} />feitianduowen/agentic-playwright-mcp</button></dd></dl>
    </div>
  );
}

function formatDate(value?: string) {
  if (!value) return "-";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN");
}

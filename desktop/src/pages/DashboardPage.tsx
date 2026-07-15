import { useEffect, useState } from "react";
import {
  ArrowRight,
  Bot,
  Database,
  Eye,
  EyeOff,
  GitFork,
  History,
  Info,
  KeyRound,
  ListTree,
  LockKeyhole,
  MessageSquare,
  MonitorCog,
  Palette,
  Save,
  Search,
  ScrollText,
  Trash2
} from "lucide-react";
import { apiRequest, desktopSettings } from "../services/api";
import { useAgentStore } from "../stores/agentStore";
import type { DesktopSettings, WxCliStatus } from "../types";
import { ChatPanel } from "../components/ChatPanel";
import { AppearanceSettings } from "../components/AppearanceSettings";
import type { DashboardSection } from "../types";
import { filterAndGroupSkills, type SkillInfo } from "../utils/skillCatalog";

const navigation: Array<{ id: DashboardSection; label: string; icon: typeof Bot }> = [
  { id: "chat", label: "聊天", icon: MessageSquare },
  { id: "history", label: "历史任务", icon: History },
  { id: "appearance", label: "外观与皮肤", icon: Palette },
  { id: "api", label: "API 与模型", icon: KeyRound },
  { id: "skills", label: "技能管理", icon: ListTree },
  { id: "browser", label: "浏览器设置", icon: MonitorCog },
  { id: "wechat", label: "微信数据读取", icon: Database },
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
        {section === "history" ? <HistoryView onOpenConversation={() => setSection("chat")} /> : null}
        {section === "appearance" ? <AppearanceSettings /> : null}
        {section === "api" || section === "browser" ? <SettingsView initialSection={section} /> : null}
        {section === "wechat" ? <WechatDataSettings /> : null}
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
    useCloakBrowser: true
  });
  const [saved, setSaved] = useState(false);
  const [showApiKey, setShowApiKey] = useState(false);
  useEffect(() => { void desktopSettings.get().then(setSettings); }, []);

  async function save() {
    const result = await desktopSettings.save(settings);
    setSettings((current) => ({ ...current, apiKey: "", apiKeyMasked: result.apiKeyMasked }));
    setSaved(true);
    window.setTimeout(() => setSaved(false), 2500);
    await reconnect();
  }

  const title = initialSection === "api" ? "API 与模型配置" : "浏览器设置";
  return (
    <div className="page-view settings-view">
      <PageHeading title={title} description="配置保存在系统加密存储中，保存后 Agent 会自动重启。" />
      {initialSection === "api" ? (
        <div className="settings-form">
          <section className="settings-section">
            <h2>服务连接</h2>
            <label>API Provider<select value={settings.provider} onChange={(event) => setSettings({ ...settings, provider: event.target.value })}><option value="openai">OpenAI 兼容</option><option value="anthropic">Anthropic</option></select></label>
            <label>API Key<span className="password-input-row"><input type={showApiKey ? "text" : "password"} value={settings.apiKey || ""} placeholder={settings.apiKeyMasked || "输入 API Key"} onChange={(event) => setSettings({ ...settings, apiKey: event.target.value })} /><button type="button" title={showApiKey ? "隐藏 API Key" : "显示 API Key"} aria-label={showApiKey ? "隐藏 API Key" : "显示 API Key"} onClick={() => setShowApiKey((visible) => !visible)}>{showApiKey ? <EyeOff size={17} /> : <Eye size={17} />}</button></span></label>
            <label>Base URL<input value={settings.baseUrl} onChange={(event) => setSettings({ ...settings, baseUrl: event.target.value })} /></label>
          </section>
          <section className="settings-section">
            <h2>模型参数</h2>
            <label>Model<input value={settings.model} onChange={(event) => setSettings({ ...settings, model: event.target.value })} /></label>
            <label>Temperature<div className="range-row"><input type="range" min="0" max="2" step="0.1" value={settings.temperature} onChange={(event) => setSettings({ ...settings, temperature: Number(event.target.value) })} /><output>{settings.temperature.toFixed(1)}</output></div></label>
            <label>Request Timeout（秒）<input type="number" min="5" max="600" value={settings.requestTimeout} onChange={(event) => setSettings({ ...settings, requestTimeout: Number(event.target.value) })} /></label>
          </section>
        </div>
      ) : null}
      {initialSection === "browser" ? (
        <div className="settings-form">
          <label className="toggle-row"><span><strong>无头模式</strong><small>后台运行浏览器，不显示窗口</small></span><input type="checkbox" checked={settings.browserHeadless} onChange={(event) => setSettings({ ...settings, browserHeadless: event.target.checked })} /></label>
          <label className="toggle-row"><span><strong>启用 CloakBrowser</strong><small>使用带反检测能力的浏览器引擎；关闭后使用 Chromium。</small></span><input type="checkbox" checked={settings.useCloakBrowser} onChange={(event) => setSettings({ ...settings, useCloakBrowser: event.target.checked })} /></label>
          <label>最大循环步数<input type="number" min="5" max="100" step="1" value={settings.maxSteps} onChange={(event) => setSettings({ ...settings, maxSteps: Number(event.target.value) })} /><small className="field-help">单个任务最多执行 5–100 步，默认 20 步。</small></label>
          <button className="button-secondary" onClick={() => void apiRequest("/api/browser/close", { method: "POST" })}>关闭当前浏览器</button>
        </div>
      ) : null}
      <button className="button-primary save-settings" onClick={() => void save()}><Save size={16} />{saved ? "已保存" : "保存设置"}</button>
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

function WechatDataSettings() {
  const initializeWxCli = useAgentStore((state) => state.initializeWxCli);
  const [status, setStatus] = useState<WxCliStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [setupMode, setSetupMode] = useState<"init" | "force" | null>(null);
  const [setupError, setSetupError] = useState("");
  const [copied, setCopied] = useState("");

  async function refresh() {
    setLoading(true);
    try {
      setStatus(await apiRequest<WxCliStatus>("/api/wx-cli/status"));
    } finally {
      setLoading(false);
    }
  }

  async function copy(label: string, command: string) {
    await navigator.clipboard.writeText(command);
    setCopied(label);
    window.setTimeout(() => setCopied(""), 1600);
  }

  async function initialize(force: boolean) {
    setSetupMode(force ? "force" : "init");
    setSetupError("");
    try {
      setStatus(await initializeWxCli(force));
    } catch (error) {
      setSetupError(error instanceof Error ? error.message : "wx-cli 初始化失败");
      await refresh();
    } finally {
      setSetupMode(null);
    }
  }

  useEffect(() => { void refresh(); }, []);
  return (
    <div className="page-view settings-view">
      <PageHeading title="微信数据读取" description="历史记录任务只检查 wx-cli 状态，不会自动初始化。初始化仅在您点击按钮后执行；聊天原文只在内存中临时显示。" />
      <div className="settings-form">
        <section className="settings-section">
          <h2>wx-cli 状态</h2>
          <dl className="wx-status-list">
            <dt>安装</dt><dd>{status?.installed ? "已安装" : "未安装"}</dd>
            <dt>版本</dt><dd>{status?.version || "-"}</dd>
            <dt>初始化</dt><dd>{status?.initialized ? "正常" : "未初始化"}</dd>
            <dt>Daemon</dt><dd>{status?.daemon_available ? "运行中" : "未运行"}</dd>
            <dt>失败阶段</dt><dd>{status?.failure_stage || "-"}</dd>
            <dt>错误代码</dt><dd>{status?.error_code || "-"}</dd>
          </dl>
          <p>{status?.message || "正在检测 wx-cli…"}</p>
          <div className="settings-actions">
            <button className="button-primary" disabled={loading} onClick={() => void refresh()}>{loading ? "检测中" : "重新检测"}</button>
            <button className="button-secondary" disabled={setupMode !== null} onClick={() => void initialize(false)}>{setupMode === "init" ? "初始化中" : "以管理员权限初始化"}</button>
            <button className="button-secondary" disabled={setupMode !== null} onClick={() => void initialize(true)}>{setupMode === "force" ? "重新初始化中" : "强制重新初始化"}</button>
            <button className="button-secondary" onClick={() => void copy("install", "npm.cmd install --prefix tools/wx-cli")}>{copied === "install" ? "已复制" : "复制安装命令"}</button>
            <button className="button-secondary" onClick={() => void copy("init", "tools\\wx-cli\\node_modules\\.bin\\wx.cmd init")}>{copied === "init" ? "已复制" : "复制手动初始化命令"}</button>
            <button className="button-secondary" onClick={() => void copy("force", "tools\\wx-cli\\node_modules\\.bin\\wx.cmd init --force")}>{copied === "force" ? "已复制" : "复制强制初始化命令"}</button>
          </div>
          {status?.diagnostic ? <details className="wx-setup-diagnostic"><summary>查看诊断详情</summary><pre>{status.diagnostic}</pre></details> : null}
          {setupError ? <p className="wx-setup-error">{setupError}</p> : null}
        </section>
        <section className="settings-section">
          <h2>隐私策略</h2>
          <label className="toggle-row"><span><strong>每次读取前确认</strong><small>固定启用，读取前必须确认具体会话和范围。</small></span><input type="checkbox" checked readOnly /></label>
          <label className="toggle-row"><span><strong>保存微信原文到智能体历史</strong><small>固定关闭。原文不会写入 SQLite。</small></span><input type="checkbox" checked={false} readOnly /></label>
          <label className="toggle-row"><span><strong>AI 分析前再次确认</strong><small>固定启用，只有明确授权后原文才会发送给当前 AI 服务。</small></span><input type="checkbox" checked readOnly /></label>
        </section>
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
  const repositoryUrl = "https://github.com/feitianduowen/agentic-playwright-mcp";
  return (
    <div className="page-view about-view">
      <PageHeading title="关于产品" description="Agentic Playwright MCP 是一个面向浏览器与桌面应用的自然语言自动化智能体。" />
      <p className="about-description">项目把技能路由、Playwright 自动化、视觉探索和桌面宠物交互整合在同一套工作流中，并将会话、任务与外观设置保存在本机。</p>
      <dl><dt>桌面端版本</dt><dd>0.1.0</dd><dt>后端</dt><dd>Python · FastAPI · Playwright</dd><dt>数据存储</dt><dd>本机 SQLite</dd><dt>浏览器界面</dt><dd>仅显示目标网页，不注入 Agent UI</dd><dt>GitHub 仓库</dt><dd><button className="external-link" onClick={() => void window.desktopAgent.openExternal(repositoryUrl)}><GitFork size={16} />feitianduowen/agentic-playwright-mcp</button></dd></dl>
    </div>
  );
}

function formatDate(value?: string) {
  if (!value) return "-";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN");
}

import { useState } from "react";
import { Copy, RefreshCw, ShieldAlert, X } from "lucide-react";
import { useAgentStore } from "../stores/agentStore";

const stageLabels: Record<string, string> = {
  resolve: "运行时定位",
  version: "版本检查",
  init: "初始化",
  elevated_init: "管理员初始化",
  daemon: "后台服务检测",
  sessions: "会话检测",
  json_parse: "结果解析"
};

export function WxCliSetupCard() {
  const request = useAgentStore((state) => state.wxCliSetupRequest);
  const recheck = useAgentStore((state) => state.recheckWxCli);
  const initialize = useAgentStore((state) => state.initializeWxCli);
  const dismiss = useAgentStore((state) => state.dismissWxCliSetup);
  const [busy, setBusy] = useState<"check" | "init" | "force" | null>(null);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState("");

  if (!request) return null;

  async function run(action: "check" | "init" | "force") {
    setBusy(action);
    setError("");
    try {
      if (action === "check") await recheck();
      else await initialize(action === "force");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "wx-cli 操作失败");
    } finally {
      setBusy(null);
    }
  }

  async function copy(label: string, command: string) {
    await navigator.clipboard.writeText(command);
    setCopied(label);
    window.setTimeout(() => setCopied(""), 1600);
  }

  return (
    <section className="wx-setup-card" aria-label="wx-cli 设置要求">
      <header>
        <ShieldAlert size={20} aria-hidden="true" />
        <div>
          <strong>{request.title || "wx-cli 尚未准备好"}</strong>
          <span>微信历史记录读取需要先完成一次本地初始化。</span>
        </div>
        <button className="icon-button" title="关闭" aria-label="关闭" onClick={dismiss}>
          <X size={17} />
        </button>
      </header>

      <dl className="wx-setup-status">
        <dt>失败阶段</dt>
        <dd>{stageLabels[request.failure_stage || ""] || request.failure_stage || "未知"}</dd>
        <dt>错误代码</dt>
        <dd>{request.error_code || "WX_CLI_SETUP_REQUIRED"}</dd>
        <dt>原因</dt>
        <dd>{request.message}</dd>
      </dl>

      <p>请保持微信桌面客户端已启动并登录。初始化按钮会触发 Windows 管理员权限提示。</p>

      <div className="wx-setup-actions">
        <button className="button-primary" disabled={busy !== null} onClick={() => void run("init")}>
          {busy === "init" ? "初始化中" : "以管理员权限初始化"}
        </button>
        <button className="button-secondary" disabled={busy !== null} onClick={() => void run("force")}>
          {busy === "force" ? "重新初始化中" : "强制重新初始化"}
        </button>
        <button className="button-secondary" disabled={busy !== null} onClick={() => void run("check")}>
          <RefreshCw size={15} />{busy === "check" ? "检测中" : "重新检测"}
        </button>
      </div>

      <div className="wx-setup-copy-actions">
        <button onClick={() => void copy("init", request.commands.initialize)}>
          <Copy size={14} />{copied === "init" ? "已复制" : "复制初始化命令"}
        </button>
        <button onClick={() => void copy("verify", request.commands.verify)}>
          <Copy size={14} />{copied === "verify" ? "已复制" : "复制验证命令"}
        </button>
      </div>

      {request.diagnostic ? (
        <details className="wx-setup-diagnostic">
          <summary>查看诊断详情</summary>
          <pre>{request.diagnostic}</pre>
        </details>
      ) : null}
      {error ? <p className="wx-setup-error">{error}</p> : null}
    </section>
  );
}

import { useEffect, useState } from "react";
import { Activity, Clock, Cpu, Eye, RefreshCw, Zap } from "lucide-react";
import { apiRequest } from "../services/api";

interface StatsSummary {
  task_count: number;
  total_duration_ms: number;
  total_text_prompt: number;
  total_text_completion: number;
  total_text_tokens: number;
  total_text_reasoning: number;
  total_text_cache_read: number;
  total_vision_tokens: number;
  total_all_tokens: number;
  total_steps: number;
  avg_tokens_per_task: number;
}

interface TaskStatRow {
  task_id: string;
  conversation_id: string;
  duration_ms: number;
  text_prompt_tokens: number;
  text_completion_tokens: number;
  text_total_tokens: number;
  text_reasoning_tokens: number;
  text_cache_read_tokens: number;
  vision_total_tokens: number;
  step_count: number;
  created_at: string;
  status?: string;
}

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return n.toLocaleString();
}

function formatDuration(ms: number): string {
  if (ms >= 3_600_000) return `${(ms / 3_600_000).toFixed(1)}h`;
  if (ms >= 60_000) return `${(ms / 60_000).toFixed(1)}min`;
  if (ms >= 1_000) return `${(ms / 1_000).toFixed(1)}s`;
  return `${Math.round(ms)}ms`;
}

function formatTime(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleString("zh-CN", {
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

function StatCard({
  icon: Icon,
  label,
  value,
  sub,
}: {
  icon: typeof Activity;
  label: string;
  value: string;
  sub?: string;
}) {
  return (
    <div className="console-stat-card">
      <div className="console-stat-icon"><Icon size={20} /></div>
      <div className="console-stat-body">
        <span className="console-stat-value">{value}</span>
        <span className="console-stat-label">{label}</span>
        {sub ? <span className="console-stat-sub">{sub}</span> : null}
      </div>
    </div>
  );
}

export function ConsoleView() {
  const [summary, setSummary] = useState<StatsSummary | null>(null);
  const [history, setHistory] = useState<TaskStatRow[]>([]);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    try {
      const [s, h] = await Promise.all([
        apiRequest<StatsSummary>("/api/stats"),
        apiRequest<TaskStatRow[]>("/api/stats/history?limit=50"),
      ]);
      setSummary(s);
      setHistory(h);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void load(); }, []);

  return (
    <div className="page-view">
      <header className="page-heading">
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <div>
            <h1>控制台</h1>
            <p>Token 消耗与任务执行统计。</p>
          </div>
          <button
            className="button-secondary"
            onClick={() => void load()}
            disabled={loading}
            style={{ display: "inline-flex", alignItems: "center", gap: 6 }}
          >
            <RefreshCw size={14} className={loading ? "spin" : ""} />
            刷新
          </button>
        </div>
      </header>

      {/* 汇总卡片 */}
      <div className="console-cards">
        <StatCard
          icon={Zap}
          label="总 Token"
          value={formatTokens(summary?.total_all_tokens ?? 0)}
          sub={`文本 ${formatTokens(summary?.total_text_tokens ?? 0)} · 视觉 ${formatTokens(summary?.total_vision_tokens ?? 0)}`}
        />
        <StatCard
          icon={Clock}
          label="总耗时"
          value={formatDuration(summary?.total_duration_ms ?? 0)}
          sub={`${summary?.task_count ?? 0} 个任务`}
        />
        <StatCard
          icon={Cpu}
          label="平均 Token / 任务"
          value={formatTokens(summary?.avg_tokens_per_task ?? 0)}
        />
        <StatCard
          icon={Activity}
          label="总步数"
          value={String(summary?.total_steps ?? 0)}
          sub={`Prompt ${formatTokens(summary?.total_text_prompt ?? 0)} · Completion ${formatTokens(summary?.total_text_completion ?? 0)}`}
        />
      </div>

      {/* 视觉 Token 占比 */}
      {summary && summary.total_all_tokens > 0 ? (
        <div className="console-ratio-bar-wrap">
          <span className="console-ratio-label">Token 分布</span>
          <div className="console-ratio-bar">
            <div
              className="console-ratio-fill text"
              style={{ width: `${(summary.total_text_tokens / summary.total_all_tokens) * 100}%` }}
              title={`文本: ${formatTokens(summary.total_text_tokens)}`}
            />
            <div
              className="console-ratio-fill vision"
              style={{ width: `${(summary.total_vision_tokens / summary.total_all_tokens) * 100}%` }}
              title={`视觉: ${formatTokens(summary.total_vision_tokens)}`}
            />
          </div>
          <div className="console-ratio-legend">
            <span><i className="legend-dot text" />文本 {formatTokens(summary.total_text_tokens)}</span>
            <span><i className="legend-dot vision" />视觉 {formatTokens(summary.total_vision_tokens)}</span>
            {summary.total_text_cache_read > 0 ? (
              <span><i className="legend-dot cache" />缓存命中 {formatTokens(summary.total_text_cache_read)}</span>
            ) : null}
          </div>
        </div>
      ) : null}

      {/* 历史明细表 */}
      <h2 className="console-section-title">最近任务明细</h2>
      {history.length === 0 ? (
        <p className="console-empty">暂无统计数据。运行 Agent 任务后将在此显示。</p>
      ) : (
        <div className="task-table" role="table">
          <div className="task-table-head" role="row">
            <span>任务 ID</span>
            <span>Token</span>
            <span>耗时</span>
            <span>步数</span>
            <span>时间</span>
          </div>
          {history.map((row) => (
            <div className="task-table-row" role="row" key={row.task_id}>
              <span title={row.task_id}>{row.task_id.replace("task_", "").slice(0, 12)}…</span>
              <span>{formatTokens(row.text_total_tokens + row.vision_total_tokens)}</span>
              <span>{formatDuration(row.duration_ms)}</span>
              <span>{row.step_count}</span>
              <span>{formatTime(row.created_at)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

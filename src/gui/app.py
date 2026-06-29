"""
简易 Web GUI —— 浏览器自动化任务执行界面。

提供:
- 任务输入和执行
- 实时执行步骤展示
- 技能库浏览
- 脚本查看

启动方式:
    python -m src.gui.app
    或
    browser-agent gui
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

# 添加项目根目录到路径
_project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_project_root))

from flask import Flask, jsonify, render_template_string, request  # noqa: E402

from src.core.agent_loop import AgentLoop  # noqa: E402
from src.core.auth_manager import get_auth_manager  # noqa: E402
from src.core.browser_manager import get_browser_manager  # noqa: E402
from src.core.script_store import get_script_store  # noqa: E402
from src.skill_library.registry import get_skill_registry  # noqa: E402

app = Flask(__name__)

# 保存当前活跃的 BrowserManager 引用，供 /api/close-browser 使用
_active_bm = None
_close_requested = False


def _load_domain_hosts() -> dict[str, str]:
    """Return domain-name -> hostname mapping from domains/*.yaml."""
    import yaml

    domains_dir = _project_root / "domains"
    hosts: dict[str, str] = {}
    if not domains_dir.is_dir():
        return hosts

    for path in domains_dir.glob("*.yaml"):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:
            data = {}

        domain = data.get("name") or path.stem
        base_url = data.get("base_url") or ""
        host = urlparse(base_url).hostname or ""
        if domain and host:
            hosts[str(domain)] = host.removeprefix("www.")

    return hosts


def _domain_from_url(url: str) -> str | None:
    """Map a browser URL back to a configured domain name."""
    host = (urlparse(url).hostname or "").removeprefix("www.")
    if not host:
        return None

    for domain, domain_host in _load_domain_hosts().items():
        if host == domain_host or host.endswith(f".{domain_host}"):
            return domain
        if domain in host:
            return domain

    return _domain_from_host(host)


def _domain_from_host(host: str) -> str | None:
    """Fallback domain name for sites without domains/*.yaml entries."""
    parts = [part for part in host.removeprefix("www.").split(".") if part]
    if not parts:
        return None
    if len(parts) >= 2 and parts[-2] in {"com", "net", "org", "gov", "edu"}:
        return parts[-3] if len(parts) >= 3 else parts[0]
    return parts[-2] if len(parts) >= 2 else parts[0]


def _domain_from_task(task: str) -> str | None:
    """Best-effort domain detection before running a GUI task."""
    task_lower = task.lower()
    aliases = {
        "zhihu": ("知乎",),
        "weibo": ("微博",),
        "douyin": ("抖音",),
        "xiaohongshu": ("小红书",),
        "bilibili": ("B站", "b站", "哔哩哔哩", "哔哩", "bilibili"),
    }

    for domain, names in aliases.items():
        if any(name in task for name in names):
            return domain

    for domain, host in _load_domain_hosts().items():
        if domain.lower() in task_lower or host.lower() in task_lower:
            return domain

    match = re.search(r"https?://([^/\s，,]+)", task_lower)
    if match:
        host = match.group(1).split(":")[0]
        return _domain_from_host(host)

    return None


SITE_LOGIN_COOKIES = {
    "zhihu": {"z_c0"},
}


def _storage_state_has_session(state: dict, domain: str | None = None) -> bool:
    """Heuristic: decide whether current context contains save-worthy state."""
    cookie_names = {
        str(cookie.get("name", "")).lower() for cookie in state.get("cookies", [])
    }
    site_cookie_names = SITE_LOGIN_COOKIES.get((domain or "").lower())
    if site_cookie_names is not None:
        return any(name.lower() in cookie_names for name in site_cookie_names)

    auth_words = (
        "auth",
        "login",
        "session",
        "token",
        "uid",
        "user",
        "account",
        "passport",
        "sub",
        "sso",
    )

    for name in cookie_names:
        if any(word in name for word in auth_words):
            return True

    for origin in state.get("origins", []):
        for item in origin.get("localStorage", []):
            name = str(item.get("name", "")).lower()
            if any(word in name for word in auth_words):
                return True

    return False


# HTML 模板
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Agentic Playwright MCP</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #f5f5f5;
            color: #333;
        }
        .container {
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
        }
        header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px 0;
            margin-bottom: 30px;
        }
        header h1 {
            text-align: center;
            font-size: 2em;
        }
        header p {
            text-align: center;
            opacity: 0.9;
            margin-top: 10px;
        }
        .card {
            background: white;
            border-radius: 12px;
            padding: 24px;
            margin-bottom: 20px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }
        .card h2 {
            color: #667eea;
            margin-bottom: 16px;
            font-size: 1.2em;
        }
        .task-input {
            display: flex;
            gap: 12px;
        }
        .task-input input {
            flex: 1;
            padding: 12px 16px;
            border: 2px solid #e0e0e0;
            border-radius: 8px;
            font-size: 16px;
            transition: border-color 0.3s;
        }
        .task-input input:focus {
            outline: none;
            border-color: #667eea;
        }
        .btn {
            padding: 12px 24px;
            border: none;
            border-radius: 8px;
            font-size: 16px;
            cursor: pointer;
            transition: all 0.3s;
        }
        .btn-primary {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
        }
        .btn-primary:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4);
        }
        .btn-primary:disabled {
            opacity: 0.6;
            cursor: not-allowed;
            transform: none;
        }
        .btn-secondary {
            background: #f0f0f0;
            color: #333;
        }
        .btn-secondary:hover {
            background: #e0e0e0;
        }
        .output {
            background: #1e1e1e;
            color: #d4d4d4;
            padding: 16px;
            border-radius: 8px;
            font-family: 'Monaco', 'Menlo', monospace;
            font-size: 14px;
            line-height: 1.6;
            max-height: 400px;
            overflow-y: auto;
            white-space: pre-wrap;
        }
        .output .step {
            margin-bottom: 8px;
            padding: 8px;
            border-radius: 4px;
        }
        .output .step.success {
            background: rgba(76, 175, 80, 0.2);
            border-left: 3px solid #4caf50;
        }
        .output .step.error {
            background: rgba(244, 67, 54, 0.2);
            border-left: 3px solid #f44336;
        }
        .output .step.info {
            background: rgba(33, 150, 243, 0.2);
            border-left: 3px solid #2196f3;
        }
        .status {
            display: inline-block;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 14px;
            font-weight: 500;
        }
        .status.running {
            background: #fff3e0;
            color: #e65100;
            animation: pulse 1.5s infinite;
        }
        .status.success {
            background: #e8f5e9;
            color: #2e7d32;
        }
        .status.error {
            background: #ffebee;
            color: #c62828;
        }
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.6; }
        }
        .skills-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
            gap: 12px;
        }
        .skill-item {
            padding: 12px;
            background: #f8f9fa;
            border-radius: 8px;
            border: 1px solid #e0e0e0;
        }
        .skill-item h3 {
            color: #667eea;
            font-size: 1em;
            margin-bottom: 4px;
        }
        .skill-item p {
            font-size: 0.85em;
            color: #666;
        }
        .skill-item .triggers {
            margin-top: 8px;
        }
        .skill-item .trigger {
            display: inline-block;
            padding: 2px 8px;
            background: #e8eaf6;
            border-radius: 12px;
            font-size: 0.75em;
            color: #3f51b5;
            margin-right: 4px;
            margin-bottom: 4px;
        }
        .options {
            display: flex;
            gap: 16px;
            margin-top: 12px;
        }
        .options label {
            display: flex;
            align-items: center;
            gap: 6px;
            cursor: pointer;
        }
        .spinner {
            display: inline-block;
            width: 16px;
            height: 16px;
            border: 2px solid #fff;
            border-top-color: transparent;
            border-radius: 50%;
            animation: spin 0.8s linear infinite;
        }
        @keyframes spin {
            to { transform: rotate(360deg); }
        }
        .tabs {
            display: flex;
            gap: 4px;
            margin-bottom: 16px;
        }
        .tab {
            padding: 8px 16px;
            background: #f0f0f0;
            border: none;
            border-radius: 8px 8px 0 0;
            cursor: pointer;
            font-size: 14px;
        }
        .tab.active {
            background: #667eea;
            color: white;
        }
        .tab-content {
            display: none;
        }
        .tab-content.active {
            display: block;
        }
    </style>
</head>
<body>
    <header>
        <div class="container">
            <h1>🤖 Agentic Playwright MCP</h1>
            <p>AI 驱动的浏览器自动化框架 — 输入任务，AI 自动执行</p>
        </div>
    </header>

    <div class="container">
        <!-- 任务输入 -->
        <div class="card">
            <h2>📝 执行任务</h2>
            <div class="task-input">
                <input type="text" id="taskInput" placeholder="输入任务描述，例如：帮我在百度搜索 Python 教程" />
                <button class="btn btn-primary" id="runBtn" onclick="runTask()">
                    执行
                </button>
            </div>
            <div class="options">
                <label>
                    <input type="checkbox" id="headless" />
                    无头模式
                </label>
                <label>
                    <input type="checkbox" id="useCloak" checked />
                    CloakBrowser 反检测
                </label>
                <label>
                    最大步数:
                    <input type="number" id="maxSteps" value="10" min="1" max="50" style="width:60px;padding:4px;border:1px solid #ddd;border-radius:4px;" />
                </label>
                <label>
                    <input type="checkbox" id="keepOpen" checked />
                    保持浏览器开启
                </label>
            </div>
        </div>

        <!-- 执行结果 -->
        <div class="card">
            <h2>
                📊 执行结果
                <span class="status" id="status" style="display:none;"></span>
                <button class="btn btn-primary" id="closeBtn" onclick="closeBrowser()" style="display:none;float:right;font-size:14px;padding:6px 16px;">
                    关闭浏览器
                </button>
            </h2>
            <div class="output" id="output">
                等待执行...
            </div>
        </div>

        <!-- 标签页: 技能库 / 脚本历史 -->
        <div class="card">
            <div class="tabs">
                <button class="tab active" onclick="switchTab('skills')">📚 技能库</button>
                <button class="tab" onclick="switchTab('scripts')">📜 脚本历史</button>
            </div>

            <div class="tab-content active" id="tab-skills">
                <div class="skills-grid" id="skillsGrid">
                    加载中...
                </div>
            </div>

            <div class="tab-content" id="tab-scripts">
                <div id="scriptsList">
                    加载中...
                </div>
            </div>
        </div>
    </div>

    <script>
        const promptedSaveDomains = new Set();
        let authPollTimer = null;

        async function maybeLoadSavedAuth(task, options) {
            const response = await fetch('/api/auth/suggest-load', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ task }),
            });
            const result = await response.json();
            if (result.domain && result.has_auth) {
                const ok = confirm(`检测到 ${result.domain} 已有保存的登录信息，是否本次先加载？`);
                if (ok) {
                    options.load_auth_domain = result.domain;
                }
            }
        }

        function startAuthPolling() {
            if (authPollTimer) {
                clearInterval(authPollTimer);
            }
            authPollTimer = setInterval(checkCurrentAuthState, 3000);
        }

        function stopAuthPolling() {
            if (authPollTimer) {
                clearInterval(authPollTimer);
                authPollTimer = null;
            }
        }

        async function checkCurrentAuthState() {
            try {
                const response = await fetch('/api/auth/current');
                const result = await response.json();
                if (!result.browser_running) {
                    // 浏览器已关闭，更新 UI 状态
                    const closeBtn = document.getElementById('closeBtn');
                    if (closeBtn) closeBtn.style.display = 'none';
                    stopAuthPolling();
                    return;
                }
                if (!result.domain || !result.has_session) {
                    return;
                }
                if (promptedSaveDomains.has(result.domain)) {
                    return;
                }
                promptedSaveDomains.add(result.domain);
                const action = result.has_auth ? '更新保存' : '保存';
                const ok = confirm(`检测到当前 ${result.domain} 页面可能已有登录状态，是否${action}登录信息？`);
                if (!ok) {
                    return;
                }
                const saveResponse = await fetch('/api/auth/save', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ domain: result.domain }),
                });
                const saved = await saveResponse.json();
                if (saved.success) {
                    alert(`已保存 ${result.domain} 登录信息：${saved.path}`);
                } else {
                    alert(`保存失败：${saved.error || '未知错误'}`);
                }
            } catch (error) {
                console.warn('Auth polling failed:', error);
            }
        }
        // 任务执行
        async function runTask() {
            const task = document.getElementById('taskInput').value.trim();
            if (!task) {
                alert('请输入任务描述');
                return;
            }

            const runBtn = document.getElementById('runBtn');
            const status = document.getElementById('status');
            const output = document.getElementById('output');

            // 禁用按钮，显示状态
            runBtn.disabled = true;
            runBtn.innerHTML = '<span class="spinner"></span> 执行中...';
            status.style.display = 'inline-block';
            status.className = 'status running';
            status.textContent = '执行中';
            output.innerHTML = '';

            const keepOpen = document.getElementById('keepOpen').checked;
            const options = {
                task: task,
                headless: document.getElementById('headless').checked,
                use_cloak: document.getElementById('useCloak').checked,
                max_steps: parseInt(document.getElementById('maxSteps').value) || 10,
                keep_open: keepOpen,
            };

            let taskSuccess = false;
            try {
                await maybeLoadSavedAuth(task, options);
                const response = await fetch('/api/run', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(options),
                });

                const result = await response.json();
                taskSuccess = result.success;

                if (result.success) {
                    status.className = 'status success';
                    status.textContent = '完成';
                    output.innerHTML = formatResult(result);
                } else {
                    status.className = 'status error';
                    status.textContent = '失败';
                    output.innerHTML = formatResult(result);
                }
            } catch (error) {
                status.className = 'status error';
                status.textContent = '错误';
                output.innerHTML = `<div class="step error">请求失败: ${error.message}</div>`;
            } finally {
                runBtn.disabled = false;
                runBtn.innerHTML = '执行';
                // 仅在任务成功且 keep_open 时显示"关闭浏览器"按钮和启动轮询
                const closeBtn = document.getElementById('closeBtn');
                if (keepOpen && taskSuccess) {
                    closeBtn.style.display = 'inline-block';
                    startAuthPolling();
                } else {
                    closeBtn.style.display = 'none';
                    stopAuthPolling();
                }
            }
        }

        function formatResult(result) {
            let html = '';

            if (result.steps) {
                result.steps.forEach(step => {
                    const cls = step.success ? 'success' : 'error';
                    html += `<div class="step ${cls}">`;
                    html += `<strong>Step ${step.step_number} [${step.state}]</strong>: ${step.result || ''}`;
                    if (step.error) {
                        html += `<br><span style="color:#f44336">${step.error}</span>`;
                    }
                    html += `</div>`;
                });
            }

            if (result.output) {
                html += `<div class="step info"><strong>输出:</strong><br>${escapeHtml(result.output)}</div>`;
            }

            if (result.error) {
                html += `<div class="step error"><strong>错误:</strong> ${escapeHtml(result.error)}</div>`;
            }

            if (result.final_url) {
                html += `<div class="step info"><strong>最终 URL:</strong> ${result.final_url}</div>`;
            }

            if (result.auth_domain) {
                html += `<div class="step info"><strong>已加载登录信息:</strong> ${escapeHtml(result.auth_domain)}</div>`;
            }

            return html || '无输出';
        }

        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        // 关闭保持开启的浏览器
        async function closeBrowser() {
            const closeBtn = document.getElementById('closeBtn');
            closeBtn.disabled = true;
            closeBtn.innerHTML = '关闭中...';
            try {
                await fetch('/api/close-browser', { method: 'POST' });
                closeBtn.style.display = 'none';
                const status = document.getElementById('status');
                status.className = 'status success';
                stopAuthPolling();
                status.textContent = '浏览器已关闭';
            } catch (error) {
                alert('关闭失败: ' + error.message);
            } finally {
                closeBtn.disabled = false;
                closeBtn.innerHTML = '关闭浏览器';
            }
        }

        // 标签页切换
        function switchTab(name) {
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));

            event.target.classList.add('active');
            document.getElementById(`tab-${name}`).classList.add('active');
        }

        // 加载技能库
        async function loadSkills() {
            try {
                const response = await fetch('/api/skills');
                const skills = await response.json();

                const grid = document.getElementById('skillsGrid');
                if (skills.length === 0) {
                    grid.innerHTML = '<p>暂无技能</p>';
                    return;
                }

                grid.innerHTML = skills.map(skill => `
                    <div class="skill-item">
                        <h3>${escapeHtml(skill.name)}</h3>
                        <p>${escapeHtml(skill.description || '')}</p>
                        <div class="triggers">
                            ${(skill.triggers || []).map(t =>
                                `<span class="trigger">${escapeHtml(t)}</span>`
                            ).join('')}
                        </div>
                    </div>
                `).join('');
            } catch (error) {
                document.getElementById('skillsGrid').innerHTML = `<p>加载失败: ${error.message}</p>`;
            }
        }

        // 加载脚本历史
        async function loadScripts() {
            try {
                const response = await fetch('/api/scripts');
                const scripts = await response.json();

                const list = document.getElementById('scriptsList');
                if (scripts.length === 0) {
                    list.innerHTML = '<p>暂无脚本</p>';
                    return;
                }

                list.innerHTML = scripts.map(script => `
                    <div class="skill-item">
                        <h3>${escapeHtml(script.task)}</h3>
                        <p>使用 ${script.use_count} 次，成功率 ${(script.success_rate * 100).toFixed(0)}%</p>
                        <details>
                            <summary style="cursor:pointer;color:#667eea;margin-top:8px;">查看脚本</summary>
                            <pre style="background:#f5f5f5;padding:8px;border-radius:4px;margin-top:8px;overflow-x:auto;">${escapeHtml(script.script)}</pre>
                        </details>
                    </div>
                `).join('');
            } catch (error) {
                document.getElementById('scriptsList').innerHTML = `<p>加载失败: ${error.message}</p>`;
            }
        }

        // 回车执行
        document.getElementById('taskInput').addEventListener('keypress', (e) => {
            if (e.key === 'Enter') runTask();
        });

        // 页面加载
        loadSkills();
        loadScripts();
    </script>
</body>
</html>
"""


@app.route("/")
def index():
    """主页。"""
    return render_template_string(HTML_TEMPLATE)


@app.route("/api/run", methods=["POST"])
def api_run():
    """执行任务 API。

    Playwright sync API 不支持跨线程调用，所以每个请求
    必须在同一线程内完成 launch → run → close 全流程。
    """
    from src.core.browser_manager import reset_browser_manager
    from src.core.script_engine import reset_script_engine

    data = request.json
    task = data.get("task", "")
    headless = data.get("headless", False)
    use_cloak = data.get("use_cloak", False)
    max_steps = data.get("max_steps", 10)
    keep_open = data.get("keep_open", False)
    load_auth_domain = data.get("load_auth_domain")

    if not task:
        return jsonify({"success": False, "error": "任务描述不能为空"})

    global _active_bm, _close_requested
    _close_requested = False

    try:
        # 设置环境变量
        if use_cloak:
            os.environ["USE_CLOAKBROWSER"] = "true"
        else:
            os.environ["USE_CLOAKBROWSER"] = "false"

        # 重置所有状态（确保线程安全）
        reset_script_engine()
        reset_browser_manager()

        # 在当前线程启动浏览器
        bm = get_browser_manager()
        _active_bm = bm
        if load_auth_domain:
            bm.launch_with_domain(domain=load_auth_domain, headless=headless)
        else:
            bm.launch(headless=headless)

        # 执行任务
        agent = AgentLoop(max_steps=max_steps)
        result = agent.run(task)

        # 保存最终 URL
        final_url = result.final_url or ""

        # 关闭浏览器（keep_open 模式下保留浏览器供用户查看）
        if not keep_open or _close_requested:
            bm.close()
            _active_bm = None
            _close_requested = False

        return jsonify(
            {
                "success": result.success,
                "task": result.task,
                "steps": [
                    {
                        "step_number": s.step_number,
                        "state": s.state.value
                        if hasattr(s.state, "value")
                        else str(s.state),
                        "action": s.action,
                        "result": s.result,
                        "success": s.success,
                        "error": s.error,
                    }
                    for s in result.steps
                ],
                "output": result.output,
                "final_url": final_url,
                "error": result.error,
                "auth_domain": load_auth_domain,
            }
        )

    except Exception as exc:
        # 尝试清理浏览器
        _active_bm = None
        _close_requested = False
        try:
            reset_browser_manager()
        except Exception:
            pass
        return jsonify(
            {
                "success": False,
                "error": f"{type(exc).__name__}: {exc}",
            }
        )


@app.route("/api/auth/suggest-load", methods=["POST"])
def api_auth_suggest_load():
    """Suggest loading saved auth before a GUI task starts."""
    data = request.json or {}
    task = data.get("task", "")
    domain = _domain_from_task(task)
    if not domain:
        return jsonify({"domain": None, "has_auth": False})

    am = get_auth_manager()
    return jsonify({"domain": domain, "has_auth": am.has_auth(domain)})


@app.route("/api/auth/current")
def api_auth_current():
    """Inspect the keep-open browser and report whether auth can be saved."""
    global _active_bm
    bm = _active_bm or get_browser_manager()
    if not bm.is_alive():
        # 浏览器已关闭，清理引用以避免后续状态不一致
        if _active_bm is not None:
            _active_bm = None
            try:
                from src.core.browser_manager import reset_browser_manager

                reset_browser_manager()
            except Exception:
                pass
        return jsonify({"browser_running": False})

    try:
        page = bm.get_page()
        # 实际测试页面是否可访问（窗口被关闭但进程还在时 page.url 可能不抛异常）
        try:
            page.evaluate("1")
        except Exception:
            # 页面不可访问，浏览器已断开
            _active_bm = None
            try:
                from src.core.browser_manager import reset_browser_manager

                reset_browser_manager()
            except Exception:
                pass
            return jsonify({"browser_running": False})
        current_url = page.url
        domain = bm.current_domain or _domain_from_url(current_url)
        has_session = False

        if bm._context is not None:
            state = bm._context.storage_state()
            has_session = _storage_state_has_session(state, domain)

        am = get_auth_manager()
        return jsonify(
            {
                "browser_running": True,
                "url": current_url,
                "domain": domain,
                "has_auth": am.has_auth(domain) if domain else False,
                "has_session": has_session,
            }
        )
    except Exception as exc:
        # 浏览器异常，清理引用
        if _active_bm is not None:
            _active_bm = None
            try:
                from src.core.browser_manager import reset_browser_manager

                reset_browser_manager()
            except Exception:
                pass
        return jsonify({"browser_running": False, "error": str(exc)})


@app.route("/api/auth/save", methods=["POST"])
def api_auth_save():
    """Save the active browser context auth for a domain."""
    data = request.json or {}
    bm = _active_bm or get_browser_manager()

    if not bm.is_alive() or bm._context is None:
        return jsonify({"success": False, "error": "浏览器未启动或没有可保存的上下文"})

    try:
        page = bm.get_page()
        domain = data.get("domain") or bm.current_domain or _domain_from_url(page.url)
        if not domain:
            return jsonify({"success": False, "error": "无法识别当前站点"})

        am = get_auth_manager()
        path = am.save_auth(domain, bm._context)
        return jsonify({"success": True, "domain": domain, "path": str(path)})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)})


@app.route("/api/close-browser", methods=["POST"])
def api_close_browser():
    """关闭 keep-open 模式下保持开启的浏览器。

    如果任务仍在运行，设置标志让任务结束后自动关闭；
    如果任务已完成，直接关闭浏览器。
    """
    global _active_bm, _close_requested

    try:
        # 设置标志：任务结束后自动关闭
        _close_requested = True

        # 尝试直接关闭（任务已完成时有效）
        if _active_bm is not None:
            try:
                _active_bm.close()
            except Exception:
                # 浏览器可能已被手动关闭，忽略异常
                pass
            # 无论 close 成功与否，都清理引用和标志
            _active_bm = None
            _close_requested = False
            try:
                from src.core.browser_manager import reset_browser_manager

                reset_browser_manager()
            except Exception:
                pass

        return jsonify({"success": True})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)})


@app.route("/api/skills")
def api_skills():
    """获取技能列表 API。"""
    from src.skill_library.registry import reset_skill_registry

    try:
        reset_skill_registry()
        library_dir = str(_project_root / "src" / "skill_library")
        registry = get_skill_registry(library_dir=library_dir)
        skills = registry.list_all()

        return jsonify(
            [
                {
                    "id": s.id,
                    "name": s.name,
                    "type": s.type,
                    "triggers": s.triggers,
                    "url_patterns": s.url_patterns,
                    "description": s.description,
                }
                for s in skills
            ]
        )

    except Exception:
        return jsonify([])


@app.route("/api/scripts")
def api_scripts():
    """获取脚本历史 API。"""
    try:
        store = get_script_store()
        scripts = store.list_all()

        return jsonify(
            [
                {
                    "id": s.id,
                    "task": s.task,
                    "script": s.script,
                    "use_count": s.use_count,
                    "success_count": s.success_count,
                    "success_rate": s.success_rate,
                    "created_at": s.created_at,
                    "last_used_at": s.last_used_at,
                }
                for s in scripts
            ]
        )

    except Exception:
        return jsonify([])


@app.route("/api/status")
def api_status():
    """获取系统状态 API。"""
    from src.config_manager import get_config_manager

    bm = get_browser_manager()
    config = get_config_manager()
    return jsonify(
        {
            "browser_running": bm.is_alive(),
            "engine": bm.engine if bm.is_alive() else None,
            "configured": config.is_configured(),
            "vision_provider": config.get("vision.provider", ""),
        }
    )


@app.route("/api/config", methods=["GET"])
def api_get_config():
    """获取配置 API。"""
    from src.config_manager import get_config_manager

    config = get_config_manager()
    return jsonify(
        {
            "configured": config.is_configured(),
            "vision": config.get_vision_config(),
            "browser": config.get_browser_config(),
        }
    )


@app.route("/api/config", methods=["POST"])
def api_set_config():
    """设置配置 API。"""
    from src.config_manager import get_config_manager

    config = get_config_manager()

    data = request.json
    if not data:
        return jsonify({"success": False, "error": "No data provided"})

    for key, value in data.items():
        config.set(key, value)

    config.apply_to_env()
    return jsonify({"success": True})


def main():
    """启动 GUI。"""
    import argparse

    parser = argparse.ArgumentParser(description="Agentic Playwright MCP GUI")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址")
    parser.add_argument("--port", type=int, default=8080, help="监听端口")
    parser.add_argument("--debug", action="store_true", help="调试模式")

    args = parser.parse_args()

    print(f"Starting GUI: http://{args.host}:{args.port}")
    print("Press Ctrl+C to stop")

    app.run(host=args.host, port=args.port, debug=args.debug, threaded=False)


if __name__ == "__main__":
    main()

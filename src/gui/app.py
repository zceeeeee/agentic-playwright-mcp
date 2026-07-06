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


def _cookie_values(state: dict) -> dict[str, str]:
    return {
        str(cookie.get("name", "")).lower(): str(cookie.get("value", "")).strip()
        for cookie in state.get("cookies", [])
    }


def _zhihu_auth_state(state: dict) -> str:
    """Detect Zhihu login from the z_c0 cookie."""
    cookie_values = _cookie_values(state)
    return "logged_in" if cookie_values.get("z_c0") else "logged_out"


def _xiaohongshu_auth_state(state: dict) -> str:
    """Detect Xiaohongshu login from values that differ before/after login."""
    cookie_values = _cookie_values(state)
    has_login_cookies = bool(
        cookie_values.get("web_session")
        and cookie_values.get("id_token")
        and cookie_values.get("x-rednote-datactry")
        and cookie_values.get("x-rednote-holderctry")
    )
    return "logged_in" if has_login_cookies else "logged_out"


def _storage_state_auth_state(state: dict, domain: str | None = None) -> str:
    """Return logged_in/logged_out/unknown for the current browser context."""
    domain_key = (domain or "").lower()
    if domain_key == "zhihu":
        return _zhihu_auth_state(state)
    if domain_key == "xiaohongshu":
        return _xiaohongshu_auth_state(state)

    return "logged_in" if _storage_state_has_session(state, domain) else "unknown"


def _storage_state_has_session(state: dict, domain: str | None = None) -> bool:
    """Heuristic: decide whether current context contains save-worthy state."""
    if (domain or "").lower() in {"zhihu", "xiaohongshu"}:
        return _storage_state_auth_state(state, domain) == "logged_in"

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


# ---------------------------------------------------------------------------
# 技能库辅助函数
# ---------------------------------------------------------------------------

# 平台名称映射（英文 → 中文显示名）
PLATFORM_NAMES = {
    "baidu": "百度",
    "google": "Google",
    "bing": "Bing",
    "github": "GitHub",
    "amazon": "Amazon",
    "youtube": "YouTube",
    "bilibili": "Bilibili",
    "weibo": "微博",
    "taobao": "淘宝",
    "doubao": "豆包",
    "csdn": "CSDN",
    "xiaohongshu": "小红书",
    "zhihu": "知乎",
    "gmail": "Gmail",
    "outlook": "Outlook",
}

# 操作类型映射（action 字段 → 中文标签）
ACTION_LABELS = {
    "search": "搜索",
    "login": "登录",
    "send": "发送",
    "inbox": "收件箱",
    "publish": "发布",
    "comment": "评论",
    "browse": "浏览",
    "download": "下载",
    "upload": "上传",
}


def _extract_platform(skill) -> str:
    """从技能元数据提取平台标识。

    优先级: YAML platform 字段 > id 前缀 > url_patterns。
    """
    # 1. 直接使用 platform 字段（如果 SkillMeta 有此属性）
    platform = getattr(skill, "platform", None)
    if platform:
        return platform

    # 2. 从 id 提取（如 "domain/baidu_search" → "baidu"）
    skill_id = skill.id
    if "/" in skill_id:
        prefix = skill_id.split("/")[1]
        # 去掉常见后缀
        for suffix in ["_search", "_login", "_send", "_inbox", "_publish", "_comment"]:
            prefix = prefix.replace(suffix, "")
        if prefix in PLATFORM_NAMES:
            return prefix

    # 3. 从 url_patterns 提取
    for pattern in skill.url_patterns:
        domain = pattern.strip("*.").split(".")[0]
        if domain in PLATFORM_NAMES:
            return domain

    return "other"


def _extract_action(skill) -> str:
    """从技能元数据提取操作类型标签。

    优先级: YAML action 字段 > 技能名称关键词。
    """
    # 1. 直接使用 action 字段
    action = getattr(skill, "action", None)
    if action and action in ACTION_LABELS:
        return ACTION_LABELS[action]

    # 2. 从技能名称提取
    name = skill.name
    action_keywords = {
        "搜索": "搜索",
        "登录": "登录",
        "发送": "发送",
        "收件箱": "收件箱",
        "发布": "发布",
        "评论": "评论",
        "浏览": "浏览",
        "下载": "下载",
        "上传": "上传",
        "投稿": "发布",
        "留言": "评论",
        "发邮件": "发送",
        "寄邮件": "发送",
    }
    for keyword, label in action_keywords.items():
        if keyword in name:
            return label

    return "其他"


def _format_time(timestamp: float) -> str:
    """将时间戳格式化为相对时间字符串。"""
    if not timestamp:
        return "未知"

    import time

    now = time.time()
    diff = now - timestamp

    if diff < 60:
        return "刚刚"
    elif diff < 3600:
        return f"{int(diff / 60)} 分钟前"
    elif diff < 86400:
        return f"{int(diff / 3600)} 小时前"
    elif diff < 604800:
        return f"{int(diff / 86400)} 天前"
    else:
        from datetime import datetime

        return datetime.fromtimestamp(timestamp).strftime("%m月%d日")


# HTML 模板 — Mistral AI 设计系统
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Agentic Playwright MCP</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400&display=swap" rel="stylesheet">
    <style>
        :root {
            /* Brand & Accent */
            --primary: #fa520f;
            --primary-deep: #cc3a05;
            --on-primary: #ffffff;
            --sunshine-300: #ffd06a;
            --sunshine-500: #ffb83e;
            --sunshine-700: #ffa110;
            --sunshine-800: #ff8105;
            --sunshine-900: #ff8a00;
            --yellow-saturated: #ffd900;
            /* Cream / Neutral Warm */
            --cream: #fff8e0;
            --cream-light: #fffaeb;
            --cream-deeper: #fff0c2;
            --beige-deep: #e6d5a8;
            /* Surface */
            --canvas: #ffffff;
            --surface: #fafafa;
            --surface-code: #1c1c1e;
            --hairline: #e5e5e5;
            --hairline-soft: #ededed;
            --hairline-strong: #c7c7c7;
            /* Text */
            --ink: #1f1f1f;
            --ink-tint: #3d3d3d;
            --charcoal: #2c2c2c;
            --slate: #4a4a4a;
            --steel: #6a6a6a;
            --stone: #8a8a8a;
            --muted: #a8a8a8;
            --on-dark: #ffffff;
            --on-dark-muted: #a8a8a8;
            --footer-cream: #fff8e0;
            --link: #fa520f;
            /* Radius */
            --radius-xs: 4px;
            --radius-sm: 6px;
            --radius-md: 8px;
            --radius-lg: 12px;
            --radius-xl: 16px;
            --radius-full: 9999px;
            /* Spacing */
            --sp-xxs: 4px;
            --sp-xs: 8px;
            --sp-sm: 12px;
            --sp-md: 16px;
            --sp-lg: 20px;
            --sp-xl: 24px;
            --sp-xxl: 32px;
            --sp-section: 64px;
            --sp-hero: 120px;
            /* Typography */
            --font-display: 'Times New Roman', Georgia, serif;
            --font-body: 'Inter', ui-sans-serif, system-ui, -apple-system, sans-serif;
            --font-code: 'JetBrains Mono', 'SF Mono', Menlo, Consolas, monospace;
        }

        * { margin: 0; padding: 0; box-sizing: border-box; }

        body {
            font-family: var(--font-body);
            font-size: 16px;
            line-height: 1.55;
            color: var(--ink);
            background: var(--canvas);
            -webkit-font-smoothing: antialiased;
        }

        /* ── Top Navigation ── */
        .topnav {
            position: sticky;
            top: 0;
            z-index: 100;
            display: flex;
            align-items: center;
            justify-content: space-between;
            height: 64px;
            padding: 0 var(--sp-xxl);
            background: var(--canvas);
            border-bottom: 1px solid var(--hairline-soft);
        }
        .topnav-brand {
            display: flex;
            align-items: center;
            gap: var(--sp-sm);
            font-weight: 600;
            font-size: 18px;
            color: var(--ink);
            text-decoration: none;
        }
        .topnav-brand .logo {
            width: 28px;
            height: 28px;
            background: var(--primary);
            border-radius: var(--radius-sm);
            display: flex;
            align-items: center;
            justify-content: center;
            color: var(--on-primary);
            font-weight: 600;
            font-size: 14px;
        }
        .topnav-status {
            display: flex;
            align-items: center;
            gap: var(--sp-xs);
            font-size: 13px;
            color: var(--steel);
        }
        .topnav-status .dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: var(--muted);
        }
        .topnav-status .dot.active {
            background: #34a853;
        }

        /* ── Hero Band ── */
        .hero-band {
            background: linear-gradient(135deg, var(--sunshine-700) 0%, var(--sunshine-900) 50%, var(--primary) 100%);
            padding: var(--sp-hero) var(--sp-xxl) var(--sp-section);
            text-align: center;
            position: relative;
            overflow: hidden;
        }
        .hero-band::before {
            content: '';
            position: absolute;
            inset: 0;
            background:
                radial-gradient(ellipse 80% 60% at 70% 80%, rgba(255,165,0,0.25) 0%, transparent 70%),
                radial-gradient(ellipse 60% 50% at 30% 90%, rgba(255,69,0,0.15) 0%, transparent 60%);
            pointer-events: none;
        }
        .hero-band h1 {
            font-family: var(--font-display);
            font-size: 84px;
            font-weight: 400;
            line-height: 1.05;
            letter-spacing: -1.5px;
            color: var(--ink);
            position: relative;
        }
        .hero-band .subtitle {
            font-family: var(--font-body);
            font-size: 18px;
            font-weight: 400;
            line-height: 1.50;
            color: var(--ink-tint);
            margin-top: var(--sp-md);
            position: relative;
        }

        /* ── Layout ── */
        .container {
            max-width: 1280px;
            margin: 0 auto;
            padding: 0 var(--sp-xxl);
        }
        .section {
            padding: var(--sp-section) 0;
        }
        .section-heading {
            font-family: var(--font-display);
            font-size: 52px;
            font-weight: 400;
            line-height: 1.15;
            letter-spacing: -0.5px;
            color: var(--ink);
            margin-bottom: var(--sp-xxl);
        }
        .section-label {
            font-size: 11px;
            font-weight: 600;
            line-height: 1.40;
            letter-spacing: 1px;
            text-transform: uppercase;
            color: var(--primary);
            margin-bottom: var(--sp-sm);
        }

        /* ── Cards ── */
        .card {
            background: var(--canvas);
            border-radius: var(--radius-lg);
            padding: var(--sp-xxl);
            border: 1px solid var(--hairline-soft);
            box-shadow: rgba(0,0,0,0.04) 0px 4px 12px 0px;
        }
        .card-cream {
            background: var(--cream);
            border: 1px solid var(--beige-deep);
            border-radius: var(--radius-lg);
            padding: var(--sp-xxl);
        }
        .card-title {
            font-family: var(--font-body);
            font-size: 28px;
            font-weight: 500;
            line-height: 1.25;
            color: var(--ink);
            margin-bottom: var(--sp-lg);
        }
        .card-title-row {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: var(--sp-lg);
        }

        /* ── Inputs ── */
        .input-row {
            display: flex;
            gap: var(--sp-sm);
        }
        .text-input {
            flex: 1;
            height: 44px;
            padding: var(--sp-sm) var(--sp-md);
            border: 1px solid var(--hairline-strong);
            border-radius: var(--radius-md);
            font-family: var(--font-body);
            font-size: 16px;
            line-height: 1.55;
            color: var(--ink);
            background: var(--canvas);
            transition: border-color 150ms ease;
        }
        .text-input::placeholder {
            color: var(--muted);
        }
        .text-input:focus {
            outline: none;
            border: 2px solid var(--primary);
            padding: calc(var(--sp-sm) - 1px) calc(var(--sp-md) - 1px);
        }

        /* ── Buttons ── */
        .btn {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: var(--sp-xs);
            padding: 10px 20px;
            border: none;
            border-radius: var(--radius-md);
            font-family: var(--font-body);
            font-size: 14px;
            font-weight: 500;
            line-height: 1.30;
            cursor: pointer;
            transition: background 150ms ease, box-shadow 150ms ease;
            white-space: nowrap;
        }
        .btn-primary {
            background: var(--primary);
            color: var(--on-primary);
        }
        .btn-primary:hover {
            background: var(--primary-deep);
        }
        .btn-primary:disabled {
            background: var(--hairline);
            color: var(--muted);
            cursor: not-allowed;
        }
        .btn-dark {
            background: var(--ink);
            color: var(--on-dark);
        }
        .btn-dark:hover {
            background: var(--charcoal);
        }
        .btn-secondary {
            background: transparent;
            color: var(--ink);
            border: 1px solid var(--hairline-strong);
        }
        .btn-secondary:hover {
            background: var(--surface);
        }
        .btn-link {
            background: transparent;
            color: var(--primary);
            padding: 0;
            font-size: 14px;
            font-weight: 500;
        }
        .btn-link:hover {
            text-decoration: underline;
        }
        .btn-close-browser {
            background: var(--ink);
            color: var(--on-dark);
            padding: 6px 16px;
            font-size: 13px;
        }
        .btn-close-browser:hover {
            background: var(--charcoal);
        }

        /* ── Spinner ── */
        .spinner {
            display: inline-block;
            width: 16px;
            height: 16px;
            border: 2px solid var(--on-primary);
            border-top-color: transparent;
            border-radius: 50%;
            animation: spin 0.8s linear infinite;
        }
        .spinner-dark {
            border-color: var(--muted);
            border-top-color: transparent;
        }
        @keyframes spin {
            to { transform: rotate(360deg); }
        }

        /* ── Status Badge ── */
        .status {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 4px 12px;
            border-radius: var(--radius-full);
            font-size: 13px;
            font-weight: 600;
            line-height: 1.40;
        }
        .status.running {
            background: var(--cream-deeper);
            color: var(--ink);
            animation: pulse 1.5s infinite;
        }
        .status.success {
            background: #e6f4ea;
            color: #137333;
        }
        .status.error {
            background: #fce8e6;
            color: #c5221f;
        }
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.6; }
        }

        /* ── Options Row ── */
        .options {
            display: flex;
            flex-wrap: wrap;
            gap: var(--sp-lg);
            margin-top: var(--sp-md);
        }
        .options label {
            display: flex;
            align-items: center;
            gap: 6px;
            cursor: pointer;
            font-size: 14px;
            font-weight: 400;
            line-height: 1.50;
            color: var(--slate);
        }
        .options input[type="checkbox"] {
            width: 16px;
            height: 16px;
            accent-color: var(--primary);
            cursor: pointer;
        }
        .options input[type="number"] {
            width: 60px;
            height: 32px;
            padding: 4px 8px;
            border: 1px solid var(--hairline-strong);
            border-radius: var(--radius-sm);
            font-family: var(--font-body);
            font-size: 14px;
            color: var(--ink);
            background: var(--canvas);
        }
        .options input[type="number"]:focus {
            outline: none;
            border: 2px solid var(--primary);
        }

        /* ── Output Terminal ── */
        .output {
            background: var(--surface-code);
            color: #d4d4d4;
            padding: var(--sp-md);
            border-radius: var(--radius-md);
            font-family: var(--font-code);
            font-size: 14px;
            line-height: 1.50;
            max-height: 400px;
            overflow-y: auto;
            white-space: pre-wrap;
        }
        .output .step {
            margin-bottom: var(--sp-xs);
            padding: var(--sp-xs);
            border-radius: var(--radius-xs);
        }
        .output .step.success {
            background: rgba(52,168,83,0.15);
            border-left: 3px solid #34a853;
        }
        .output .step.error {
            background: rgba(197,34,31,0.15);
            border-left: 3px solid #c5221f;
        }
        .output .step.info {
            background: rgba(250,82,15,0.10);
            border-left: 3px solid var(--primary);
        }

        /* ── Segmented Tabs ── */
        .tabs {
            display: flex;
            gap: 0;
            border-bottom: 1px solid var(--hairline);
            margin-bottom: var(--sp-xl);
        }
        .tab {
            padding: var(--sp-sm) var(--sp-md);
            background: transparent;
            border: none;
            border-bottom: 2px solid transparent;
            cursor: pointer;
            font-family: var(--font-body);
            font-size: 14px;
            font-weight: 500;
            line-height: 1.50;
            color: var(--steel);
            transition: color 150ms ease, border-color 150ms ease;
        }
        .tab:hover {
            color: var(--ink);
        }
        .tab.active {
            color: var(--primary);
            border-bottom-color: var(--primary);
        }
        .tab-content {
            display: none;
        }
        .tab-content.active {
            display: block;
        }

        /* ── View Switcher ── */
        .view-switcher {
            display: flex;
            gap: var(--sp-xs);
            margin-bottom: var(--sp-lg);
        }
        .view-btn {
            display: inline-flex;
            align-items: center;
            gap: var(--sp-xxs);
            padding: 8px 16px;
            background: var(--canvas);
            border: 1px solid var(--hairline-soft);
            border-radius: var(--radius-full);
            font-family: var(--font-body);
            font-size: 13px;
            font-weight: 500;
            color: var(--steel);
            cursor: pointer;
            transition: all 150ms ease;
        }
        .view-btn:hover {
            color: var(--ink);
            border-color: var(--stone);
        }
        .view-btn.active {
            background: var(--ink);
            color: var(--on-primary);
            border-color: var(--ink);
        }
        .view-icon {
            font-size: 14px;
        }

        /* ── Platform Grid (按网站视图) ── */
        .platform-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
            gap: var(--sp-md);
        }
        .platform-card {
            padding: var(--sp-lg);
            background: var(--canvas);
            border-radius: var(--radius-lg);
            border: 1px solid var(--hairline-soft);
            transition: box-shadow 150ms ease;
        }
        .platform-card:hover {
            box-shadow: rgba(0,0,0,0.04) 0px 4px 12px 0px;
        }
        .platform-name {
            font-family: var(--font-body);
            font-size: 18px;
            font-weight: 600;
            color: var(--ink);
            margin-bottom: var(--sp-sm);
        }
        .platform-card .tags {
            display: flex;
            flex-wrap: wrap;
            gap: var(--sp-xxs);
        }

        /* ── Skills Grid (按功能视图) ── */
        .skills-grid {
            display: flex;
            flex-direction: column;
            gap: var(--sp-xl);
        }
        .skill-group {
            margin-bottom: var(--sp-sm);
        }
        .skill-group-title {
            font-family: var(--font-body);
            font-size: 16px;
            font-weight: 600;
            color: var(--ink);
            margin-bottom: var(--sp-md);
            padding-bottom: var(--sp-xxs);
            border-bottom: 1px solid var(--hairline-soft);
        }
        .skill-group-items {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
            gap: var(--sp-md);
        }
        .skill-item {
            padding: var(--sp-xl);
            background: var(--canvas);
            border-radius: var(--radius-lg);
            border: 1px solid var(--hairline-soft);
            transition: box-shadow 150ms ease;
        }
        .skill-item:hover {
            box-shadow: rgba(0,0,0,0.04) 0px 4px 12px 0px;
        }
        .skill-item h4 {
            font-family: var(--font-body);
            font-size: 16px;
            font-weight: 500;
            line-height: 1.40;
            color: var(--ink);
            margin-bottom: var(--sp-xxs);
        }
        .skill-item p {
            font-size: 14px;
            color: var(--steel);
            line-height: 1.50;
            margin-bottom: var(--sp-xs);
        }
        .skill-item .tags {
            margin-top: var(--sp-xs);
        }
        .skill-item .tag {
            display: inline-block;
            padding: 4px 10px;
            background: var(--primary-light, #fff5f0);
            border-radius: var(--radius-full);
            font-size: 12px;
            font-weight: 500;
            color: var(--primary);
            margin-right: var(--sp-xxs);
            margin-bottom: var(--sp-xxs);
        }
        .skill-item .tag-platform {
            background: transparent;
            color: var(--steel);
            border: 1px solid var(--hairline-soft);
        }
        .tag-clickable {
            cursor: pointer;
            transition: all 150ms ease;
        }
        .tag-clickable:hover {
            background: var(--primary);
            color: var(--on-primary);
        }

        /* ── Script Card ── */
        .script-card {
            padding: var(--sp-lg);
            background: var(--canvas);
            border-radius: var(--radius-lg);
            border: 1px solid var(--hairline-soft);
            margin-bottom: var(--sp-sm);
            transition: box-shadow 150ms ease;
        }
        .script-card:hover {
            box-shadow: rgba(0,0,0,0.04) 0px 4px 12px 0px;
        }
        .script-header {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            margin-bottom: var(--sp-xs);
        }
        .script-header h4 {
            font-size: 16px;
            font-weight: 500;
            color: var(--ink);
            margin: 0;
            flex: 1;
            margin-right: var(--sp-md);
        }
        .script-time {
            font-size: 12px;
            color: var(--steel);
            white-space: nowrap;
        }
        .script-meta {
            display: flex;
            gap: var(--sp-md);
            margin-bottom: var(--sp-sm);
        }
        .script-stat {
            font-size: 13px;
            color: var(--stone);
        }
        .script-rate {
            font-size: 12px;
            font-weight: 600;
            padding: 2px 8px;
            border-radius: var(--radius-full);
        }
        .rate-good { background: #e6f4ea; color: #1e7e34; }
        .rate-mid { background: #fff3cd; color: #856404; }
        .rate-low { background: #f8d7da; color: #721c24; }
        .script-preview {
            margin-top: var(--sp-xs);
        }
        .script-preview summary {
            cursor: pointer;
            color: var(--primary);
            font-size: 14px;
            font-weight: 500;
        }
        .script-preview summary:hover {
            text-decoration: underline;
        }
        .script-preview pre {
            background: var(--surface-code);
            color: #d4d4d4;
            padding: var(--sp-md);
            border-radius: var(--radius-md);
            margin-top: var(--sp-xs);
            overflow-x: auto;
            font-family: var(--font-code);
            font-size: 13px;
            line-height: 1.50;
        }

        /* ── Empty State ── */
        .empty-state {
            text-align: center;
            padding: var(--sp-xxl);
            color: var(--stone);
            font-size: 14px;
        }

        /* ── Sunset Stripe Band (Signature) ── */
        .sunset-stripe {
            height: 6px;
            background: linear-gradient(90deg,
                var(--primary) 0%,
                var(--sunshine-700) 25%,
                var(--sunshine-500) 50%,
                var(--yellow-saturated) 75%,
                var(--cream) 100%
            );
            margin-top: var(--sp-section);
        }

        /* ── Footer ── */
        .footer {
            background: var(--footer-cream);
            padding: var(--sp-section) var(--sp-xxl);
            color: var(--steel);
            font-size: 13px;
            line-height: 1.40;
        }
        .footer-inner {
            max-width: 1280px;
            margin: 0 auto;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: var(--sp-md);
        }
        .footer-brand {
            font-weight: 600;
            color: var(--ink);
            font-size: 14px;
        }
        .footer-links {
            display: flex;
            gap: var(--sp-lg);
        }
        .footer-links a {
            color: var(--primary);
            text-decoration: none;
            font-size: 13px;
        }
        .footer-links a:hover {
            text-decoration: underline;
        }

        /* ── Responsive ── */
        @media (max-width: 1023px) {
            .hero-band h1 { font-size: 64px; }
            .hero-band { padding: var(--sp-section) var(--sp-xxl) var(--sp-xxxl); }
            .section-heading { font-size: 36px; }
        }
        @media (max-width: 767px) {
            .hero-band h1 { font-size: 52px; letter-spacing: -0.5px; }
            .hero-band .subtitle { font-size: 16px; }
            .topnav { padding: 0 var(--sp-md); }
            .container { padding: 0 var(--sp-md); }
            .card, .card-cream { padding: var(--sp-xl); }
            .options { gap: var(--sp-sm); }
            .input-row { flex-direction: column; }
            .footer-inner { flex-direction: column; text-align: center; }
        }
        @media (max-width: 479px) {
            .hero-band h1 { font-size: 40px; }
            .section-heading { font-size: 28px; }
            .skills-grid { grid-template-columns: 1fr; }
        }

        /* ── Setup Modal ── */
        .modal-overlay {
            display: none;
            position: fixed;
            inset: 0;
            z-index: 9999;
            background: rgba(0,0,0,0.45);
            backdrop-filter: blur(4px);
            align-items: center;
            justify-content: center;
        }
        .modal-overlay.active { display: flex; }
        .modal-box {
            background: var(--canvas);
            border-radius: var(--radius-lg);
            box-shadow: 0 24px 64px rgba(0,0,0,0.18);
            width: 440px;
            max-width: 92vw;
            padding: var(--sp-xxl) var(--sp-xxl) var(--sp-lg);
            animation: modalIn .2s ease-out;
        }
        @keyframes modalIn {
            from { opacity: 0; transform: translateY(16px) scale(0.97); }
            to   { opacity: 1; transform: translateY(0) scale(1); }
        }
        .modal-box h2 {
            font-family: var(--font-display);
            font-size: 22px;
            margin-bottom: var(--sp-xs);
        }
        .modal-box .modal-desc {
            font-size: 14px;
            color: var(--steel);
            margin-bottom: var(--sp-lg);
        }
        .modal-field {
            margin-bottom: var(--sp-md);
        }
        .modal-field label {
            display: block;
            font-size: 13px;
            font-weight: 500;
            color: var(--slate);
            margin-bottom: var(--sp-xxs);
        }
        .modal-field input, .modal-field select {
            width: 100%;
            padding: 10px 12px;
            font-size: 14px;
            border: 1px solid var(--hairline-strong);
            border-radius: var(--radius-sm);
            background: var(--surface);
            color: var(--ink);
            font-family: var(--font-body);
            transition: border-color .15s;
        }
        .modal-field input:focus, .modal-field select:focus {
            outline: none;
            border-color: var(--primary);
            box-shadow: 0 0 0 3px rgba(250,82,15,0.1);
        }
        .modal-field input::placeholder { color: var(--muted); }
        .modal-hint {
            font-size: 12px;
            color: var(--stone);
            margin-top: 2px;
        }
        .modal-actions {
            display: flex;
            gap: var(--sp-sm);
            margin-top: var(--sp-lg);
        }
        .modal-actions button {
            flex: 1;
            padding: 10px 0;
            font-size: 14px;
            font-weight: 500;
            border-radius: var(--radius-sm);
            cursor: pointer;
            border: none;
            transition: background .15s;
        }
        .btn-modal-primary {
            background: var(--primary);
            color: var(--on-primary);
        }
        .btn-modal-primary:hover { background: var(--primary-deep); }
        .btn-modal-primary:disabled { opacity: .5; cursor: not-allowed; }
        .btn-modal-ghost {
            background: transparent;
            color: var(--steel);
            border: 1px solid var(--hairline-strong) !important;
        }
        .btn-modal-ghost:hover { background: var(--surface); }
        .modal-error {
            font-size: 13px;
            color: #c5221f;
            margin-top: var(--sp-xs);
            display: none;
        }
        .provider-chips {
            display: flex;
            gap: var(--sp-xs);
            margin-bottom: var(--sp-md);
        }
        .provider-chip {
            flex: 1;
            padding: 12px;
            border: 2px solid var(--hairline);
            border-radius: var(--radius-md);
            cursor: pointer;
            text-align: center;
            transition: all .15s;
            background: var(--canvas);
        }
        .provider-chip:hover { border-color: var(--hairline-strong); }
        .provider-chip.selected {
            border-color: var(--primary);
            background: rgba(250,82,15,0.04);
        }
        .provider-chip .chip-name {
            font-weight: 600;
            font-size: 14px;
        }
        .provider-chip .chip-desc {
            font-size: 12px;
            color: var(--stone);
            margin-top: 2px;
        }
    </style>
</head>
<body>

    <!-- Top Navigation -->
    <nav class="topnav">
        <a class="topnav-brand" href="/">
            <span class="logo">A</span>
            Agentic Playwright
        </a>
        <div class="topnav-status" style="gap: var(--sp-md);">
            <div style="display:flex;align-items:center;gap:var(--sp-xs);cursor:pointer" onclick="openSetupModal()" title="点击配置 AI 模型">
                <span class="dot" id="llmDot"></span>
                <span id="llmStatusText" style="font-size:12px">检查中...</span>
            </div>
            <div style="display:flex;align-items:center;gap:var(--sp-xs)">
                <span class="dot" id="navDot"></span>
                <span id="navStatusText">就绪</span>
            </div>
        </div>
    </nav>

    <!-- Hero Band -->
    <div class="hero-band">
        <h1>Browser Automation.</h1>
        <p class="subtitle">AI 驱动的浏览器自动化框架 — 输入任务，Agent 自动执行</p>
    </div>

    <!-- Task Input Section -->
    <div class="container section">
        <p class="section-label">EXECUTE</p>
        <h2 class="section-heading">执行任务</h2>

        <div class="card-cream">
            <div class="input-row">
                <input class="text-input" type="text" id="taskInput" placeholder="输入任务描述，例如：帮我在百度搜索 Python 教程" />
                <button class="btn btn-dark" id="runBtn" onclick="runTask()">
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
                    最大步数
                    <input type="number" id="maxSteps" value="10" min="1" max="50" />
                </label>
                <label>
                    <input type="checkbox" id="keepOpen" checked />
                    保持浏览器开启
                </label>
            </div>
        </div>
    </div>

    <!-- Execution Results -->
    <div class="container" style="padding-bottom: var(--sp-section);">
        <p class="section-label">RESULT</p>
        <div class="card">
            <div class="card-title-row">
                <h2 class="card-title" style="margin-bottom:0;">
                    执行结果
                    <span class="status" id="status" style="display:none;margin-left:12px;"></span>
                </h2>
                <button class="btn btn-close-browser" id="closeBtn" onclick="closeBrowser()" style="display:none;">
                    关闭浏览器
                </button>
            </div>
            <div class="output" id="output">等待执行...</div>
            <div class="step info" id="authPrompt" style="display:none;margin-top:12px;">
                <strong id="authPromptTitle">Login detected</strong>
                <div id="authPromptText" style="margin:8px 0;"></div>
                <button class="btn btn-dark" id="authSaveBtn" type="button">Save login</button>
                <button class="btn btn-secondary" id="authDismissBtn" type="button">Not now</button>
            </div>
        </div>
    </div>

    <!-- Skills & Scripts -->
    <div class="container" style="padding-bottom: var(--sp-section);">
        <p class="section-label">LIBRARY</p>
        <h2 class="section-heading">技能库 & 脚本</h2>

        <div class="card">
            <div class="tabs">
                <button class="tab active" onclick="switchTab('skills', this)">技能库</button>
                <button class="tab" onclick="switchTab('scripts', this)">脚本历史</button>
            </div>

            <div class="tab-content active" id="tab-skills">
                <div class="view-switcher">
                    <button class="view-btn active" onclick="switchSkillView('platform', this)" data-view="platform">
                        <span class="view-icon">🌐</span> 按网站
                    </button>
                    <button class="view-btn" onclick="switchSkillView('action', this)" data-view="action">
                        <span class="view-icon">⚡</span> 按功能
                    </button>
                </div>
                <div class="skills-grid" id="skillsGrid">
                    <div class="empty-state">加载中...</div>
                </div>
            </div>

            <div class="tab-content" id="tab-scripts">
                <div id="scriptsList">
                    <div class="empty-state">加载中...</div>
                </div>
            </div>
        </div>
    </div>

    <!-- Sunset Stripe Band (Signature) -->
    <div class="sunset-stripe"></div>

    <!-- Footer -->
    <footer class="footer">
        <div class="footer-inner">
            <span class="footer-brand">Agentic Playwright MCP</span>
            <div class="footer-links">
                <a href="https://github.com/zceeeeee/agentic-playwright-mcp" target="_blank">GitHub</a>
                <a href="/api/status" target="_blank">API Status</a>
            </div>
        </div>
    </footer>

    <script>
        const promptedSaveDomains = new Map();
        let authPollTimer = null;
        let latestAuthPromptDomain = null;
        let taskRunning = false;

        function startAuthPolling() {
            if (authPollTimer) {
                clearInterval(authPollTimer);
            }
            // 首次检查延迟 5 秒，之后每 30 秒轮询一次（避免频繁弹窗和页面闪烁）
            setTimeout(() => {
                checkCurrentAuthState();
                authPollTimer = setInterval(checkCurrentAuthState, 30000);
            }, 5000);
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
                    if (taskRunning) {
                        return;
                    }
                    const closeBtn = document.getElementById('closeBtn');
                    if (closeBtn) closeBtn.style.display = 'none';
                    stopAuthPolling();
                    updateNavStatus(false);
                    return;
                }
                if (!result.domain || !result.has_session) {
                    return;
                }
                const promptState = result.has_auth ? 'has-auth' : 'no-auth';
                if (promptedSaveDomains.get(result.domain) === promptState) {
                    return;
                }
                promptedSaveDomains.set(result.domain, promptState);
                showAuthSavePrompt(result.domain, result.has_auth);
            } catch (error) {
                console.warn('Auth polling failed:', error);
            }
        }

        function showAuthSavePrompt(domain, hasAuth) {
            latestAuthPromptDomain = domain;
            const panel = document.getElementById('authPrompt');
            const title = document.getElementById('authPromptTitle');
            const text = document.getElementById('authPromptText');
            const saveBtn = document.getElementById('authSaveBtn');
            const dismissBtn = document.getElementById('authDismissBtn');
            const action = hasAuth ? 'update saved' : 'save';
            title.textContent = `Login detected: ${domain}`;
            text.textContent = `Detected an active ${domain} login. ${action} login info? This will not pause the running task.`;
            saveBtn.textContent = hasAuth ? 'Update login' : 'Save login';
            saveBtn.disabled = false;
            saveBtn.onclick = () => saveAuthFromPrompt(domain);
            dismissBtn.onclick = () => {
                panel.style.display = 'none';
            };
            panel.style.display = 'block';
        }

        async function saveAuthFromPrompt(domain) {
            const panel = document.getElementById('authPrompt');
            const text = document.getElementById('authPromptText');
            const saveBtn = document.getElementById('authSaveBtn');
            saveBtn.disabled = true;
            saveBtn.textContent = 'Saving...';
            try {
                const saveResponse = await fetch('/api/auth/save', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ domain }),
                });
                const saved = await saveResponse.json();
                if (saved.success) {
                    promptedSaveDomains.set(domain, 'has-auth');
                    text.textContent = `Saved login info for ${domain}.`;
                    setTimeout(() => {
                        if (latestAuthPromptDomain === domain) {
                            panel.style.display = 'none';
                        }
                    }, 1500);
                } else {
                    text.textContent = `Failed to save login info: ${saved.error || 'unknown error'}`;
                    saveBtn.disabled = false;
                    saveBtn.textContent = 'Retry save';
                }
            } catch (error) {
                text.textContent = `Failed to save login info: ${error.message}`;
                saveBtn.disabled = false;
                saveBtn.textContent = 'Retry save';
            }
        }

        function updateNavStatus(running) {
            const dot = document.getElementById('navDot');
            const text = document.getElementById('navStatusText');
            if (running) {
                dot.classList.add('active');
                text.textContent = '运行中';
            } else {
                dot.classList.remove('active');
                text.textContent = '就绪';
            }
        }

        async function runTask() {
            const task = document.getElementById('taskInput').value.trim();
            if (!task) {
                alert('请输入任务描述');
                return;
            }

            const runBtn = document.getElementById('runBtn');
            const status = document.getElementById('status');
            const output = document.getElementById('output');

            runBtn.disabled = true;
            runBtn.innerHTML = '<span class="spinner"></span> 执行中...';
            status.style.display = 'inline-flex';
            status.className = 'status running';
            status.textContent = '执行中';
            output.innerHTML = '';
            updateNavStatus(true);

            const keepOpen = document.getElementById('keepOpen').checked;
            const options = {
                task: task,
                headless: document.getElementById('headless').checked,
                use_cloak: document.getElementById('useCloak').checked,
                max_steps: parseInt(document.getElementById('maxSteps').value) || 10,
                keep_open: keepOpen,
            };

            let taskSuccess = false;
            promptedSaveDomains.clear();
            taskRunning = true;
            if (keepOpen) {
                startAuthPolling();
            }
            try {
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
                taskRunning = false;
                runBtn.disabled = false;
                runBtn.innerHTML = '执行';
                const closeBtn = document.getElementById('closeBtn');
                if (keepOpen && taskSuccess) {
                    closeBtn.style.display = 'inline-flex';
                } else {
                    closeBtn.style.display = 'none';
                    stopAuthPolling();
                    updateNavStatus(false);
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
                        html += `<br><span style="color:#c5221f">${step.error}</span>`;
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

            return html || '<div class="empty-state">无输出</div>';
        }

        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        async function closeBrowser() {
            const closeBtn = document.getElementById('closeBtn');
            closeBtn.disabled = true;
            closeBtn.innerHTML = '<span class="spinner spinner-dark" style="width:14px;height:14px;"></span> 关闭中...';
            try {
                await fetch('/api/close-browser', { method: 'POST' });
                closeBtn.style.display = 'none';
                const status = document.getElementById('status');
                status.className = 'status success';
                stopAuthPolling();
                status.textContent = '浏览器已关闭';
                updateNavStatus(false);
            } catch (error) {
                alert('关闭失败: ' + error.message);
            } finally {
                closeBtn.disabled = false;
                closeBtn.innerHTML = '关闭浏览器';
            }
        }

        function switchTab(name, el) {
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
            el.classList.add('active');
            document.getElementById(`tab-${name}`).classList.add('active');
        }

        // 平台名称映射
        const PLATFORM_NAMES = {
            "baidu": "百度",
            "google": "Google",
            "bing": "Bing",
            "github": "GitHub",
            "amazon": "Amazon",
            "youtube": "YouTube",
            "bilibili": "Bilibili",
            "weibo": "微博",
            "taobao": "淘宝",
            "doubao": "豆包",
            "csdn": "CSDN",
            "xiaohongshu": "小红书",
            "zhihu": "知乎",
            "gmail": "Gmail",
            "outlook": "Outlook",
        };

        // 操作类型中文映射
        const ACTION_NAMES = {
            "搜索": "搜索",
            "登录": "登录",
            "发送": "发送",
            "收件箱": "收件箱",
            "发布": "发布",
            "评论": "评论",
            "浏览": "浏览",
            "下载": "下载",
            "上传": "上传",
            "其他": "其他",
        };

        // 当前技能视图模式
        let currentSkillView = 'platform';
        let cachedSkills = null;

        function switchSkillView(view, el) {
            currentSkillView = view;
            document.querySelectorAll('.view-btn').forEach(b => b.classList.remove('active'));
            el.classList.add('active');
            if (cachedSkills) {
                renderSkills(cachedSkills);
            }
        }

        function renderSkills(skills) {
            const grid = document.getElementById('skillsGrid');
            if (skills.length === 0) {
                grid.innerHTML = '<div class="empty-state">暂无技能</div>';
                return;
            }

            if (currentSkillView === 'platform') {
                renderByPlatform(skills, grid);
            } else {
                renderByAction(skills, grid);
            }
        }

        // 点击 tag 填入任务描述
        function fillTask(platform, action) {
            const platformName = PLATFORM_NAMES[platform] || platform;
            let task = '';
            if (action === '搜索') {
                task = `在${platformName}搜索`;
            } else if (action === '登录') {
                task = `${platformName}登录`;
            } else if (action === '发送') {
                task = `用${platformName}发送`;
            } else if (action === '收件箱') {
                task = `打开${platformName}收件箱`;
            } else if (action === '发布') {
                task = `在${platformName}发布`;
            } else if (action === '评论') {
                task = `在${platformName}评论`;
            } else {
                task = `${platformName}${action}`;
            }
            const input = document.getElementById('taskInput');
            input.value = task;
            input.focus();
            // 滚动到页面顶部
            window.scrollTo({ top: 0, behavior: 'smooth' });
        }

        function renderByPlatform(skills, grid) {
            // 按 platform 分组，收集每个平台的所有功能
            const platforms = {};
            skills.forEach(skill => {
                const platform = skill.platform || 'other';
                if (!platforms[platform]) {
                    platforms[platform] = { actions: new Set(), count: 0 };
                }
                platforms[platform].actions.add(skill.action || '其他');
                platforms[platform].count++;
            });

            // 定义分组顺序（常用平台优先）
            const order = ['baidu', 'google', 'bing', 'github', 'bilibili', 'youtube', 'zhihu', 'xiaohongshu', 'weibo', 'taobao', 'amazon', 'gmail', 'outlook', 'csdn', 'doubao'];
            const sortedKeys = Object.keys(platforms).sort((a, b) => {
                const ia = order.indexOf(a);
                const ib = order.indexOf(b);
                return (ia === -1 ? 999 : ia) - (ib === -1 ? 999 : ib);
            });

            // 一个网站一张卡片
            grid.innerHTML = `
                <div class="platform-grid">
                    ${sortedKeys.map(platform => `
                        <div class="platform-card">
                            <h4 class="platform-name">${PLATFORM_NAMES[platform] || platform}</h4>
                            <div class="tags">
                                ${[...platforms[platform].actions].map(action =>
                                    `<span class="tag tag-clickable" onclick="fillTask('${platform}', '${escapeHtml(action)}')">${escapeHtml(action)}</span>`
                                ).join('')}
                            </div>
                        </div>
                    `).join('')}
                </div>
            `;
        }

        function renderByAction(skills, grid) {
            // 按 action 分组
            const groups = {};
            skills.forEach(skill => {
                const action = skill.action || '其他';
                if (!groups[action]) groups[action] = [];
                groups[action].push(skill);
            });

            // 定义分组顺序
            const order = ['搜索', '登录', '发送', '发布', '评论', '收件箱', '浏览', '下载', '上传', '其他'];
            const sortedKeys = Object.keys(groups).sort((a, b) => {
                const ia = order.indexOf(a);
                const ib = order.indexOf(b);
                return (ia === -1 ? 999 : ia) - (ib === -1 ? 999 : ib);
            });

            grid.innerHTML = sortedKeys.map(action => `
                <div class="skill-group">
                    <h3 class="skill-group-title">${ACTION_NAMES[action] || action}</h3>
                    <div class="skill-group-items">
                        ${groups[action].map(skill => `
                            <div class="skill-item">
                                <h4>${escapeHtml(skill.name)}</h4>
                                <p>${escapeHtml(skill.description || '')}</p>
                                <div class="tags">
                                    <span class="tag tag-platform">${PLATFORM_NAMES[skill.platform] || skill.platform || '其他'}</span>
                                </div>
                            </div>
                        `).join('')}
                    </div>
                </div>
            `).join('');
        }

        async function loadSkills() {
            try {
                const response = await fetch('/api/skills');
                cachedSkills = await response.json();
                renderSkills(cachedSkills);
            } catch (error) {
                document.getElementById('skillsGrid').innerHTML = `<div class="empty-state">加载失败: ${error.message}</div>`;
            }
        }

        async function loadScripts() {
            try {
                const response = await fetch('/api/scripts');
                const scripts = await response.json();
                const list = document.getElementById('scriptsList');
                if (scripts.length === 0) {
                    list.innerHTML = '<div class="empty-state">暂无脚本</div>';
                    return;
                }

                // 按最后使用时间排序（最近使用的在前）
                scripts.sort((a, b) => (b.last_used_at || b.created_at) - (a.last_used_at || a.created_at));

                list.innerHTML = scripts.map(script => {
                    const rateClass = script.success_rate >= 0.8 ? 'rate-good' : script.success_rate >= 0.5 ? 'rate-mid' : 'rate-low';
                    return `
                        <div class="script-card">
                            <div class="script-header">
                                <h4>${escapeHtml(script.task)}</h4>
                                <span class="script-time">${escapeHtml(script.last_used_at_fmt || script.created_at_fmt)}</span>
                            </div>
                            <div class="script-meta">
                                <span class="script-stat">使用 ${script.use_count} 次</span>
                                <span class="script-rate ${rateClass}">成功率 ${(script.success_rate * 100).toFixed(0)}%</span>
                            </div>
                            <details class="script-preview">
                                <summary>查看脚本</summary>
                                <pre>${escapeHtml(script.script)}</pre>
                            </details>
                        </div>
                    `;
                }).join('');
            } catch (error) {
                document.getElementById('scriptsList').innerHTML = `<div class="empty-state">加载失败: ${error.message}</div>`;
            }
        }

        document.getElementById('taskInput').addEventListener('keypress', (e) => {
            if (e.key === 'Enter') runTask();
        });

        loadSkills();
        loadScripts();
    </script>

    <!-- ── LLM Setup Modal ── -->
    <div class="modal-overlay" id="setupModal">
        <div class="modal-box">
            <h2>配置 AI 模型</h2>
            <p class="modal-desc">选择 Provider 并填入 API Key，用于自然语言任务的 LLM 兜底解析。</p>

            <div class="provider-chips">
                <div class="provider-chip selected" data-provider="openai" onclick="selectProvider('openai')">
                    <div class="chip-name">OpenAI</div>
                    <div class="chip-desc">GPT / 兼容 API</div>
                </div>
                <div class="provider-chip" data-provider="anthropic" onclick="selectProvider('anthropic')">
                    <div class="chip-name">Anthropic</div>
                    <div class="chip-desc">Claude 系列</div>
                </div>
            </div>

            <div class="modal-field">
                <label for="setupApiKey">API Key</label>
                <input type="password" id="setupApiKey" placeholder="sk-..." autocomplete="off">
            </div>

            <div class="modal-field">
                <label for="setupBaseUrl">Base URL</label>
                <input type="text" id="setupBaseUrl" placeholder="https://api.openai.com/v1">
                <div class="modal-hint" id="setupBaseUrlHint">可选，兼容 API 可改为其他地址</div>
            </div>

            <div class="modal-field">
                <label for="setupModel">Model</label>
                <input type="text" id="setupModel" placeholder="gpt-4o-mini">
            </div>

            <div class="modal-error" id="setupError"></div>

            <div class="modal-actions">
                <button class="btn-modal-ghost" onclick="closeSetupModal()">跳过</button>
                <button class="btn-modal-primary" id="setupSaveBtn" onclick="saveSetup()">保存并继续</button>
            </div>
        </div>
    </div>

    <script>
        /* ── Setup Modal Logic ── */
        const PROVIDER_DEFAULTS = {
            openai: {
                base_url: 'https://api.openai.com/v1',
                model: 'gpt-4o-mini',
                base_url_placeholder: 'https://api.openai.com/v1',
                base_url_hint: '兼容 API 可改为 DeepSeek、本地模型等地址',
            },
            anthropic: {
                base_url: 'https://api.anthropic.com',
                model: 'claude-haiku-4-5-20251001',
                base_url_placeholder: 'https://api.anthropic.com',
                base_url_hint: '通常无需修改',
            },
        };

        let selectedProvider = 'openai';

        function selectProvider(provider) {
            selectedProvider = provider;
            document.querySelectorAll('.provider-chip').forEach(el => {
                el.classList.toggle('selected', el.dataset.provider === provider);
            });
            const defaults = PROVIDER_DEFAULTS[provider];
            document.getElementById('setupBaseUrl').placeholder = defaults.base_url_placeholder;
            document.getElementById('setupBaseUrlHint').textContent = defaults.base_url_hint;
            document.getElementById('setupModel').placeholder = defaults.model;
            document.getElementById('setupError').style.display = 'none';
        }

        function openSetupModal() {
            document.getElementById('setupModal').classList.add('active');
            document.getElementById('setupApiKey').focus();
        }

        function closeSetupModal() {
            document.getElementById('setupModal').classList.remove('active');
        }

        async function saveSetup() {
            const btn = document.getElementById('setupSaveBtn');
            const errEl = document.getElementById('setupError');
            const apiKey = document.getElementById('setupApiKey').value.trim();

            if (!apiKey) {
                errEl.textContent = '请输入 API Key';
                errEl.style.display = 'block';
                return;
            }

            btn.disabled = true;
            btn.textContent = '保存中...';
            errEl.style.display = 'none';

            try {
                const resp = await fetch('/api/llm/setup', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        provider: selectedProvider,
                        api_key: apiKey,
                        base_url: document.getElementById('setupBaseUrl').value.trim(),
                        model: document.getElementById('setupModel').value.trim(),
                    }),
                });
                const result = await resp.json();

                if (result.success) {
                    closeSetupModal();
                    // 更新导航栏状态
                    updateLlmStatus(true, result.provider);
                } else {
                    errEl.textContent = result.error || '保存失败';
                    errEl.style.display = 'block';
                }
            } catch (e) {
                errEl.textContent = '请求失败: ' + e.message;
                errEl.style.display = 'block';
            } finally {
                btn.disabled = false;
                btn.textContent = '保存并继续';
            }
        }

        function updateLlmStatus(configured, provider) {
            const dot = document.getElementById('llmDot');
            const text = document.getElementById('llmStatusText');
            if (configured) {
                dot.classList.add('active');
                text.textContent = provider || '已配置';
            } else {
                dot.classList.remove('active');
                text.textContent = '未配置';
            }
        }

        async function checkLlmStatus() {
            try {
                const resp = await fetch('/api/llm/status');
                const result = await resp.json();
                updateLlmStatus(result.configured, result.provider);
                if (!result.configured) {
                    openSetupModal();
                }
            } catch (e) {
                console.warn('LLM status check failed:', e);
            }
        }

        // 页面加载后检查 LLM 配置状态
        document.addEventListener('DOMContentLoaded', checkLlmStatus);

        // 点击遮罩关闭
        document.getElementById('setupModal').addEventListener('click', (e) => {
            if (e.target === e.currentTarget) closeSetupModal();
        });
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
        auth_state = "unknown"
        has_session = False

        if bm._context is not None:
            state = bm._context.storage_state()
            auth_state = _storage_state_auth_state(state, domain)
            has_session = auth_state == "logged_in"

        am = get_auth_manager()
        return jsonify(
            {
                "browser_running": True,
                "url": current_url,
                "domain": domain,
                "auth_state": auth_state,
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
                    "platform": _extract_platform(s),
                    "action": _extract_action(s),
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
                    "created_at_fmt": _format_time(s.created_at),
                    "last_used_at_fmt": _format_time(s.last_used_at),
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


# ---------------------------------------------------------------------------
# LLM 配置 API
# ---------------------------------------------------------------------------


@app.route("/api/llm/status")
def api_llm_status():
    """检查 LLM 是否已配置。"""
    provider = os.getenv("LLM_PROVIDER", "openai").lower()
    has_openai = bool(os.getenv("OPENAI_API_KEY", "").strip())
    has_anthropic = bool(os.getenv("ANTHROPIC_API_KEY", "").strip())

    configured = has_openai or has_anthropic
    active_provider = "anthropic" if has_anthropic and provider == "anthropic" else "openai" if has_openai else ""

    return jsonify({
        "configured": configured,
        "provider": active_provider,
        "has_openai": has_openai,
        "has_anthropic": has_anthropic,
    })


@app.route("/api/llm/setup", methods=["POST"])
def api_llm_setup():
    """保存 LLM 配置到 .env 文件。"""
    data = request.json
    if not data:
        return jsonify({"success": False, "error": "No data provided"})

    provider = data.get("provider", "openai").lower()
    api_key = (data.get("api_key") or "").strip()
    base_url = (data.get("base_url") or "").strip()
    model = (data.get("model") or "").strip()

    if not api_key:
        return jsonify({"success": False, "error": "API Key 不能为空"})

    # 根据 provider 设置环境变量和默认值
    if provider == "anthropic":
        env_entries = {
            "LLM_PROVIDER": "anthropic",
            "ANTHROPIC_API_KEY": api_key,
            "ANTHROPIC_BASE_URL": base_url or "https://api.anthropic.com",
            "ANTHROPIC_MODEL": model or "claude-haiku-4-5-20251001",
        }
    else:
        env_entries = {
            "LLM_PROVIDER": "openai",
            "OPENAI_API_KEY": api_key,
            "OPENAI_BASE_URL": base_url or "https://api.openai.com/v1",
            "OPENAI_MODEL": model or "gpt-4o-mini",
        }

    # 应用到当前进程
    for key, value in env_entries.items():
        os.environ[key] = value

    # 追加写入 .env 文件
    env_file = _project_root / ".env"
    try:
        lines = ["", "# LLM config (auto-saved by web GUI)"]
        for key, value in env_entries.items():
            lines.append(f"{key}={value}")
        with open(env_file, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except Exception as exc:
        return jsonify({"success": False, "error": f"写入 .env 失败: {exc}"})

    return jsonify({"success": True, "provider": provider})


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

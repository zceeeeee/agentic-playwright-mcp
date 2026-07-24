"""
Agentic Playwright MCP Server -- main entry point.

Registers browser-automation tools via FastMCP and exposes them to MCP
clients (e.g. Claude Desktop).  All tools return synchronously using
Playwright's sync_api.

工具分为两类:
1. 脚本工具（新增）: browse_skills, get_skill, write_script, run_script, analyze_page
2. 基础工具（保留）: ping, browser_launch, screenshot
"""

from __future__ import annotations

import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from src.core.browser_manager import get_browser_manager
from src.core.script_engine import get_script_engine
from src.layer_2.controls import get_controls_exports
from src.logging import get_logger, log_mcp_tool, log_timing

# Module logger
logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# MCP Server instance
# ---------------------------------------------------------------------------

mcp = FastMCP(
    name="agentic-playwright-mcp",
)

# ---------------------------------------------------------------------------
# Project path constants
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DOMAINS_DIR = str(_PROJECT_ROOT / "domains")
_LIBRARY_DIR = str(_PROJECT_ROOT / "src" / "skill_library")


# ---------------------------------------------------------------------------
# 初始化脚本引擎（注入控件层函数）
# ---------------------------------------------------------------------------


def _init_script_engine():
    """初始化脚本引擎，注入控件层函数。"""
    engine = get_script_engine()
    engine.register_functions(get_controls_exports())
    return engine


# ---------------------------------------------------------------------------
# 基础工具（保留）
# ---------------------------------------------------------------------------


@mcp.tool()
def ping() -> str:
    """Health-check endpoint.  Returns 'pong'."""
    return "pong"


@mcp.tool()
def browser_launch() -> str:
    """Launch a Chromium browser and return its status.

    Uses the BrowserManager singleton.  If a browser is already running,
    returns an informational message instead of launching a second one.
    """
    bm = get_browser_manager()

    if bm.is_alive():
        logger.debug("Browser already running, skipping launch")
        return "Browser is already running."

    try:
        headless = os.getenv("BROWSER_HEADLESS", "false").lower() == "true"
        with log_timing("browser_launch", headless=headless) as meta:
            page = bm.launch(headless=headless)
            meta["engine"] = bm.engine
            meta["url"] = page.url
        log_mcp_tool("browser_launch", success=True, engine=bm.engine)
        return f"Browser launched successfully. Current page: {page.url}"
    except Exception as exc:
        log_mcp_tool("browser_launch", success=False, error=str(exc))
        return f"Browser launch failed: {exc}"


@mcp.tool()
def screenshot(path: str) -> str:
    """Capture a screenshot of the current page and save it.

    Args:
        path: File path for the screenshot (PNG), e.g. 'screenshots/home.png'.

    Returns:
        The save-result message.
    """
    bm = get_browser_manager()
    try:
        page = bm.get_page()
    except RuntimeError:
        return "Browser not launched. Call browser_launch first."

    try:
        from src.layer_1.actions import do_screenshot

        saved = do_screenshot(page, path)
        return f"Screenshot saved: {saved}"
    except Exception as exc:
        return f"Screenshot failed: {exc}"


# ---------------------------------------------------------------------------
# 脚本工具（新增）
# ---------------------------------------------------------------------------


@mcp.tool()
def browse_skills(query: str = "", url: str = "") -> str:
    """Browse the skill library and find matching skills.

    Search by keywords or URL pattern. Returns a list of matching skills
    with their IDs, names, types, and descriptions.

    Args:
        query: Search keywords (e.g. "百度 搜索", "登录", "分页").
        url: URL to match against skill URL patterns.

    Returns:
        Formatted list of matching skills.
    """
    from src.skill_library.registry import get_skill_registry

    registry = get_skill_registry(library_dir=_LIBRARY_DIR)

    if not query and not url:
        # 列出所有技能
        skills = registry.list_all()
    else:
        skills = registry.search(query=query or None, url=url or None)

    if not skills:
        return "No matching skills found."

    lines = ["Found skills:\n"]
    for skill in skills:
        lines.append(f"  [{skill.id}] {skill.name} ({skill.type})")
        lines.append(f"    {skill.description}")
        if skill.triggers:
            lines.append(f"    Keywords: {', '.join(skill.triggers)}")
        if skill.url_patterns:
            lines.append(f"    URL patterns: {', '.join(skill.url_patterns)}")
        lines.append("")

    return "\n".join(lines)


@mcp.tool()
def get_skill(skill_id: str) -> str:
    """Get the source code and guide for a specific skill.

    Args:
        skill_id: The skill ID (e.g. "domain/baidu_search", "interaction/login_flow").

    Returns:
        The skill's source code and optional guide document.
    """
    from src.skill_library.registry import get_skill_registry

    registry = get_skill_registry(library_dir=_LIBRARY_DIR)
    detail = registry.get_detail(skill_id)

    if detail is None:
        return f"Skill '{skill_id}' not found."

    parts = [f"=== Skill: {detail.meta.name} ==="]
    parts.append(f"Type: {detail.meta.type}")
    parts.append(f"Description: {detail.meta.description}")
    parts.append("")

    if detail.source_code:
        parts.append("--- Source Code ---")
        parts.append(detail.source_code)
        parts.append("")

    if detail.guide:
        parts.append("--- Guide ---")
        parts.append(detail.guide)

    return "\n".join(parts)


@mcp.tool()
def run_script(code: str) -> str:
    """Execute a Python script in the sandboxed environment.

    The script can use these built-in functions:
    - Navigation: goto(url), go_back(), go_forward(), reload()
    - Element ops: click(selector, ...), fill(selector, value, ...),
                  smart_click(element, domain), smart_fill(element, value, domain)
    - Composite: smart_login(domain, user, pass), smart_search(domain, keyword),
                 smart_fill_form(domain, {field: value})
    - Wait: wait_for_navigation(timeout), wait_for_element(selector, timeout), wait(sec)
    - Info: get_url(), get_title(), get_text(), screenshot(path)
    - Output: print(...), log(...)
    - Panel: panel_log(msg), panel_prompt(question), panel_read(),
             panel_read_events(), panel_show(), panel_hide(),
             panel_set_title(text), panel_set_fields(fields)

    Args:
        code: Python script source code to execute.

    Returns:
        Execution result with output, error info, and screenshot paths.
    """
    bm = get_browser_manager()
    if not bm.is_alive():
        logger.error("run_script called but browser not launched")
        return "Error: Browser not launched. Call browser_launch first."

    engine = _init_script_engine()

    with log_timing("script_execution") as meta:
        result = engine.execute(code)
        meta["success"] = result.success
        meta["has_output"] = bool(result.output)
        meta["has_error"] = bool(result.error)
        meta["screenshot_count"] = len(result.screenshots) if result.screenshots else 0

    log_mcp_tool("run_script", success=result.success)

    parts = []
    if result.success:
        parts.append("Script executed successfully.")
    else:
        parts.append("Script execution failed.")

    if result.output:
        parts.append(f"\nOutput:\n{result.output}")

    if result.error:
        parts.append(f"\nError:\n{result.error}")

    if result.screenshots:
        parts.append(f"\nScreenshots: {', '.join(result.screenshots)}")

    return "\n".join(parts)


@mcp.tool()
def analyze_page(question: str = "") -> str:
    """Take a screenshot and analyze the page with a multimodal LLM.

    Uses Claude Vision or GPT-4V to understand page content, identify
    interactive elements, and suggest next actions.

    Requires ANTHROPIC_API_KEY or OPENAI_API_KEY environment variable.

    Args:
        question: Optional specific question about the page
                  (e.g. "Where is the login button?").

    Returns:
        Page analysis with summary, elements, and suggested actions.
    """
    bm = get_browser_manager()
    if not bm.is_alive():
        return "Error: Browser not launched. Call browser_launch first."

    try:
        from src.core.vision import get_vision_module

        vision = get_vision_module()
    except ValueError as exc:
        return f"Vision module error: {exc}"
    except ImportError as exc:
        return f"Vision module error: {exc}"

    try:
        analysis = vision.analyze_page(question=question or None)
    except Exception as exc:
        return f"Page analysis failed: {exc}"

    parts = [f"Page Analysis:\n{analysis.summary}"]

    if analysis.elements:
        parts.append("\nInteractive Elements:")
        for i, elem in enumerate(analysis.elements, 1):
            parts.append(
                f"  {i}. {elem.description} "
                f"@ ({elem.x}, {elem.y}) "
                f"selector='{elem.suggested_selector}' "
                f"confidence={elem.confidence}"
            )

    if analysis.suggested_actions:
        parts.append("\nSuggested Actions:")
        for action in analysis.suggested_actions:
            parts.append(f"  - {action}")

    return "\n".join(parts)


@mcp.tool()
def run_task(task: str, max_steps: int = 20) -> str:
    """Execute a natural language task using the autonomous Agent loop.

    The Agent will automatically:
    1. Observe the current page (screenshot + analysis)
    2. Plan the next action (check skill library or generate script)
    3. Execute the script
    4. Repeat until task complete or max steps reached

    Failure recovery:
    - Script fails → self-healing (selector fallback)
    - All selectors fail → vision fallback (use coordinates)
    - Vision fallback fails → record experience, try other approach

    Args:
        task: Natural language task description,
              e.g. "帮我在百度搜索 Python 教程"
        max_steps: Maximum execution steps (default 10).

    Returns:
        Execution result with step-by-step progress and final output.
    """
    bm = get_browser_manager()
    if not bm.is_alive():
        return "Error: Browser not launched. Call browser_launch first."

    try:
        from src.core.agent_loop import run_task as _run_task

        result = _run_task(task, max_steps=max(max_steps, 20))
    except Exception as exc:
        return f"Agent loop error: {exc}"

    parts = []
    if result.success:
        parts.append(f"Task completed: {task}")
    else:
        parts.append(f"Task failed: {task}")

    if result.steps:
        parts.append("\nExecution steps:")
        for step in result.steps:
            status = "✓" if step.success else "✗"
            cost = ""
            if step.token_usage and step.token_usage.total_tokens > 0:
                cost = f" [{step.token_usage.total_tokens:,} tokens, {step.duration_ms:.0f}ms]"
            parts.append(
                f"  {status} Step {step.step_number} [{step.state}]: {step.result}{cost}"
            )

    if result.output:
        parts.append(f"\nOutput:\n{result.output}")

    if result.final_url:
        parts.append(f"\nFinal URL: {result.final_url}")

    if result.error:
        parts.append(f"\nError: {result.error}")

    # 消耗摘要
    cost_summary = result.format_cost_summary()
    if cost_summary:
        parts.append(f"\nCost: {cost_summary}")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# 认证管理工具
# ---------------------------------------------------------------------------


@mcp.tool()
def auth_list() -> str:
    """List all domains and their authentication status.

    Scans the domains/ directory and shows which sites have saved cookies.

    Returns:
        Formatted list of domains with auth status.
    """
    from src.core.auth_manager import get_auth_manager

    am = get_auth_manager()
    domains = am.list_domains()
    if not domains:
        return "No domains found in domains/ directory."

    lines = ["Domain authentication status:"]
    for d in domains:
        icon = "✓" if d["has_auth"] else "✗"
        lines.append(f"  {icon} {d['domain']}")
    return "\n".join(lines)


@mcp.tool()
def auth_save(domain: str) -> str:
    """Save current browser cookies for a domain.

    Saves the current browser context's storage_state (cookies, localStorage)
    to ~/.agentic-playwright/auth/{domain}.json.

    Args:
        domain: Domain name (matching domains/{domain}.yaml).

    Returns:
        Save result message.
    """
    bm = get_browser_manager()
    if not bm.is_alive():
        return "Error: Browser not launched. Call browser_launch first."

    if bm._context is None:
        return "Error: No active browser context."

    from src.core.auth_manager import get_auth_manager

    am = get_auth_manager()
    path = am.save_auth(domain, bm._context)
    return f"Auth saved for '{domain}': {path}"


@mcp.tool()
def auth_delete(domain: str) -> str:
    """Delete saved cookies for a domain.

    Args:
        domain: Domain name.

    Returns:
        Delete result message.
    """
    from src.core.auth_manager import get_auth_manager

    am = get_auth_manager()
    if am.delete_auth(domain):
        return f"Auth deleted for '{domain}'."
    return f"No auth found for '{domain}'."


@mcp.tool()
def browser_launch_with_domain(domain: str) -> str:
    """Launch browser with saved cookies for a domain.

    If the browser is already running, creates a new context with the
    domain's saved auth. If no saved auth exists, launches normally.

    Args:
        domain: Domain name (matching domains/{domain}.yaml).

    Returns:
        Launch result message.
    """
    bm = get_browser_manager()

    try:
        page = bm.launch_with_domain(domain=domain)
        from src.core.auth_manager import get_auth_manager

        has = (
            "with saved auth"
            if get_auth_manager().has_auth(domain)
            else "no saved auth"
        )
        return f"Browser ready for '{domain}' ({has}). Current page: {page.url}"
    except Exception as exc:
        return f"Launch failed: {exc}"


# ---------------------------------------------------------------------------
# 面板交互工具
# ---------------------------------------------------------------------------


@mcp.tool()
def panel_toggle(visible: bool) -> str:
    """Compatibility toggle for the desktop interaction surface.

    Args:
        visible: True to show the panel, False to hide it.

    Returns:
        Confirmation message.
    """
    try:
        from src.panel import get_panel_manager

        pm = get_panel_manager()
        pm.toggle(None, visible)
        return f"Desktop interaction surface {'enabled' if visible else 'unchanged'}."
    except Exception as exc:
        return f"Panel toggle failed: {exc}"


@mcp.tool()
def panel_read() -> str:
    """Read user input data and events from the interactive panel.

    Returns the latest data submitted by the user through the panel
    form, and flushes the event queue (button clicks, form submissions).

    Returns:
        JSON string with 'data' (latest input) and 'events' (queue).
    """
    try:
        import json

        from src.panel import get_panel_manager

        pm = get_panel_manager()
        data = pm.read_data(None)
        events = pm.read_events(None)
        return json.dumps({"data": data, "events": events}, ensure_ascii=False, indent=2)
    except Exception as exc:
        return f"Panel read failed: {exc}"


@mcp.tool()
def panel_log(message: str) -> str:
    """Write a message to the panel's log area.

    The log is displayed in the panel and helps the user track
    what the automation is doing.

    Args:
        message: Log message to display.

    Returns:
        Confirmation message.
    """
    try:
        from src.panel import get_panel_manager

        pm = get_panel_manager()
        pm.log(None, message)
        return "Log written to desktop interaction stream."
    except Exception as exc:
        return f"Panel log failed: {exc}"


@mcp.tool()
def panel_set_title(text: str) -> str:
    """Set the title of the interactive panel.

    Args:
        text: New title text.

    Returns:
        Confirmation message.
    """
    try:
        from src.panel import get_panel_manager

        pm = get_panel_manager()
        pm.set_title(None, text)
        return f"Desktop prompt title set to: {text}"
    except Exception as exc:
        return f"Panel set_title failed: {exc}"


@mcp.tool()
def panel_prompt(question: str) -> str:
    """Ask the user through the desktop chat and wait for an answer.

    This is a blocking call — it waits until the user responds.

    Args:
        question: Question to display to the user.

    Returns:
        The user's answer as a string.
    """
    try:
        from src.panel import get_panel_manager

        pm = get_panel_manager()
        answer = pm.prompt(None, question)
        return f"User answered: {answer}"
    except Exception as exc:
        return f"Panel prompt failed: {exc}"


@mcp.tool()
def panel_set_fields(fields_json: str) -> str:
    """Dynamically update the panel's form fields.

    Replace the current form with new fields. Each field is an object
    with: name, label, type (text/password/textarea/select),
    placeholder, and optionally options (for select).

    Args:
        fields_json: JSON array of field definitions, e.g.
            '[{"name": "username", "label": "用户名", "type": "text", "placeholder": "输入用户名"}]'

    Returns:
        Confirmation message.
    """
    try:
        import json

        from src.panel import get_panel_manager

        fields = json.loads(fields_json)
        pm = get_panel_manager()
        pm.set_fields(None, fields)
        return f"Desktop prompt fields updated: {len(fields)} fields configured."
    except json.JSONDecodeError as exc:
        return f"Invalid JSON: {exc}"
    except Exception as exc:
        return f"Panel set_fields failed: {exc}"


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


def main() -> None:
    """Start the MCP stdio transport.

    Note: The canonical entry point is now ``agentic-playwright-mcp serve``
    via src.cli.  This function is kept for backward compatibility with
    ``python -m src.server``.
    """
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()

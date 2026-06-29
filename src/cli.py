"""
CLI entry point for agentic-playwright-mcp.

Subcommands:
    serve   -- Start the MCP server (stdio / sse / streamable-http)
    run     -- Execute a one-shot natural-language task and exit
    doctor  -- Diagnose environment health
"""

from __future__ import annotations

import importlib.metadata
import os
import platform
import subprocess
import sys
from pathlib import Path

import click

# ---------------------------------------------------------------------------
# Project paths
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DOMAINS_DIR = _PROJECT_ROOT / "domains"
_LIBRARY_DIR = _PROJECT_ROOT / "src" / "skill_library"
_ENV_FILE = _PROJECT_ROOT / ".env"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _version() -> str:
    """Return package version from metadata or pyproject.toml."""
    try:
        return importlib.metadata.version("agentic-playwright-mcp")
    except importlib.metadata.PackageNotFoundError:
        return "0.1.0 (dev)"


def _get_package_version(distribution_name: str) -> str:
    """Return installed version of a distribution, or '?' if unknown."""
    try:
        return importlib.metadata.version(distribution_name)
    except importlib.metadata.PackageNotFoundError:
        return "?"


def _append_env_file(api_key: str, base_url: str, model: str) -> None:
    """将 LLM 配置追加写入 .env 文件。"""
    lines = [
        "",
        "# LLM Fallback (auto-saved by gui command)",
        f"OPENAI_API_KEY={api_key}",
        f"OPENAI_BASE_URL={base_url}",
        f"OPENAI_MODEL={model}",
    ]
    with open(_ENV_FILE, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def _check_mark(ok: bool) -> str:
    return "[OK]" if ok else "[FAIL]"


def _warn_mark(ok: bool) -> str:
    return "[OK]" if ok else "[WARN]"


def _load_config() -> None:
    """加载配置文件，首次运行时引导配置。"""
    from src.config_manager import get_config_manager

    config = get_config_manager()

    if not config.is_configured():
        click.echo("首次运行，需要配置 API Key。")
        config.setup_interactive()

    # 应用配置到环境变量
    config.apply_to_env()

    # 加载 .env（优先级更高，可覆盖 config.yaml）
    if _ENV_FILE.is_file():
        from dotenv import load_dotenv

        load_dotenv(_ENV_FILE, override=False)


# ---------------------------------------------------------------------------
# CLI root
# ---------------------------------------------------------------------------


@click.group()
@click.version_option(version=_version(), prog_name="agentic-playwright-mcp")
def main() -> None:
    """Agentic Playwright MCP -- browser automation for LLM agents."""


# ---------------------------------------------------------------------------
# serve
# ---------------------------------------------------------------------------


@main.command()
@click.option(
    "--transport",
    type=click.Choice(["stdio", "sse", "streamable-http"]),
    default="stdio",
    show_default=True,
    help="MCP transport layer.",
)
@click.option(
    "--host",
    default="localhost",
    show_default=True,
    help="Host for SSE / streamable-http transport.",
)
@click.option(
    "--port",
    default=8000,
    type=int,
    show_default=True,
    help="Port for SSE / streamable-http transport.",
)
@click.option(
    "--debug",
    is_flag=True,
    default=False,
    help="Enable verbose logging.",
)
def serve(transport: str, host: str, port: int, debug: bool) -> None:
    """Start the MCP server.

    By default uses stdio transport (for Claude Desktop / CLI integration).
    Use --transport sse or --transport streamable-http for network modes.
    """
    # Load config
    _load_config()

    if debug:
        os.environ["LOG_LEVEL"] = "DEBUG"

    # Configure structured logging
    from src.logging import configure_logging_from_env

    configure_logging_from_env()

    # Suppress color codes on stdio (avoids garbled output in MCP clients)
    if transport == "stdio":
        os.environ.setdefault("NO_COLOR", "1")

    from src.server import mcp

    if transport == "stdio":
        mcp.run(transport="stdio")
    else:
        mcp.run(transport=transport, host=host, port=port)


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------


@main.command()
@click.argument("task")
@click.option(
    "--max-steps",
    default=10,
    type=int,
    show_default=True,
    help="Maximum agent-loop steps.",
)
@click.option(
    "--headless/--headed",
    default=True,
    show_default=True,
    help="Run browser in headless or headed mode.",
)
@click.option(
    "--slow-mo",
    default=0,
    type=int,
    show_default=True,
    help="Slow-down between actions (ms). Useful for headed debugging.",
)
@click.option(
    "--keep-open",
    is_flag=True,
    default=False,
    help="Keep the browser open until Enter is pressed.",
)
def run(
    task: str, max_steps: int, headless: bool, slow_mo: int, keep_open: bool
) -> None:
    """Execute a natural-language TASK and print the result.

    Launches a browser, runs the agent loop, prints output, and exits.
    This is a one-shot command -- not an interactive REPL.

    Examples:

        agentic-playwright-mcp run "open https://example.com and take a screenshot"

        agentic-playwright-mcp run --headed --slow-mo 500 "search Python docs on baidu"
    """
    # Load config
    _load_config()

    from src.core.browser_manager import get_browser_manager

    bm = get_browser_manager()

    try:
        bm.launch(headless=headless, slow_mo=slow_mo)
    except Exception as exc:
        click.secho(f"Failed to launch browser: {exc}", fg="red", err=True)
        sys.exit(1)

    click.echo(f"Browser launched ({bm.engine}). Running task...")
    click.echo(f"  Task: {task}")
    click.echo(f"  Max steps: {max_steps}")
    click.echo()

    try:
        from src.core.agent_loop import run_task

        result = run_task(task, max_steps=max_steps)

        # Print step-by-step progress
        for step in result.steps:
            status = (
                click.style("OK", fg="green")
                if step.success
                else click.style("FAIL", fg="red")
            )
            click.echo(
                f"  Step {step.step_number} [{step.state}] {status}: {step.result}"
            )

        click.echo()

        if result.success:
            click.secho("Task completed.", fg="green")
        else:
            click.secho("Task failed.", fg="red")

        if result.output:
            click.echo(f"\nOutput:\n{result.output}")

        if result.final_url:
            click.echo(f"\nFinal URL: {result.final_url}")

        if result.error:
            click.secho(f"\nError: {result.error}", fg="red")
            sys.exit(1)

    except Exception as exc:
        click.secho(f"Agent loop error: {exc}", fg="red", err=True)
        sys.exit(1)
    finally:
        if keep_open:
            click.echo()
            click.echo("Browser kept open. Press Enter here to close it.")
            input()
        bm.close()


# ---------------------------------------------------------------------------
# doctor
# ---------------------------------------------------------------------------


@main.command()
@click.option(
    "--fix",
    is_flag=True,
    default=False,
    help="Attempt to fix detected issues (e.g. install playwright browsers).",
)
def doctor(fix: bool) -> None:
    """Diagnose environment health and report issues.

    Checks Python version, dependencies, Playwright browsers, .env config,
    domain YAML files, and the skill library. Exits 0 when all critical
    checks pass, 1 otherwise.
    """
    errors: list[str] = []
    warnings: list[str] = []
    passed: list[str] = []

    click.echo("agentic-playwright-mcp doctor")
    click.echo("=" * 40)

    # ------------------------------------------------------------------
    # 1. Python version
    # ------------------------------------------------------------------
    click.echo("\n[1/7] Python version")
    major, minor = sys.version_info[:2]
    py_ok = (major, minor) >= (3, 11)
    click.echo(f"  Python {major}.{minor} {_check_mark(py_ok)}")
    if py_ok:
        passed.append("Python version")
    else:
        errors.append(f"Python >= 3.11 required, found {major}.{minor}")

    # ------------------------------------------------------------------
    # 2. Core dependencies
    # ------------------------------------------------------------------
    click.echo("\n[2/7] Core dependencies")
    core_deps = [
        ("playwright", "playwright"),
        ("mcp", "mcp"),
        ("pydantic", "pydantic"),
        ("pyyaml", "yaml"),
        ("python-dotenv", "dotenv"),
        ("httpx", "httpx"),
        ("click", "click"),
    ]
    all_deps_ok = True
    for pip_name, import_name in core_deps:
        try:
            importlib.import_module(import_name)
            ver = _get_package_version(pip_name)
            click.echo(f"  {pip_name} ({ver}) {_check_mark(True)}")
        except ImportError:
            click.echo(f"  {pip_name} {_check_mark(False)}")
            errors.append(f"Missing dependency: {pip_name}")
            all_deps_ok = False
    if all_deps_ok:
        passed.append("Core dependencies")

    # ------------------------------------------------------------------
    # 3. Playwright browsers
    # ------------------------------------------------------------------
    click.echo("\n[3/7] Playwright browsers")
    pw_ok = _check_playwright_browsers()
    click.echo(f"  Chromium installed {_check_mark(pw_ok)}")
    if pw_ok:
        passed.append("Playwright browsers")
    else:
        msg = "Playwright browsers not installed. Run: python -m playwright install chromium"
        errors.append(msg)
        if fix:
            click.echo("  -> Attempting fix: python -m playwright install chromium")
            try:
                subprocess.run(
                    [sys.executable, "-m", "playwright", "install", "chromium"],
                    check=True,
                    capture_output=True,
                )
                click.echo("  -> Chromium installed successfully.")
                errors.remove(msg)
                passed.append("Playwright browsers")
            except subprocess.CalledProcessError as exc:
                click.echo(f"  -> Install failed: {exc}")

    # ------------------------------------------------------------------
    # 4. .env file
    # ------------------------------------------------------------------
    click.echo("\n[4/7] Environment file (.env)")
    if _ENV_FILE.is_file():
        click.echo(f"  {_ENV_FILE} {_check_mark(True)}")
        passed.append(".env exists")

        # Check for at least one API key (needed for vision)
        has_anthropic = bool(os.getenv("ANTHROPIC_API_KEY", "").strip())
        has_openai = bool(os.getenv("OPENAI_API_KEY", "").strip())
        if has_anthropic or has_openai:
            key_name = "ANTHROPIC_API_KEY" if has_anthropic else "OPENAI_API_KEY"
            click.echo(f"  {key_name} {_check_mark(True)}")
            passed.append("Vision API key")
        else:
            warnings.append(
                "No ANTHROPIC_API_KEY or OPENAI_API_KEY set. "
                "Vision features (analyze_page, run_task) will not work."
            )
    else:
        warnings.append(
            f".env file not found at {_ENV_FILE}. "
            "Copy .env.example to .env and fill in your keys."
        )

    # ------------------------------------------------------------------
    # 5. Domains directory
    # ------------------------------------------------------------------
    click.echo("\n[5/7] Domain configs (domains/)")
    if _DOMAINS_DIR.is_dir():
        yaml_files = list(_DOMAINS_DIR.glob("*.yaml")) + list(
            _DOMAINS_DIR.glob("*.yml")
        )
        count = len(yaml_files)
        dom_ok = count > 0
        click.echo(f"  Directory: {_DOMAINS_DIR} {_check_mark(True)}")
        click.echo(f"  YAML files found: {count} {_warn_mark(dom_ok)}")
        if dom_ok:
            for yf in yaml_files[:5]:
                click.echo(f"    - {yf.name}")
            passed.append("Domain configs")
        else:
            warnings.append(
                "No domain YAML files found in domains/. The system will work but without site-specific selectors."
            )
    else:
        warnings.append("domains/ directory not found.")

    # ------------------------------------------------------------------
    # 6. Skill library
    # ------------------------------------------------------------------
    click.echo("\n[6/7] Skill library")
    if _LIBRARY_DIR.is_dir():
        skills_yaml = _LIBRARY_DIR / "skills.yaml"
        skill_files = list(_LIBRARY_DIR.glob("**/*.py"))
        skill_count = len(skill_files)

        click.echo(f"  Directory: {_LIBRARY_DIR} {_check_mark(True)}")
        click.echo(f"  Python files: {skill_count}")

        if skills_yaml.is_file():
            click.echo(f"  skills.yaml {_check_mark(True)}")
            passed.append("Skill library")
        else:
            warnings.append(
                "skills.yaml not found in skill library. Skills will not be indexed."
            )
    else:
        warnings.append("Skill library directory not found.")

    # ------------------------------------------------------------------
    # 7. Optional: CloakBrowser
    # ------------------------------------------------------------------
    click.echo("\n[7/7] Optional: CloakBrowser (stealth)")
    use_cloak = os.getenv("USE_CLOAKBROWSER", "true").strip().lower() == "true"
    if use_cloak:
        try:
            import cloakbrowser  # noqa: F401

            click.echo(f"  CloakBrowser enabled and installed {_check_mark(True)}")
            passed.append("CloakBrowser")
        except ImportError:
            msg = "USE_CLOAKBROWSER=true but cloakbrowser not installed. Run: pip install agentic-playwright-mcp[stealth]"
            errors.append(msg)
            click.echo(f"  {_check_mark(False)}")
    else:
        click.echo("  Not enabled (default Playwright engine)")

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    click.echo("\n" + "=" * 40)
    click.echo("Summary")
    click.echo("=" * 40)

    if passed:
        click.secho(f"  Passed:   {len(passed)}", fg="green")
    if warnings:
        for w in warnings:
            click.secho(f"  Warning:  {w}", fg="yellow")
    if errors:
        for e in errors:
            click.secho(f"  Error:    {e}", fg="red")

    if not errors:
        click.secho("\nAll critical checks passed. Ready to go!", fg="green")
        sys.exit(0)
    else:
        click.secho(
            f"\n{len(errors)} critical issue(s) found. Fix them before running.",
            fg="red",
        )
        sys.exit(1)


def _check_playwright_browsers() -> bool:
    """Return True if Chromium is installed for Playwright."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "--dry-run"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        # If the command succeeds and output contains "chromium" in installed list
        output = result.stdout + result.stderr
        if "chromium" in output.lower():
            return True
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    # Fallback: check the default browser path
    pw_data = Path.home() / ".cache" / "ms-playwright"
    if platform.system() == "Windows":
        pw_data = Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"

    if pw_data.is_dir():
        chromium_dirs = list(pw_data.glob("chromium-*"))
        return len(chromium_dirs) > 0

    return False


# ---------------------------------------------------------------------------
# setup
# ---------------------------------------------------------------------------


@main.command()
def setup() -> None:
    """Interactive setup wizard for first-time configuration.

    Prompts for API key, browser engine, and other settings.
    Saves to ~/.agentic-playwright/config.yaml.
    """
    from src.config_manager import get_config_manager, reset_config_manager

    reset_config_manager()
    config = get_config_manager()
    config.setup_interactive()


# ---------------------------------------------------------------------------
# gui
# ---------------------------------------------------------------------------


@main.command()
@click.option(
    "--host",
    default="127.0.0.1",
    show_default=True,
    help="Host to bind the GUI server.",
)
@click.option(
    "--port",
    default=8080,
    type=int,
    show_default=True,
    help="Port to bind the GUI server.",
)
@click.option(
    "--debug",
    is_flag=True,
    default=False,
    help="Enable debug mode.",
)
def gui(host: str, port: int, debug: bool) -> None:
    """Launch the web GUI for browser automation.

    Opens a web interface where you can:
    - Enter natural-language tasks and watch them execute
    - Browse the skill library
    - View script history

    Examples:

        agentic-playwright-mcp gui

        agentic-playwright-mcp gui --port 9090 --debug
    """
    # Load .env
    if _ENV_FILE.is_file():
        from dotenv import load_dotenv

        load_dotenv(_ENV_FILE, override=False)

    # --- LLM 配置检查：缺少 API Key 时交互式引导 ---
    if not os.getenv("OPENAI_API_KEY", "").strip():
        click.secho("⚙  未检测到 OPENAI_API_KEY，LLM 兜底功能需要配置。", fg="yellow")
        click.echo("   （直接回车跳过，将使用纯规则模式）\n")

        api_key = click.prompt(
            "  OPENAI_API_KEY", default="", show_default=False
        ).strip()
        if api_key:
            base_url = click.prompt(
                "  OPENAI_BASE_URL", default="https://api.openai.com/v1"
            ).strip()
            model = click.prompt("  OPENAI_MODEL", default="gpt-4o-mini").strip()

            os.environ["OPENAI_API_KEY"] = api_key
            os.environ["OPENAI_BASE_URL"] = base_url
            os.environ["OPENAI_MODEL"] = model

            # 追加写入 .env 方便下次使用
            _append_env_file(api_key, base_url, model)
            click.secho("  ✓ 配置已保存到 .env\n", fg="green")
        else:
            click.secho("  → 跳过，将以纯规则模式运行\n", fg="yellow")

    try:
        from src.gui.app import app
    except ImportError:
        click.secho(
            "GUI dependencies not installed. Run: pip install flask",
            fg="red",
            err=True,
        )
        sys.exit(1)

    click.echo(f"Starting GUI at http://{host}:{port}")
    click.echo("Press Ctrl+C to stop")

    app.run(host=host, port=port, debug=debug, threaded=False)


if __name__ == "__main__":
    main()

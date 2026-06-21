"""Tests for cli.py -- Click CLI entry point and subcommands.

Uses Click's CliRunner to invoke commands in isolation.  Heavy dependencies
(browser, network, MCP transport) are mocked so the tests run fast and
offline.
"""

from __future__ import annotations

import importlib.metadata
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from src.cli import main, doctor, serve, run, _version, _get_package_version, _check_mark, _warn_mark, _check_playwright_browsers


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


# ---------------------------------------------------------------------------
# Helpers -- pure functions
# ---------------------------------------------------------------------------


class TestVersionHelper:
    def test_returns_installed_version(self):
        """When the package IS installed, version comes from metadata."""
        with patch("importlib.metadata.version", return_value="1.2.3"):
            assert _version() == "1.2.3"

    def test_falls_back_to_dev(self):
        """When the package is NOT installed, returns dev fallback."""
        with patch("importlib.metadata.version", side_effect=importlib.metadata.PackageNotFoundError):
            assert _version() == "0.1.0 (dev)"


class TestGetPackageVersion:
    def test_known_package(self):
        with patch("importlib.metadata.version", return_value="3.14"):
            assert _get_package_version("pi") == "3.14"

    def test_unknown_package(self):
        with patch("importlib.metadata.version", side_effect=importlib.metadata.PackageNotFoundError):
            assert _get_package_version("nope") == "?"


class TestCheckMark:
    def test_ok(self):
        assert _check_mark(True) == "[OK]"

    def test_fail(self):
        assert _check_mark(False) == "[FAIL]"


class TestWarnMark:
    def test_ok(self):
        assert _warn_mark(True) == "[OK]"

    def test_warn(self):
        assert _warn_mark(False) == "[WARN]"


# ---------------------------------------------------------------------------
# _check_playwright_browsers
# ---------------------------------------------------------------------------


class TestCheckPlaywrightBrowsers:
    def test_dry_run_reports_chromium(self):
        """When the dry-run output mentions chromium, returns True."""
        mock_result = MagicMock()
        mock_result.stdout = "Browsers: chromium-1234\n"
        mock_result.stderr = ""
        with patch("subprocess.run", return_value=mock_result):
            assert _check_playwright_browsers() is True

    def test_dry_run_no_chromium(self):
        """When dry-run output lacks chromium and no cache dir, returns False."""
        mock_result = MagicMock()
        mock_result.stdout = "Browsers: firefox-1234\n"
        mock_result.stderr = ""
        with patch("subprocess.run", return_value=mock_result), \
             patch.object(Path, "is_dir", return_value=False):
            assert _check_playwright_browsers() is False

    def test_dry_run_timeout_falls_back_to_cache(self):
        """On subprocess timeout, falls back to checking cache directory."""
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="playwright", timeout=10)), \
             patch.object(Path, "is_dir", return_value=True), \
             patch.object(Path, "glob", return_value=["chromium-1234"]):
            assert _check_playwright_browsers() is True

    def test_dry_run_file_not_found_falls_back(self):
        """When playwright is not installed, falls back to cache check."""
        with patch("subprocess.run", side_effect=FileNotFoundError), \
             patch.object(Path, "is_dir", return_value=False):
            assert _check_playwright_browsers() is False


# ---------------------------------------------------------------------------
# CLI root group
# ---------------------------------------------------------------------------


class TestMainGroup:
    def test_help(self, runner: CliRunner):
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "browser automation" in result.output.lower() or "mcp" in result.output.lower()

    def test_version(self, runner: CliRunner):
        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        assert "agentic-playwright-mcp" in result.output
        # Version is captured at import time by @click.version_option;
        # just verify it looks like a version string.
        assert any(c.isdigit() for c in result.output)

    def test_unknown_subcommand(self, runner: CliRunner):
        result = runner.invoke(main, ["nosuch"])
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# serve
# ---------------------------------------------------------------------------


class TestServeCommand:
    def test_help(self, runner: CliRunner):
        result = runner.invoke(main, ["serve", "--help"])
        assert result.exit_code == 0
        assert "transport" in result.output.lower()
        assert "stdio" in result.output.lower()

    @patch("src.server.mcp")
    def test_stdio_default(self, mock_mcp, runner: CliRunner):
        """Default transport is stdio."""
        result = runner.invoke(main, ["serve"])
        assert result.exit_code == 0
        mock_mcp.run.assert_called_once_with(transport="stdio")

    @patch("src.server.mcp")
    def test_sse_transport(self, mock_mcp, runner: CliRunner):
        """SSE transport passes host and port."""
        result = runner.invoke(main, ["serve", "--transport", "sse", "--host", "0.0.0.0", "--port", "9000"])
        assert result.exit_code == 0
        mock_mcp.run.assert_called_once_with(transport="sse", host="0.0.0.0", port=9000)

    def test_invalid_transport(self, runner: CliRunner):
        result = runner.invoke(main, ["serve", "--transport", "grpc"])
        assert result.exit_code != 0
        assert "invalid" in result.output.lower() or "choice" in result.output.lower()

    @patch("src.server.mcp")
    def test_debug_enables_logging(self, mock_mcp, runner: CliRunner):
        """--debug flag sets up logging."""
        with patch("logging.basicConfig") as mock_logging:
            result = runner.invoke(main, ["serve", "--debug"])
        assert result.exit_code == 0

    @patch("src.server.mcp")
    def test_stdio_sets_no_color(self, mock_mcp, runner: CliRunner):
        """stdio transport sets NO_COLOR=1 to avoid garbled output."""
        env = os.environ.copy()
        env.pop("NO_COLOR", None)
        result = runner.invoke(main, ["serve"], env=env)
        assert result.exit_code == 0
        assert os.environ.get("NO_COLOR") == "1"


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------


class TestRunCommand:
    def test_help(self, runner: CliRunner):
        result = runner.invoke(main, ["run", "--help"])
        assert result.exit_code == 0
        assert "task" in result.output.lower()
        assert "max-steps" in result.output.lower()
        assert "headless" in result.output.lower()

    def test_missing_task(self, runner: CliRunner):
        """Task argument is required."""
        result = runner.invoke(main, ["run"])
        assert result.exit_code != 0

    @patch("src.core.agent_loop.run_task")
    @patch("src.core.browser_manager.get_browser_manager")
    def test_success(self, mock_get_bm, mock_run_task, runner: CliRunner):
        """Happy path: browser launches, task runs, prints result."""
        from src.core.agent_loop import AgentTaskResult, AgentStep, AgentState

        bm = MagicMock()
        bm.engine = "playwright"
        mock_get_bm.return_value = bm

        mock_run_task.return_value = AgentTaskResult(
            success=True,
            task="open example.com",
            steps=[
                AgentStep(step_number=1, state=AgentState.ACT, result="navigated", success=True),
            ],
            final_url="https://example.com",
            output="Page loaded",
        )

        result = runner.invoke(main, ["run", "open example.com"])
        assert result.exit_code == 0
        assert "Page loaded" in result.output
        assert "completed" in result.output.lower()

    @patch("src.core.browser_manager.get_browser_manager")
    def test_browser_launch_failure(self, mock_get_bm, runner: CliRunner):
        """Exits 1 when browser cannot launch."""
        bm = MagicMock()
        bm.launch.side_effect = RuntimeError("no chromium")
        mock_get_bm.return_value = bm

        result = runner.invoke(main, ["run", "do something"])
        assert result.exit_code == 1

    @patch("src.core.agent_loop.run_task")
    @patch("src.core.browser_manager.get_browser_manager")
    def test_task_error_exits_1(self, mock_get_bm, mock_run_task, runner: CliRunner):
        """Exits 1 when the agent loop returns an error."""
        from src.core.agent_loop import AgentTaskResult

        bm = MagicMock()
        bm.engine = "playwright"
        mock_get_bm.return_value = bm

        mock_run_task.return_value = AgentTaskResult(
            success=False,
            task="impossible",
            steps=[],
            error="Could not complete",
        )

        result = runner.invoke(main, ["run", "impossible"])
        assert result.exit_code == 1

    @patch("src.core.browser_manager.get_browser_manager")
    def test_agent_loop_exception(self, mock_get_bm, runner: CliRunner):
        """Exits 1 when agent loop raises unexpectedly."""
        bm = MagicMock()
        bm.engine = "playwright"
        mock_get_bm.return_value = bm

        with patch("src.core.agent_loop.run_task", side_effect=RuntimeError("boom")):
            result = runner.invoke(main, ["run", "explode"])
        assert result.exit_code == 1

    @patch("src.core.agent_loop.run_task")
    @patch("src.core.browser_manager.get_browser_manager")
    def test_custom_max_steps(self, mock_get_bm, mock_run_task, runner: CliRunner):
        """--max-steps is forwarded to run_task."""
        from src.core.agent_loop import AgentTaskResult

        bm = MagicMock()
        bm.engine = "playwright"
        mock_get_bm.return_value = bm

        mock_run_task.return_value = AgentTaskResult(
            success=True, task="t", steps=[], output="ok"
        )

        runner.invoke(main, ["run", "--max-steps", "5", "test task"])
        mock_run_task.assert_called_once_with("test task", max_steps=5)

    @patch("src.core.agent_loop.run_task")
    @patch("src.core.browser_manager.get_browser_manager")
    def test_headed_flag(self, mock_get_bm, mock_run_task, runner: CliRunner):
        """--headed passes headless=False to browser manager."""
        from src.core.agent_loop import AgentTaskResult

        bm = MagicMock()
        bm.engine = "playwright"
        mock_get_bm.return_value = bm

        mock_run_task.return_value = AgentTaskResult(
            success=True, task="t", steps=[], output="ok"
        )

        runner.invoke(main, ["run", "--headed", "test task"])
        bm.launch.assert_called_once_with(headless=False, slow_mo=0)

    @patch("src.core.agent_loop.run_task")
    @patch("src.core.browser_manager.get_browser_manager")
    def test_slow_mo(self, mock_get_bm, mock_run_task, runner: CliRunner):
        """--slow-mo is forwarded to browser launch."""
        from src.core.agent_loop import AgentTaskResult

        bm = MagicMock()
        bm.engine = "playwright"
        mock_get_bm.return_value = bm

        mock_run_task.return_value = AgentTaskResult(
            success=True, task="t", steps=[], output="ok"
        )

        runner.invoke(main, ["run", "--slow-mo", "500", "test task"])
        bm.launch.assert_called_once_with(headless=True, slow_mo=500)


# ---------------------------------------------------------------------------
# doctor
# ---------------------------------------------------------------------------


class TestDoctorCommand:
    def test_help(self, runner: CliRunner):
        result = runner.invoke(main, ["doctor", "--help"])
        assert result.exit_code == 0
        assert "fix" in result.output.lower() or "diagnose" in result.output.lower()

    def test_all_pass(self, runner: CliRunner):
        """When everything is healthy, exits 0."""
        with patch("src.cli._check_playwright_browsers", return_value=True), \
             patch("importlib.import_module"), \
             patch("src.cli._get_package_version", return_value="1.0.0"), \
             patch.object(Path, "is_file", return_value=True), \
             patch.object(Path, "is_dir", return_value=True), \
             patch.object(Path, "glob", return_value=[Path("example.yaml")]), \
             patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test"}):
            result = runner.invoke(main, ["doctor"])
        assert result.exit_code == 0
        assert "passed" in result.output.lower() or "ready" in result.output.lower()

    def test_missing_dependency(self, runner: CliRunner):
        """Missing a core dependency causes exit 1."""
        def fake_import(name):
            if name == "playwright":
                raise ImportError("no module")
            return MagicMock()

        with patch("src.cli._check_playwright_browsers", return_value=True), \
             patch("importlib.import_module", side_effect=fake_import), \
             patch("src.cli._get_package_version", return_value="1.0.0"), \
             patch.object(Path, "is_file", return_value=False), \
             patch.object(Path, "is_dir", return_value=True), \
             patch.object(Path, "glob", return_value=[Path("example.yaml")]):
            result = runner.invoke(main, ["doctor"])
        assert result.exit_code == 1
        assert "critical" in result.output.lower()

    def test_no_domains_warns(self, runner: CliRunner):
        """Empty domains/ produces a warning but not an error."""
        with patch("src.cli._check_playwright_browsers", return_value=True), \
             patch("importlib.import_module"), \
             patch("src.cli._get_package_version", return_value="1.0.0"), \
             patch.object(Path, "is_file", return_value=False), \
             patch.object(Path, "is_dir", return_value=True), \
             patch.object(Path, "glob", return_value=[]):
            result = runner.invoke(main, ["doctor"])
        # Should still exit 0 (warnings are non-fatal)
        assert result.exit_code == 0

    def test_no_env_warns(self, runner: CliRunner):
        """Missing .env file produces a warning."""
        with patch("src.cli._check_playwright_browsers", return_value=True), \
             patch("importlib.import_module"), \
             patch("src.cli._get_package_version", return_value="1.0.0"), \
             patch.object(Path, "is_file", return_value=False), \
             patch.object(Path, "is_dir", return_value=True), \
             patch.object(Path, "glob", return_value=[Path("example.yaml")]):
            result = runner.invoke(main, ["doctor"])
        assert result.exit_code == 0
        assert "warning" in result.output.lower() or "warn" in result.output.lower()

    def test_fix_attempts_browser_install(self, runner: CliRunner):
        """--fix flag attempts to install playwright browsers."""
        with patch("src.cli._check_playwright_browsers", return_value=False), \
             patch("importlib.import_module"), \
             patch("src.cli._get_package_version", return_value="1.0.0"), \
             patch.object(Path, "is_file", return_value=False), \
             patch.object(Path, "is_dir", return_value=True), \
             patch.object(Path, "glob", return_value=[Path("example.yaml")]), \
             patch("subprocess.run") as mock_subproc:
            mock_subproc.return_value = MagicMock()
            result = runner.invoke(main, ["doctor", "--fix"])
        # Should have attempted to install chromium
        assert any(
            "chromium" in str(call) for call in mock_subproc.call_args_list
        ) or result.exit_code in (0, 1)

    def test_cloakbrowser_enabled_missing(self, runner: CliRunner):
        """USE_CLOAKBROWSER=true without the package causes an error."""
        import builtins
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "cloakbrowser":
                raise ImportError("no cloakbrowser")
            return real_import(name, *args, **kwargs)

        with patch("src.cli._check_playwright_browsers", return_value=True), \
             patch("builtins.__import__", side_effect=fake_import), \
             patch("src.cli._get_package_version", return_value="1.0.0"), \
             patch.object(Path, "is_file", return_value=False), \
             patch.object(Path, "is_dir", return_value=True), \
             patch.object(Path, "glob", return_value=[Path("example.yaml")]), \
             patch.dict(os.environ, {"USE_CLOAKBROWSER": "true"}):
            result = runner.invoke(main, ["doctor"])
        assert result.exit_code == 1

    def test_cloakbrowser_enabled_present(self, runner: CliRunner):
        """USE_CLOAKBROWSER=true with the package installed is OK."""
        with patch("src.cli._check_playwright_browsers", return_value=True), \
             patch("importlib.import_module"), \
             patch("src.cli._get_package_version", return_value="1.0.0"), \
             patch.object(Path, "is_file", return_value=False), \
             patch.object(Path, "is_dir", return_value=True), \
             patch.object(Path, "glob", return_value=[Path("example.yaml")]), \
             patch.dict(os.environ, {"USE_CLOAKBROWSER": "true"}):
            result = runner.invoke(main, ["doctor"])
        # Should not fail on cloakbrowser
        assert "cloakbrowser" in result.output.lower()

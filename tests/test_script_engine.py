"""Tests for core.script_engine — sandboxed script execution."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.core.login_guard import GenericLoginGuard
from src.core.script_engine import (
    ScriptEngine,
    ScriptResult,
    get_script_engine,
    reset_script_engine,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def engine():
    """Create a fresh ScriptEngine for each test."""
    return ScriptEngine()


@pytest.fixture
def mock_browser():
    """Mock get_browser_manager so script primitives don't touch real browser."""
    with patch("src.core.script_engine.get_browser_manager") as mock_get_bm:
        bm = MagicMock()
        page = MagicMock()
        page.url = "https://example.com"
        page.title.return_value = "Example"
        bm.get_page.return_value = page
        mock_get_bm.return_value = bm
        yield bm, page


# ---------------------------------------------------------------------------
# ScriptResult
# ---------------------------------------------------------------------------


class TestScriptResult:
    def test_success_result(self):
        r = ScriptResult(success=True, output="hello")
        assert r.success is True
        assert r.output == "hello"
        assert r.error is None
        assert r.screenshots == []

    def test_failure_result(self):
        r = ScriptResult(success=False, error="boom")
        assert r.success is False
        assert r.error == "boom"


# ---------------------------------------------------------------------------
# Basic execution
# ---------------------------------------------------------------------------


class TestBasicExecution:
    """Test basic script execution in sandbox."""

    def test_simple_expression(self, engine):
        """Should execute simple Python and capture nothing."""
        result = engine.execute("x = 1 + 2")
        assert result.success is True
        assert result.error is None

    def test_print_capture(self, engine):
        """Should capture print output."""
        result = engine.execute("print('hello world')")
        assert result.success is True
        assert "hello world" in result.output

    def test_multiple_prints(self, engine):
        """Should capture multiple print calls."""
        result = engine.execute("print('a')\nprint('b')")
        assert result.success is True
        assert "a" in result.output
        assert "b" in result.output

    def test_variable_persistence_within_script(self, engine):
        """Variables should persist within a single script execution."""
        result = engine.execute("x = 42\nprint(x)")
        assert result.success is True
        assert "42" in result.output

    def test_syntax_error(self, engine):
        """Should catch syntax errors gracefully."""
        result = engine.execute("def (invalid")
        assert result.success is False
        assert result.error is not None
        assert "SyntaxError" in result.error

    def test_runtime_error(self, engine):
        """Should catch runtime errors gracefully."""
        result = engine.execute("x = 1 / 0")
        assert result.success is False
        assert result.error is not None
        assert "ZeroDivisionError" in result.error

    def test_name_error(self, engine):
        """Should catch NameError for undefined variables."""
        result = engine.execute("print(undefined_var)")
        assert result.success is False
        assert "NameError" in result.error


# ---------------------------------------------------------------------------
# Sandbox restrictions
# ---------------------------------------------------------------------------


class TestSandboxRestrictions:
    """Test that dangerous operations are blocked."""

    def test_import_blocked(self, engine):
        """Should block import statements."""
        result = engine.execute("import os")
        assert result.success is False
        assert "ImportError" in result.error or "ModuleNotFoundError" in result.error

    def test_open_blocked(self, engine):
        """Should block file open() — not in builtins."""
        result = engine.execute("f = open('/etc/passwd')")
        assert result.success is False

    def test_os_blocked(self, engine):
        """Should block os module access."""
        result = engine.execute("os.system('echo hacked')")
        assert result.success is False

    def test_subprocess_blocked(self, engine):
        """Should block subprocess access."""
        result = engine.execute("import subprocess")
        assert result.success is False

    def test_eval_blocked(self, engine):
        """Should block eval() — not in safe builtins."""
        result = engine.execute("eval('1+1')")
        assert result.success is False

    def test_exec_blocked(self, engine):
        """Should block nested exec() — not in safe builtins."""
        result = engine.execute("exec('print(1)')")
        assert result.success is False

    def test_safe_builtins_available(self, engine):
        """Should have safe builtins like len, str, int."""
        result = engine.execute("x = len([1,2,3])\nprint(x)")
        assert result.success is True
        assert "3" in result.output

    def test_safe_string_ops(self, engine):
        """Should allow string operations."""
        result = engine.execute("x = 'hello'.upper()\nprint(x)")
        assert result.success is True
        assert "HELLO" in result.output


# ---------------------------------------------------------------------------
# Browser primitives injection
# ---------------------------------------------------------------------------


class TestBrowserPrimitives:
    """Test that browser primitives are available in scripts."""

    def test_goto_available(self, engine, mock_browser):
        """Should have goto() function available."""
        result = engine.execute("goto('https://example.com')")
        assert result.success is True
        bm, page = mock_browser
        page.goto.assert_called_once()

    def test_click_available(self, engine, mock_browser):
        """Should have click() function available."""
        bm, page = mock_browser
        page.is_visible.return_value = True
        result = engine.execute("click('#btn')")
        assert result.success is True

    def test_fill_available(self, engine, mock_browser):
        """Should have fill() function available."""
        bm, page = mock_browser
        page.is_visible.return_value = True
        result = engine.execute("fill('#input', 'hello')")
        assert result.success is True

    def test_screenshot_available(self, engine, mock_browser):
        """Should have screenshot() function and collect paths."""
        result = engine.execute("screenshot('test.png')")
        assert result.success is True
        assert "test.png" in result.screenshots

    def test_get_url_available(self, engine, mock_browser):
        """Should have get_url() function."""
        result = engine.execute("print(get_url())")
        assert result.success is True
        assert "https://example.com" in result.output

    def test_get_title_available(self, engine, mock_browser):
        """Should have get_title() function."""
        result = engine.execute("print(get_title())")
        assert result.success is True
        assert "Example" in result.output

    def test_uses_injected_browser_manager(self):
        """Should support the legacy ScriptEngine(browser_manager) call style."""
        bm = MagicMock()
        page = MagicMock()
        page.url = "https://injected.example"
        bm.get_page.return_value = page

        engine = ScriptEngine(bm)
        result = engine.execute("print(get_url())")

        assert result.success is True
        assert "https://injected.example" in result.output
        bm.get_page.assert_called_once()

    def test_generic_login_popup_waits_for_cookie_before_continuing(self):
        """Generic browser actions should pause when a login modal appears."""

        class FakeContext:
            def __init__(self):
                self.logged_in = False

            def storage_state(self):
                if not self.logged_in:
                    return {"cookies": [], "origins": []}
                return {
                    "cookies": [
                        {
                            "name": "session",
                            "value": "abc123",
                            "domain": "example.com",
                        }
                    ],
                    "origins": [],
                }

        class FakePage:
            def __init__(self, context):
                self.context = context
                self.url = "https://example.com"
                self.login_required = False
                self.waits = 0

            def evaluate(self, code):
                if "GENERIC_LOGIN_PROMPT_DETECTOR" in code:
                    return {
                        "success": True,
                        "login_required": self.login_required,
                        "url": self.url,
                    }
                return None

            def wait_for_timeout(self, milliseconds):
                self.waits += 1
                self.login_required = False
                self.context.logged_in = True

        class FakeBrowserManager:
            def __init__(self):
                self._context = FakeContext()
                self.page = FakePage(self._context)
                self.current_domain = None
                self.saved_domains = []

            def get_page(self):
                return self.page

            def save_auth(self, domain=None):
                self.saved_domains.append(domain)
                return True

        bm = FakeBrowserManager()
        engine = ScriptEngine(bm)

        def fake_goto(url):
            bm.page.url = url
            bm.page.login_required = True
            return "ok"

        engine.register_function("goto", fake_goto)
        result = engine.execute("goto('https://example.com/protected')\nprint('after login')")

        assert result.success is True
        assert "after login" in result.output
        assert "Detected login popup" in result.output
        assert bm.page.waits == 1
        assert bm.saved_domains == ["example"]

    def test_explicit_login_script_skips_generic_login_wait(self):
        """Scripts with their own login flow should not be intercepted."""

        bm = MagicMock()
        page = MagicMock()
        page.url = "https://example.com"
        page.evaluate.return_value = {
            "success": True,
            "login_required": True,
            "url": page.url,
        }
        bm.get_page.return_value = page
        bm._context.storage_state.return_value = {"cookies": [], "origins": []}
        bm.current_domain = None

        engine = ScriptEngine(bm)
        engine.register_function("goto", lambda url: "ok")
        result = engine.execute(
            "PHONE_LOGIN_TEXT = '手机号登录'\n"
            "goto('https://example.com/login')\n"
            "print('login flow continues')"
        )

        assert result.success is True
        assert "login flow continues" in result.output
        page.wait_for_timeout.assert_not_called()

    def test_generic_login_guard_reports_closed_page_cleanly(self):
        class FakeContext:
            def storage_state(self):
                return {"cookies": [], "origins": []}

        class FakePage:
            url = "https://example.com"
            context = FakeContext()

            def __init__(self):
                self.closed = False

            def evaluate(self, code):
                if "GENERIC_LOGIN_PROMPT_DETECTOR" in code:
                    return {
                        "success": True,
                        "login_required": True,
                        "url": self.url,
                    }
                return None

            def wait_for_timeout(self, _milliseconds):
                self.closed = True
                raise RuntimeError("TargetClosedError: page closed")

            def is_closed(self):
                return self.closed

        page = FakePage()
        guard = GenericLoginGuard(lambda: page)

        with pytest.raises(RuntimeError, match="Page closed while waiting"):
            guard.maybe_wait("after_goto")


# ---------------------------------------------------------------------------
# Custom function registration
# ---------------------------------------------------------------------------


class TestCustomFunctions:
    """Test registering custom functions (controls layer)."""

    def test_register_single_function(self, engine):
        """Should allow registering a custom function."""
        engine.register_function("my_func", lambda x: x * 2)
        result = engine.execute("print(my_func(5))")
        assert result.success is True
        assert "10" in result.output

    def test_register_multiple_functions(self, engine):
        """Should allow batch registering functions."""
        engine.register_functions(
            {
                "add": lambda a, b: a + b,
                "multiply": lambda a, b: a * b,
            }
        )
        result = engine.execute("print(add(2, 3))\nprint(multiply(4, 5))")
        assert result.success is True
        assert "5" in result.output
        assert "20" in result.output

    def test_custom_function_cannot_access_outer_scope(self, engine):
        """Custom functions run in their own closure, not script namespace."""
        secret = "hidden"
        engine.register_function("get_secret", lambda: secret)
        result = engine.execute("print(get_secret())")
        assert result.success is True
        assert "hidden" in result.output

    def test_log_function(self, engine):
        """Should have log() function that writes to output."""
        result = engine.execute("log('starting task')")
        assert result.success is True
        assert "[LOG] starting task" in result.output


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


class TestSingleton:
    def teardown_method(self):
        reset_script_engine()

    def test_singleton(self):
        e1 = get_script_engine()
        e2 = get_script_engine()
        assert e1 is e2

    def test_reset(self):
        e1 = get_script_engine()
        reset_script_engine()
        e2 = get_script_engine()
        assert e1 is not e2


# ---------------------------------------------------------------------------
# Complex scripts
# ---------------------------------------------------------------------------


class TestComplexScripts:
    """Test realistic multi-line scripts."""

    def test_conditional_logic(self, engine, mock_browser):
        """Should support if/else in scripts."""
        script = """
url = get_url()
if 'example' in url:
    print('found example')
else:
    print('other site')
"""
        result = engine.execute(script)
        assert result.success is True
        assert "found example" in result.output

    def test_loop(self, engine):
        """Should support loops."""
        script = """
for i in range(3):
    print(f'iteration {i}')
"""
        result = engine.execute(script)
        assert result.success is True
        assert "iteration 0" in result.output
        assert "iteration 2" in result.output

    def test_function_definition(self, engine, mock_browser):
        """Should support defining functions within script."""
        script = """
def greet(name):
    return f'Hello, {name}!'

print(greet('World'))
"""
        result = engine.execute(script)
        assert result.success is True
        assert "Hello, World!" in result.output

    def test_try_except(self, engine):
        """Should support try/except."""
        script = """
try:
    x = 1 / 0
except Exception as e:
    print(f'caught: {e}')
"""
        result = engine.execute(script)
        assert result.success is True
        assert "caught" in result.output

    def test_multi_step_workflow(self, engine, mock_browser):
        """Should support a realistic multi-step workflow."""
        script = """
log('Starting workflow')
goto('https://example.com')
url = get_url()
log(f'Current URL: {url}')
screenshot('step1.png')
log('Workflow complete')
"""
        result = engine.execute(script)
        assert result.success is True
        assert "Starting workflow" in result.output
        assert "Workflow complete" in result.output
        assert "step1.png" in result.screenshots

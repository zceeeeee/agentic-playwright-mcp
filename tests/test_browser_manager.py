"""Tests for core.browser_manager — dual-engine browser lifecycle."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from src.core.browser_manager import (
    BrowserManager,
    _get_engine_type,
    _is_cloak_enabled,
    get_browser_manager,
    reset_browser_manager,
)

# ---------------------------------------------------------------------------
# _is_cloak_enabled
# ---------------------------------------------------------------------------


class TestIsCloakEnabled:
    """Tests for the _is_cloak_enabled helper."""

    def test_default_true(self):
        """Should return True when USE_CLOAKBROWSER is not set (default)."""
        with patch.dict("os.environ", {}, clear=False):
            os.environ.pop("USE_CLOAKBROWSER", None)
            assert _is_cloak_enabled() is True

    @pytest.mark.parametrize(
        "value, expected",
        [
            ("true", True),
            ("True", True),
            ("TRUE", True),
            (" true ", True),
            ("false", False),
            ("False", False),
            ("0", False),
            ("no", False),
            ("", False),
        ],
    )
    def test_env_values(self, value, expected):
        """Should parse various env string values correctly."""
        with patch.dict("os.environ", {"USE_CLOAKBROWSER": value}):
            assert _is_cloak_enabled() is expected


class TestEngineType:
    def test_explicit_engine_takes_precedence(self):
        with patch.dict(
            "os.environ",
            {"BROWSER_ENGINE": "local_chrome", "USE_CLOAKBROWSER": "true"},
        ):
            assert _get_engine_type() == "local_chrome"

    def test_legacy_toggle_remains_supported(self):
        with patch.dict("os.environ", {"USE_CLOAKBROWSER": "false"}):
            os.environ.pop("BROWSER_ENGINE", None)
            assert _get_engine_type() == "playwright"


# ---------------------------------------------------------------------------
# BrowserManager — Playwright engine (default)
# ---------------------------------------------------------------------------


class TestBrowserManagerPlaywright:
    """Tests for BrowserManager with Playwright engine."""

    def setup_method(self):
        reset_browser_manager()

    def teardown_method(self):
        reset_browser_manager()

    @patch.dict("os.environ", {"USE_CLOAKBROWSER": "false"})
    @patch("src.core.browser_manager.sync_playwright")
    def test_launch_playwright(self, mock_pw):
        """Should launch via Playwright when explicitly set."""
        # sync_playwright() returns context, .start() returns the actual pw instance
        mock_context = MagicMock()
        mock_pw.return_value = mock_context
        mock_pw_instance = MagicMock()
        mock_context.start.return_value = mock_pw_instance
        mock_browser = MagicMock()
        mock_page = MagicMock()
        mock_pw_instance.chromium.launch.return_value = mock_browser
        mock_browser.new_context.return_value.new_page.return_value = mock_page

        bm = BrowserManager()
        page = bm.launch(headless=True)

        assert page is mock_page
        assert bm.engine == "playwright"
        mock_pw_instance.chromium.launch.assert_called_once_with(
            headless=True, slow_mo=500
        )

    def test_get_page_before_launch(self):
        """Should raise RuntimeError if get_page called before launch."""
        bm = BrowserManager()
        with pytest.raises(RuntimeError, match="尚未启动"):
            bm.get_page()

    def test_start_clean_context_discards_existing_login_state(self):
        bm = BrowserManager()
        old_context = MagicMock()
        clean_context = MagicMock()
        clean_page = MagicMock()
        clean_context.new_page.return_value = clean_page
        browser = MagicMock()
        browser.is_connected.return_value = True
        browser.new_context.return_value = clean_context
        bm._browser = browser
        bm._context = old_context
        bm._current_domain = "zhihu"

        assert bm.start_clean_context() is clean_page
        browser.new_context.assert_called_once_with()
        old_context.close.assert_called_once_with()
        assert bm._context is clean_context
        assert bm.current_domain is None

    @patch.dict("os.environ", {"USE_CLOAKBROWSER": "false"})
    @patch("src.core.browser_manager.sync_playwright")
    def test_close(self, mock_pw):
        """Should close browser and stop playwright."""
        mock_context = MagicMock()
        mock_pw.return_value = mock_context
        mock_pw_instance = MagicMock()
        mock_context.start.return_value = mock_pw_instance
        mock_browser = MagicMock()
        mock_pw_instance.chromium.launch.return_value = mock_browser
        mock_browser.new_context.return_value.new_page.return_value = MagicMock()

        bm = BrowserManager()
        bm.launch(headless=True)
        bm.close()

        mock_browser.close.assert_called_once()
        mock_pw_instance.stop.assert_called_once()

    @patch.dict("os.environ", {"USE_CLOAKBROWSER": "false"})
    @patch("src.core.browser_manager.sync_playwright")
    def test_is_alive(self, mock_pw):
        """Should report alive after launch, dead after close."""
        mock_context = MagicMock()
        mock_pw.return_value = mock_context
        mock_pw_instance = MagicMock()
        mock_context.start.return_value = mock_pw_instance
        mock_browser = MagicMock()
        mock_pw_instance.chromium.launch.return_value = mock_browser
        mock_browser.new_page.return_value = MagicMock()

        bm = BrowserManager()
        assert bm.is_alive() is False

        bm.launch(headless=True)
        assert bm.is_alive() is True

        bm.close()
        assert bm.is_alive() is False


# ---------------------------------------------------------------------------
# BrowserManager — CloakBrowser engine
# ---------------------------------------------------------------------------


class TestBrowserManagerCloak:
    """Tests for BrowserManager with CloakBrowser engine."""

    def setup_method(self):
        reset_browser_manager()

    def teardown_method(self):
        reset_browser_manager()

    @patch.dict("os.environ", {"USE_CLOAKBROWSER": "true"})
    @patch("src.core.browser_manager._import_cloakbrowser")
    def test_launch_cloakbrowser(self, mock_import):
        """Should launch via CloakBrowser when enabled."""
        mock_cloak = MagicMock()
        mock_import.return_value = mock_cloak
        mock_browser = MagicMock()
        mock_page = MagicMock()
        mock_cloak.launch.return_value = mock_browser
        mock_browser.new_context.return_value.new_page.return_value = mock_page

        bm = BrowserManager()
        page = bm.launch(headless=False, humanize=True)

        assert page is mock_page
        assert bm.engine == "cloakbrowser"
        mock_cloak.launch.assert_called_once_with(headless=False, humanize=True)

    @patch.dict("os.environ", {"USE_CLOAKBROWSER": "true"})
    @patch("src.core.browser_manager._import_cloakbrowser")
    def test_launch_cloakbrowser_with_proxy(self, mock_import):
        """Should pass proxy to CloakBrowser."""
        mock_cloak = MagicMock()
        mock_import.return_value = mock_cloak
        mock_browser = MagicMock()
        mock_cloak.launch.return_value = mock_browser
        mock_browser.new_context.return_value.new_page.return_value = MagicMock()

        bm = BrowserManager()
        bm.launch(proxy="http://user:pass@host:port")

        mock_cloak.launch.assert_called_once_with(
            headless=False,
            proxy="http://user:pass@host:port",
        )

    @patch.dict("os.environ", {"USE_CLOAKBROWSER": "true"})
    @patch("src.core.browser_manager._import_cloakbrowser")
    def test_launch_cloakbrowser_not_installed(self, mock_import):
        """Should raise ImportError when cloakbrowser is not installed."""
        mock_import.side_effect = ImportError("CloakBrowser 未安装")
        bm = BrowserManager()
        with pytest.raises(ImportError, match="未安装"):
            bm.launch()

    @patch.dict("os.environ", {"USE_CLOAKBROWSER": "true"})
    @patch("src.core.browser_manager._import_cloakbrowser")
    def test_close_cloak_no_playwright_stop(self, mock_import):
        """Should NOT call playwright.stop() when using CloakBrowser."""
        mock_cloak = MagicMock()
        mock_import.return_value = mock_cloak
        mock_browser = MagicMock()
        mock_cloak.launch.return_value = mock_browser
        mock_browser.new_page.return_value = MagicMock()

        bm = BrowserManager()
        bm.launch()
        bm.close()

        mock_browser.close.assert_called_once()
        # _playwright should remain None — never started
        assert bm._playwright is None


class TestBrowserManagerLocalChrome:
    def test_clean_task_replaces_only_the_task_tab(self):
        manager = BrowserManager()
        manager._engine = "local_chrome"
        manager._browser = MagicMock()
        manager._browser.is_connected.return_value = True
        manager._context = MagicMock()
        old_page = MagicMock()
        old_page.is_closed.return_value = False
        new_page = MagicMock()
        manager._context.new_page.return_value = new_page
        manager._page = old_page

        assert manager.start_clean_context() is new_page

        old_page.close.assert_called_once_with()
        manager._context.close.assert_not_called()
        manager._browser.new_context.assert_not_called()

    @patch.dict("os.environ", {"BROWSER_ENGINE": "local_chrome"})
    @patch("src.core.browser_manager._local_chrome_endpoint_ready", return_value=True)
    @patch("src.core.browser_manager.sync_playwright")
    def test_connects_over_cdp_and_detaches_without_closing_chrome(
        self, mock_pw, _mock_ready
    ):
        playwright = MagicMock()
        mock_pw.return_value.start.return_value = playwright
        browser = MagicMock()
        context = MagicMock()
        page = MagicMock()
        page.is_closed.return_value = False
        context.new_page.return_value = page
        browser.contexts = [context]
        playwright.chromium.connect_over_cdp.return_value = browser

        manager = BrowserManager()
        assert manager.launch() is page
        assert manager.engine == "local_chrome"
        playwright.chromium.connect_over_cdp.assert_called_once_with(
            "http://127.0.0.1:9222"
        )

        manager.close()

        page.close.assert_called_once_with()
        context.close.assert_not_called()
        browser.close.assert_not_called()
        playwright.stop.assert_called_once_with()


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


class TestSingleton:
    """Tests for get_browser_manager / reset_browser_manager."""

    def teardown_method(self):
        reset_browser_manager()

    def test_singleton_returns_same_instance(self):
        """Should return the same BrowserManager instance."""
        bm1 = get_browser_manager()
        bm2 = get_browser_manager()
        assert bm1 is bm2

    def test_reset_creates_new_instance(self):
        """Should create a new instance after reset."""
        bm1 = get_browser_manager()
        reset_browser_manager()
        bm2 = get_browser_manager()
        assert bm1 is not bm2

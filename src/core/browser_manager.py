"""
Playwright / CloakBrowser 浏览器生命周期管理器。

提供单例模式的 BrowserManager，负责启动/关闭浏览器实例。
根据 USE_CLOAKBROWSER 环境变量选择引擎：
  - false（默认）: 官方 Playwright Chromium
  - true: CloakBrowser（反检测 Chromium，需 pip install agentic-playwright-mcp[stealth]）

所有页面操作通过 get_page() 获取统一入口。
"""

from __future__ import annotations

import os

from playwright.sync_api import sync_playwright, Page

from src.core.event_bus import (
    EVENT_BROWSER_CLOSE,
    EVENT_BROWSER_LAUNCH,
    Event,
    Phase,
    get_event_bus,
)
from src.logging import get_logger, log_browser_event

logger = get_logger(__name__)

_instance: "BrowserManager | None" = None


def _is_cloak_enabled() -> bool:
    """Check if CloakBrowser engine is enabled via env var."""
    return os.getenv("USE_CLOAKBROWSER", "true").strip().lower() == "true"


def _import_cloakbrowser():
    """Lazy-import cloakbrowser. Raises ImportError if not installed."""
    try:
        import cloakbrowser
        return cloakbrowser
    except ImportError:
        raise ImportError(
            "CloakBrowser 未安装。请运行: pip install agentic-playwright-mcp[stealth]"
        ) from None


class BrowserManager:
    """浏览器生命周期管理器（单例）。支持 Playwright 和 CloakBrowser 双引擎。"""

    def __init__(self) -> None:
        self._playwright = None
        self._browser = None
        self._page = None
        self._engine: str = "playwright"  # "playwright" | "cloakbrowser"

    @property
    def engine(self) -> str:
        """返回当前使用的浏览器引擎名称。"""
        return self._engine

    def launch(
        self,
        headless: bool = False,
        slow_mo: int = 500,
        humanize: bool = False,
        proxy: str | None = None,
    ) -> Page:
        """启动浏览器并返回默认页面。

        根据 USE_CLOAKBROWSER 环境变量自动选择引擎。

        Args:
            headless: 是否无头模式运行。
            slow_mo: 操作间延迟（毫秒），便于观察和调试。
            humanize: 仅 CloakBrowser — 启用真人行为模拟（鼠标曲线、键盘节奏）。
            proxy: 仅 CloakBrowser — 代理地址，如 "http://user:pass@host:port"。

        Returns:
            启动后的默认 Page 实例。
        """
        use_cloak = _is_cloak_enabled()

        if use_cloak:
            return self._launch_cloakbrowser(headless, humanize, proxy)
        else:
            return self._launch_playwright(headless, slow_mo)

    def _launch_playwright(self, headless: bool, slow_mo: int) -> Page:
        """使用官方 Playwright 启动 Chromium。"""
        bus = get_event_bus()
        event = Event(
            name=EVENT_BROWSER_LAUNCH,
            phase=Phase.BEFORE,
            data={"engine": "playwright", "headless": headless, "slow_mo": slow_mo},
        )
        bus.emit(event)
        if event.cancelled:
            raise RuntimeError(event.metadata.get("cancel_reason", "Browser launch cancelled by hook"))

        self._engine = "playwright"
        logger.info("Starting Playwright engine", extra={"headless": headless, "slow_mo": slow_mo})
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            headless=headless,
            slow_mo=slow_mo,
        )
        self._page = self._browser.new_page()
        log_browser_event("launched", engine="playwright", headless=headless)

        after_event = Event(
            name=EVENT_BROWSER_LAUNCH,
            phase=Phase.AFTER,
            data={"engine": "playwright", "headless": headless, "slow_mo": slow_mo},
            result=self._page,
        )
        bus.emit(after_event)
        return self._page

    def _launch_cloakbrowser(
        self,
        headless: bool,
        humanize: bool,
        proxy: str | None,
    ) -> Page:
        """使用 CloakBrowser 启动反检测 Chromium。"""
        bus = get_event_bus()
        event = Event(
            name=EVENT_BROWSER_LAUNCH,
            phase=Phase.BEFORE,
            data={"engine": "cloakbrowser", "headless": headless, "humanize": humanize, "proxy": proxy},
        )
        bus.emit(event)
        if event.cancelled:
            raise RuntimeError(event.metadata.get("cancel_reason", "Browser launch cancelled by hook"))

        cloakbrowser = _import_cloakbrowser()
        self._engine = "cloakbrowser"
        logger.info(
            "Starting CloakBrowser engine",
            extra={"headless": headless, "humanize": humanize, "proxy": bool(proxy)},
        )

        launch_kwargs: dict = {
            "headless": headless,
        }
        if humanize:
            launch_kwargs["humanize"] = True
        if proxy:
            launch_kwargs["proxy"] = proxy

        self._browser = cloakbrowser.launch(**launch_kwargs)
        self._page = self._browser.new_page()
        log_browser_event("launched", engine="cloakbrowser", headless=headless, humanize=humanize)

        after_event = Event(
            name=EVENT_BROWSER_LAUNCH,
            phase=Phase.AFTER,
            data={"engine": "cloakbrowser", "headless": headless, "humanize": humanize, "proxy": proxy},
            result=self._page,
        )
        bus.emit(after_event)
        return self._page

    def get_page(self) -> Page:
        """返回当前活跃页面。

        Returns:
            当前 Page 实例。

        Raises:
            RuntimeError: 浏览器尚未启动时抛出。
        """
        if self._page is None:
            raise RuntimeError(
                "浏览器尚未启动，请先调用 launch() 方法。"
            )
        return self._page

    def close(self) -> None:
        """关闭浏览器和 Playwright 实例。安全处理已关闭的情况。"""
        bus = get_event_bus()
        before_event = Event(
            name=EVENT_BROWSER_CLOSE,
            phase=Phase.BEFORE,
            data={"engine": self._engine},
        )
        bus.emit(before_event)
        if before_event.cancelled:
            logger.info("Browser close cancelled by hook")
            return

        logger.info("Closing browser", extra={"engine": self._engine})
        try:
            if self._browser is not None:
                self._browser.close()
        except Exception as exc:
            logger.warning("Error closing browser", extra={"error": str(exc)})
        finally:
            self._browser = None
            self._page = None

        # CloakBrowser 不需要单独 stop playwright
        if self._engine == "playwright":
            try:
                if self._playwright is not None:
                    self._playwright.stop()
            except Exception as exc:
                logger.warning("Error stopping Playwright", extra={"error": str(exc)})
            finally:
                self._playwright = None

        log_browser_event("closed", engine=self._engine)

        after_event = Event(
            name=EVENT_BROWSER_CLOSE,
            phase=Phase.AFTER,
            data={"engine": self._engine},
        )
        bus.emit(after_event)

    def is_alive(self) -> bool:
        """检查浏览器是否仍在运行。

        Returns:
            浏览器已启动且连接有效时返回 True。
        """
        if self._browser is None:
            return False
        try:
            _ = self._browser.contexts
            return True
        except Exception:
            return False


def get_browser_manager() -> BrowserManager:
    """获取全局单例 BrowserManager 实例。

    Returns:
        全局唯一的 BrowserManager 实例。
    """
    global _instance
    if _instance is None:
        _instance = BrowserManager()
    return _instance


def reset_browser_manager() -> None:
    """重置全局单例（用于测试）。"""
    global _instance
    if _instance is not None:
        try:
            _instance.close()
        except Exception:
            pass
    _instance = None

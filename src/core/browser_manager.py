"""
Playwright / CloakBrowser 浏览器生命周期管理器。

提供单例模式的 BrowserManager，负责启动/关闭浏览器实例。
根据 USE_CLOAKBROWSER 环境变量选择引擎：
  - false（默认）: 官方 Playwright Chromium
  - true: CloakBrowser（反检测 Chromium，需 pip install agentic-playwright-mcp[stealth]）

所有页面操作通过 get_page() 获取统一入口。

域名认证持久化：
  launch_with_domain(domain) 会自动加载该站点的 storage_state（如有），
  save_auth(domain) 在登录成功后保存 cookie / localStorage。
"""

from __future__ import annotations

import os

from playwright.sync_api import BrowserContext, Page, sync_playwright

from src.core.auth_manager import get_auth_manager
from src.core.event_bus import (
    EVENT_BROWSER_CLOSE,
    EVENT_BROWSER_LAUNCH,
    Event,
    Phase,
    get_event_bus,
)
from src.logging import get_logger, log_browser_event
from src.panel import get_panel_manager

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
        self._context: BrowserContext | None = None
        self._page = None
        self._engine: str = "playwright"  # "playwright" | "cloakbrowser"
        self._current_domain: str | None = None
        self._disconnected: bool = False  # 浏览器是否已断开连接

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
            raise RuntimeError(
                event.metadata.get("cancel_reason", "Browser launch cancelled by hook")
            )

        self._engine = "playwright"
        self._disconnected = False
        logger.info(
            "Starting Playwright engine",
            extra={"headless": headless, "slow_mo": slow_mo},
        )
        # 安全兜底：如果旧 _playwright 实例还在（比如 close() 因断开未完全清理），
        # 先停掉再启动新的，避免 asyncio loop 冲突
        if self._playwright is not None:
            logger.warning(
                "Stale _playwright instance found before launch, stopping it"
            )
            try:
                self._playwright.stop()
            except Exception:
                import asyncio

                asyncio.set_event_loop(asyncio.new_event_loop())
            self._playwright = None
        try:
            self._playwright = sync_playwright().start()
        except RuntimeError as exc:
            if "asyncio loop" in str(exc).lower():
                # 上次 stop() 未完全清理，强制重置后重试
                logger.warning("Playwright asyncio loop conflict, retrying: %s", exc)
                import asyncio

                asyncio.set_event_loop(asyncio.new_event_loop())
                self._playwright = sync_playwright().start()
            else:
                raise
        self._browser = self._playwright.chromium.launch(
            headless=headless,
            slow_mo=slow_mo,
        )
        # 监听浏览器断开事件（用户手动关闭窗口时触发）
        try:
            self._browser.on("disconnected", self._on_browser_disconnected)
        except Exception:
            pass  # 某些 Playwright 版本可能不支持
        self._context = self._browser.new_context()
        self._page = self._context.new_page()
        self._inject_panel()
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
            data={
                "engine": "cloakbrowser",
                "headless": headless,
                "humanize": humanize,
                "proxy": proxy,
            },
        )
        bus.emit(event)
        if event.cancelled:
            raise RuntimeError(
                event.metadata.get("cancel_reason", "Browser launch cancelled by hook")
            )

        cloakbrowser = _import_cloakbrowser()
        self._engine = "cloakbrowser"
        self._disconnected = False
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
        # 监听浏览器断开事件（用户手动关闭窗口时触发）
        try:
            self._browser.on("disconnected", self._on_browser_disconnected)
        except Exception:
            pass
        self._context = self._browser.new_context()
        self._page = self._context.new_page()
        self._inject_panel()
        log_browser_event(
            "launched", engine="cloakbrowser", headless=headless, humanize=humanize
        )

        after_event = Event(
            name=EVENT_BROWSER_LAUNCH,
            phase=Phase.AFTER,
            data={
                "engine": "cloakbrowser",
                "headless": headless,
                "humanize": humanize,
                "proxy": proxy,
            },
            result=self._page,
        )
        bus.emit(after_event)
        return self._page

    def _on_browser_disconnected(self) -> None:
        """浏览器断开连接时的回调（用户手动关闭窗口等）。"""
        logger.info("Browser disconnected detected")
        self._disconnected = True

    def get_page(self) -> Page:
        """返回当前活跃页面。

        Returns:
            当前 Page 实例。

        Raises:
            RuntimeError: 浏览器尚未启动时抛出。
        """
        if self._context is None:
            raise RuntimeError("浏览器尚未启动，请先调用 launch() 方法。")
        if self._page is None or self._page.is_closed():
            remaining = [p for p in self._context.pages if not p.is_closed()]
            if remaining:
                self._page = remaining[-1]
                logger.info("Auto-switched to live tab: %s", self._page.url)
            else:
                self._page = self._context.new_page()
                logger.info("Current page was closed, opened a replacement tab")
                self._inject_panel()
        return self._page

    def new_tab(self) -> Page:
        """在同一浏览器上下文中打开新标签页，返回新 Page。

        面板通过 context.addInitScript 自动注入到新标签页，无需额外处理。

        Returns:
            新创建的 Page 实例。

        Raises:
            RuntimeError: 浏览器尚未启动时抛出。
        """
        if self._context is None:
            raise RuntimeError("浏览器尚未启动，请先调用 launch() 方法。")
        page = self._context.new_page()
        logger.info("New tab opened: %s", page.url)
        return page

    def switch_page(self, page: Page) -> None:
        """切换当前活跃页面。

        后续 get_page() 将返回此 page。

        Args:
            page: 要切换到的 Page 实例。
        """
        self._page = page
        logger.info("Switched to tab: %s", page.url)

    def close_tab(self, page: Page) -> None:
        """关闭指定标签页。

        如果关闭的是当前活跃页，会自动切换到同 context 下的其他页面。
        如果没有剩余页面，当前页指针设为 None。

        Args:
            page: 要关闭的 Page 实例。
        """
        is_current = page is self._page
        try:
            page.close()
            logger.info("Tab closed: %s", page.url)
        except Exception as exc:
            logger.warning("Error closing tab: %s", exc)

        if is_current:
            # 尝试切换到 context 中的其他页面
            if self._context is not None:
                remaining = [
                    p for p in self._context.pages if not p.is_closed()
                ]
                if remaining:
                    self._page = remaining[-1]
                    logger.info("Auto-switched to tab: %s", self._page.url)
                    return
            self._page = None
            logger.info("No remaining tabs, page pointer set to None")

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

        # 在调用 Playwright close 之前，确认浏览器真的还连接着
        # 用户手动关闭窗口但 Chromium 进程还在时，is_connected() 可能返回 True
        # 但实际页面已不可访问，此时调用 close() 会触发闪烁
        if not self._disconnected and self._page is not None:
            try:
                self._page.evaluate("1")
            except Exception:
                self._disconnected = True
                logger.info("Browser page unreachable, marking as disconnected")

        if not self._disconnected:
            try:
                if self._context is not None:
                    self._context.close()
            except Exception as exc:
                logger.warning("Error closing context", extra={"error": str(exc)})
            try:
                if self._browser is not None:
                    self._browser.close()
            except Exception as exc:
                logger.warning("Error closing browser", extra={"error": str(exc)})
        else:
            # 浏览器已断开，跳过 context.close()（页面已死）
            # 但必须调 browser.close() — CloakBrowser 把 pw.stop() 绑在了
            # browser.close() 的 patch 里，不调的话 asyncio loop 永远不会清理
            logger.info("Browser disconnected, calling close for cleanup")
            try:
                if self._browser is not None:
                    self._browser.close()
            except Exception as exc:
                logger.warning(
                    "Error closing disconnected browser", extra={"error": str(exc)}
                )

        # 无论是否已断开，都清理引用
        # 清理面板管理器中对旧 context 的记录
        if self._context is not None:
            try:
                get_panel_manager().cleanup_context(self._context)
            except Exception:
                pass

        self._browser = None
        self._context = None
        self._page = None
        self._current_domain = None
        self._disconnected = False

        # 清理 Playwright / CloakBrowser 的 asyncio loop
        # 无论哪个引擎，底层都有 asyncio loop，断开后必须重置
        import asyncio

        if self._engine == "playwright":
            try:
                if self._playwright is not None:
                    self._playwright.stop()
            except Exception as exc:
                logger.warning(
                    "Error stopping Playwright, force-resetting asyncio loop: %s", exc
                )
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        loop.stop()
                except Exception:
                    pass
                asyncio.set_event_loop(asyncio.new_event_loop())
            finally:
                self._playwright = None
        else:
            # CloakBrowser 也需要重置 asyncio loop
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.stop()
            except Exception:
                pass
            asyncio.set_event_loop(asyncio.new_event_loop())

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
        if self._disconnected or self._browser is None:
            return False
        try:
            # 优先使用 Playwright 原生的 is_connected() 检测
            if hasattr(self._browser, "is_connected"):
                connected = bool(self._browser.is_connected())
                if not connected:
                    self._disconnected = True
                return connected
            # 回退：尝试访问 contexts
            _ = self._browser.contexts
            return True
        except Exception:
            self._disconnected = True
            return False

    # ------------------------------------------------------------------
    # 域名认证持久化
    # ------------------------------------------------------------------

    def launch_with_domain(
        self,
        domain: str,
        headless: bool = False,
        slow_mo: int = 500,
        humanize: bool = False,
        proxy: str | None = None,
    ) -> Page:
        """启动浏览器并自动加载该站点的 storage_state（如有）。

        浏览器已启动时，会关闭旧 context 并创建新的 context
        （不重新启动浏览器进程，速度快）。

        Args:
            domain: 站点名（对应 domains/{domain}.yaml）。
            headless: 是否无头模式。
            slow_mo: 操作间延迟（毫秒）。
            humanize: CloakBrowser 真人行为模拟。
            proxy: 代理地址。

        Returns:
            加载完成的 Page 实例。
        """
        am = get_auth_manager()

        # 浏览器已启动 → 只替换 context
        if self.is_alive() and self._browser is not None:
            # 关闭旧 context
            if self._context is not None:
                try:
                    self._context.close()
                except Exception:
                    pass

            # 创建新 context（带或不带 storage_state）
            ctx_kwargs: dict = {}
            auth_data = am.load_auth(domain)
            if auth_data:
                ctx_kwargs["storage_state"] = auth_data
                logger.info("Loaded auth for domain=%s", domain)
            else:
                logger.info("No auth found for domain=%s, using fresh context", domain)

            self._context = self._browser.new_context(**ctx_kwargs)
            self._page = self._context.new_page()
            self._inject_panel()
            self._current_domain = domain
            return self._page

        # 浏览器未启动 → 完整启动流程
        self.launch(headless=headless, slow_mo=slow_mo, humanize=humanize, proxy=proxy)

        # launch() 已创建 context，如果有 auth 则重新创建带 auth 的 context
        auth_data = am.load_auth(domain)
        if auth_data and self._browser is not None:
            # 关闭无 auth 的 context
            if self._context is not None:
                try:
                    self._context.close()
                except Exception:
                    pass
            self._context = self._browser.new_context(storage_state=auth_data)
            self._page = self._context.new_page()
            self._inject_panel()
            logger.info("Loaded auth for domain=%s", domain)

        self._current_domain = domain
        return self._page

    def save_auth(self, domain: str | None = None) -> bool:
        """保存当前 context 的 storage_state。

        Args:
            domain: 站点名。为 None 时使用 launch_with_domain 设置的 domain。

        Returns:
            True 保存成功，False 无 context 可保存。
        """
        if self._context is None:
            logger.warning("Cannot save auth: no active context")
            return False

        target = domain or self._current_domain
        if not target:
            logger.warning("Cannot save auth: no domain specified")
            return False

        am = get_auth_manager()
        am.save_auth(target, self._context)
        return True

    @property
    def current_domain(self) -> str | None:
        """当前加载的站点名。"""
        return self._current_domain

    def apply_auth_to_current_context(self, domain: str) -> bool:
        """Load saved auth cookies into the current context without opening a new page."""
        if self._context is None:
            logger.warning("Cannot apply auth: no active context")
            return False

        am = get_auth_manager()
        auth_data = am.load_auth(domain)
        if not auth_data:
            logger.info("No auth found for domain=%s", domain)
            return False

        cookies = auth_data.get("cookies") or []
        if cookies:
            try:
                self._context.add_cookies(cookies)
            except Exception as exc:
                logger.warning("Failed to apply cookies for domain=%s: %s", domain, exc)
                return False

        self._current_domain = domain
        logger.info("Applied auth cookies to current context for domain=%s", domain)
        return True

    def _inject_panel(self) -> None:
        """在当前 context 注入交互面板（内部方法）。"""
        if self._context is None:
            return
        try:
            pm = get_panel_manager()
            pm.inject(self._context)
        except Exception as exc:
            logger.warning("Failed to inject panel: %s", exc)


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

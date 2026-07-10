"""
浏览器交互面板管理器。

负责将 inject.js 注入到 BrowserContext，并提供 Python 端的面板控制 API。
所有页面操作通过 page.evaluate 调用 window.__agentic_panel__ 接口。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from playwright.sync_api import BrowserContext, Page

from src.logging import get_logger

logger = get_logger(__name__)

_instance: PanelManager | None = None

# inject.js 的路径
_INJECT_JS_PATH = Path(__file__).parent / "inject.js"


class PanelManager:
    """浏览器交互面板管理器（单例）。"""

    def __init__(self) -> None:
        self._injected_contexts: set[int] = set()

    def inject(self, context: BrowserContext) -> None:
        """将面板脚本注入到 BrowserContext。

        addInitScript 会自动应用到该 context 中的所有页面（包括新标签页、
        iframe、刷新后的页面）。重复调用对同一 context 会被跳过。

        Args:
            context: Playwright BrowserContext 实例。
        """
        ctx_id = id(context)
        if ctx_id in self._injected_contexts:
            logger.debug("Panel already injected for context %s", ctx_id)
            return

        if not _INJECT_JS_PATH.exists():
            logger.error("inject.js not found at %s", _INJECT_JS_PATH)
            return

        context.add_init_script(path=str(_INJECT_JS_PATH))
        self._injected_contexts.add(ctx_id)
        logger.info("Panel injected into context %s", ctx_id)

    def toggle(self, page: Page, visible: bool) -> None:
        """控制面板的显示/隐藏。

        Args:
            page: Playwright Page 实例。
            visible: True 显示面板，False 隐藏面板。
        """
        if visible:
            page.evaluate("window.__agentic_panel__ && window.__agentic_panel__.show()")
        else:
            page.evaluate("window.__agentic_panel__ && window.__agentic_panel__.hide()")

    def read_data(self, page: Page) -> dict[str, Any] | None:
        """读取用户通过面板输入的最新数据。

        Args:
            page: Playwright Page 实例。

        Returns:
            用户输入的数据字典，无数据时返回 None。
        """
        self._ensure_page_injected(page)
        return page.evaluate(
            "window.__agentic_panel__ ? window.__agentic_panel__.data : null"
        )

    def read_events(self, page: Page) -> list[dict[str, Any]]:
        """读取并清空面板事件队列。

        Args:
            page: Playwright Page 实例。

        Returns:
            事件列表，每个事件包含 action, value, timestamp。
        """
        return page.evaluate(
            "window.__agentic_panel__ ? window.__agentic_panel__.flushEvents() : []"
        )

    def log(self, page: Page, message: str) -> None:
        """向面板日志区写入消息。

        Args:
            page: Playwright Page 实例。
            message: 日志消息文本。
        """
        page.evaluate(
            "(msg) => window.__agentic_panel__ && window.__agentic_panel__.log(msg)",
            message,
        )

    def set_title(self, page: Page, text: str) -> None:
        """设置面板标题。

        Args:
            page: Playwright Page 实例。
            text: 标题文本。
        """
        page.evaluate(
            "(t) => window.__agentic_panel__ && window.__agentic_panel__.setTitle(t)",
            text,
        )

    def prompt(self, page: Page, question: str) -> Any:
        """向用户提问并等待回答。

        面板会展开并显示问题，用户输入回答后返回。
        注意：这是一个阻塞调用，会等待用户操作。

        Args:
            page: Playwright Page 实例。
            question: 要向用户展示的问题。

        Returns:
            用户的回答（字符串）。
        """
        self._ensure_page_injected(page)
        return page.evaluate(
            """(question) => {
                if (!window.__agentic_panel__) return null;
                return window.__agentic_panel__.prompt(question);
            }""",
            question,
        )

    def _ensure_page_injected(self, page: Page) -> None:
        """Ensure the panel exists on the current page, including about:blank."""
        try:
            if self.is_injected(page):
                return
        except Exception as exc:
            logger.debug("Panel injection check failed: %s", exc)

        if not _INJECT_JS_PATH.exists():
            logger.error("inject.js not found at %s", _INJECT_JS_PATH)
            return

        try:
            page.evaluate(
                """() => {
                    if (window.__agentic_panel__ && !document.getElementById("__agentic_panel__")) {
                        window.__agentic_panel__ = undefined;
                    }
                }"""
            )
            page.add_script_tag(content=_INJECT_JS_PATH.read_text(encoding="utf-8"))
            logger.debug("Panel injected into current page")
        except Exception as exc:
            logger.warning("Failed to inject panel into current page: %s", exc)

    def set_fields(self, page: Page, fields: list[dict[str, Any]]) -> None:
        """动态更新面板的表单字段。

        Args:
            page: Playwright Page 实例。
            fields: 字段定义列表，每个字段包含:
                - name: 字段名
                - label: 显示标签
                - type: 类型 (text/password/textarea/select)
                - placeholder: 占位提示
                - options: 仅 select 类型，选项列表
        """
        page.evaluate(
            "(f) => window.__agentic_panel__ && window.__agentic_panel__.setFields(f)",
            fields,
        )

    def is_injected(self, page: Page) -> bool:
        """检查面板是否已在当前页面注入。

        Args:
            page: Playwright Page 实例。

        Returns:
            面板已注入返回 True。
        """
        return bool(
            page.evaluate(
                """() => (
                    typeof window.__agentic_panel__ !== "undefined" &&
                    !!document.getElementById("__agentic_panel__")
                )"""
            )
        )

    def cleanup_context(self, context: BrowserContext) -> None:
        """清理已关闭 context 的记录。

        Args:
            context: 要清理的 BrowserContext。
        """
        ctx_id = id(context)
        self._injected_contexts.discard(ctx_id)


def get_panel_manager() -> PanelManager:
    """获取全局单例 PanelManager 实例。"""
    global _instance
    if _instance is None:
        _instance = PanelManager()
    return _instance


def reset_panel_manager() -> None:
    """重置全局单例（用于测试）。"""
    global _instance
    _instance = None

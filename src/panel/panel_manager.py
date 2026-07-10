"""Compatibility facade for the removed browser-injected panel.

The public methods remain so existing skills keep working. They now delegate
to the desktop interaction broker and never inspect or mutate page DOM.
"""

from __future__ import annotations

from typing import Any

from src.core.user_interaction import get_user_interaction_broker

_instance: "PanelManager | None" = None


class PanelManager:
    """DOM-free compatibility adapter for legacy ``panel_*`` helpers."""

    def inject(self, context: Any) -> None:
        del context

    def toggle(self, page: Any, visible: bool) -> None:
        del page, visible

    def read_data(self, page: Any = None) -> dict[str, Any] | None:
        del page
        return get_user_interaction_broker().read_data()

    def read_events(self, page: Any = None) -> list[dict[str, Any]]:
        del page
        return get_user_interaction_broker().read_events()

    def log(self, page: Any, message: str) -> None:
        del page
        get_user_interaction_broker().log(message)

    def set_title(self, page: Any, text: str) -> None:
        del page
        get_user_interaction_broker().set_title(text)

    def prompt(self, page: Any, question: str) -> Any:
        del page
        return get_user_interaction_broker().prompt(question)

    def set_fields(self, page: Any, fields: list[dict[str, Any]]) -> None:
        del page
        get_user_interaction_broker().set_fields(fields)

    def is_injected(self, page: Any) -> bool:
        del page
        return False

    def cleanup_context(self, context: Any) -> None:
        del context


def get_panel_manager() -> PanelManager:
    global _instance
    if _instance is None:
        _instance = PanelManager()
    return _instance


def reset_panel_manager() -> None:
    global _instance
    _instance = None

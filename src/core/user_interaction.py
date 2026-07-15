"""Desktop-safe user interaction bridge.

Browser automation scripts historically talked to an injected page panel.  The
desktop application now owns all user interaction, so this module provides a
small process-local broker that is independent from Playwright page DOM.
"""

from __future__ import annotations

import sys
import threading
from typing import Any, Protocol

from src.logging import get_logger

logger = get_logger(__name__)


class InteractionAdapter(Protocol):
    def log(self, message: str) -> None: ...

    def prompt(
        self,
        question: str,
        *,
        title: str = "",
        fields: list[dict[str, Any]] | None = None,
    ) -> Any: ...

    def read_data(self) -> dict[str, Any] | None: ...

    def read_events(self) -> list[dict[str, Any]]: ...

    def cancel_event(self) -> threading.Event: ...

    def publish_sensitive_result(
        self,
        kind: str,
        payload: dict[str, Any],
        *,
        ttl_seconds: int = 1800,
    ) -> str: ...

    def summarize_sensitive_result(self, result_id: str) -> dict[str, Any]: ...


class UserInteractionBroker:
    """Route logs and confirmation prompts to the active desktop task."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._adapter: InteractionAdapter | None = None
        self._title = ""
        self._fields: list[dict[str, Any]] = []

    def attach(self, adapter: InteractionAdapter) -> None:
        with self._lock:
            self._adapter = adapter
            self._title = ""
            self._fields = []

    def detach(self, adapter: InteractionAdapter | None = None) -> None:
        with self._lock:
            if adapter is None or self._adapter is adapter:
                self._adapter = None
                self._title = ""
                self._fields = []

    def log(self, message: str) -> None:
        with self._lock:
            adapter = self._adapter
        if adapter is not None:
            adapter.log(str(message))
            return
        logger.info("User interaction log: %s", message)

    def prompt(self, question: str) -> Any:
        with self._lock:
            adapter = self._adapter
            title = self._title
            fields = list(self._fields)
        if adapter is not None:
            return adapter.prompt(str(question), title=title, fields=fields)
        if sys.stdin is not None and sys.stdin.isatty():
            return input(f"{question}\n> ")
        logger.warning("No desktop interaction client is connected for prompt: %s", question)
        return None

    def set_title(self, title: str) -> None:
        with self._lock:
            self._title = str(title)

    def set_fields(self, fields: list[dict[str, Any]]) -> None:
        with self._lock:
            self._fields = [dict(field) for field in fields]

    def read_data(self) -> dict[str, Any] | None:
        with self._lock:
            adapter = self._adapter
        return adapter.read_data() if adapter is not None else None

    def read_events(self) -> list[dict[str, Any]]:
        with self._lock:
            adapter = self._adapter
        return adapter.read_events() if adapter is not None else []

    def cancel_event(self) -> threading.Event | None:
        with self._lock:
            adapter = self._adapter
        return adapter.cancel_event() if adapter is not None else None

    def publish_sensitive_result(
        self,
        kind: str,
        payload: dict[str, Any],
        *,
        ttl_seconds: int = 1800,
    ) -> str:
        with self._lock:
            adapter = self._adapter
        if adapter is None:
            raise RuntimeError("Sensitive results require an active desktop task")
        return adapter.publish_sensitive_result(
            kind,
            payload,
            ttl_seconds=ttl_seconds,
        )

    def summarize_sensitive_result(self, result_id: str) -> dict[str, Any]:
        with self._lock:
            adapter = self._adapter
        if adapter is None:
            raise RuntimeError("Sensitive summaries require an active desktop task")
        return adapter.summarize_sensitive_result(result_id)


_instance: UserInteractionBroker | None = None


def get_user_interaction_broker() -> UserInteractionBroker:
    global _instance
    if _instance is None:
        _instance = UserInteractionBroker()
    return _instance


def reset_user_interaction_broker() -> None:
    global _instance
    _instance = None

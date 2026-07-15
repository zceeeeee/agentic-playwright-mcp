"""Process-local storage for sensitive results that must never reach SQLite."""

from __future__ import annotations

import copy
import json
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Any


@dataclass
class SensitiveResultEntry:
    result_id: str
    task_id: str
    conversation_id: str
    kind: str
    payload: dict[str, Any]
    created_at: float
    expires_at: float


class SensitiveResultStore:
    def __init__(self, *, max_entry_bytes: int = 12 * 1024 * 1024) -> None:
        self._max_entry_bytes = max_entry_bytes
        self._entries: dict[str, SensitiveResultEntry] = {}
        self._lock = threading.RLock()

    def put(
        self,
        *,
        task_id: str,
        conversation_id: str,
        kind: str,
        payload: dict[str, Any],
        ttl_seconds: int = 1800,
    ) -> str:
        copied = copy.deepcopy(payload)
        self._validate_size(copied)
        now = time.monotonic()
        result_id = f"sensitive_{secrets.token_urlsafe(24)}"
        entry = SensitiveResultEntry(
            result_id=result_id,
            task_id=task_id,
            conversation_id=conversation_id,
            kind=kind,
            payload=copied,
            created_at=now,
            expires_at=now + max(60, min(int(ttl_seconds), 7200)),
        )
        with self._lock:
            self._cleanup_expired_locked(now)
            self._entries[result_id] = entry
        return result_id

    def get(
        self,
        result_id: str,
        *,
        task_id: str | None = None,
        conversation_id: str | None = None,
    ) -> dict[str, Any] | None:
        entry = self.get_entry(
            result_id, task_id=task_id, conversation_id=conversation_id
        )
        return copy.deepcopy(entry.payload) if entry is not None else None

    def get_entry(
        self,
        result_id: str,
        *,
        task_id: str | None = None,
        conversation_id: str | None = None,
    ) -> SensitiveResultEntry | None:
        now = time.monotonic()
        with self._lock:
            self._cleanup_expired_locked(now)
            entry = self._entries.get(result_id)
            if entry is None:
                return None
            if task_id is not None and entry.task_id != task_id:
                return None
            if conversation_id is not None and entry.conversation_id != conversation_id:
                return None
            return copy.deepcopy(entry)

    def update(self, result_id: str, payload: dict[str, Any]) -> bool:
        copied = copy.deepcopy(payload)
        self._validate_size(copied)
        with self._lock:
            self._cleanup_expired_locked(time.monotonic())
            entry = self._entries.get(result_id)
            if entry is None:
                return False
            entry.payload = copied
            return True

    def delete(self, result_id: str) -> None:
        with self._lock:
            self._entries.pop(result_id, None)

    def delete_for_task(self, task_id: str) -> None:
        with self._lock:
            result_ids = [
                result_id
                for result_id, entry in self._entries.items()
                if entry.task_id == task_id
            ]
            for result_id in result_ids:
                self._entries.pop(result_id, None)

    def cleanup_expired(self) -> None:
        with self._lock:
            self._cleanup_expired_locked(time.monotonic())

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def _cleanup_expired_locked(self, now: float) -> None:
        expired = [
            result_id
            for result_id, entry in self._entries.items()
            if entry.expires_at <= now
        ]
        for result_id in expired:
            self._entries.pop(result_id, None)

    def _validate_size(self, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
        if len(encoded) > self._max_entry_bytes:
            raise ValueError("Sensitive result exceeds the in-memory size limit")

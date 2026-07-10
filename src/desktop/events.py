"""Thread-safe WebSocket event fan-out for the desktop backend."""

from __future__ import annotations

import asyncio
import threading
import uuid
from datetime import UTC, datetime
from typing import Any


class DesktopEventHub:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._clients: dict[asyncio.Queue, asyncio.AbstractEventLoop] = {}

    async def connect(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=500)
        with self._lock:
            self._clients[queue] = asyncio.get_running_loop()
        return queue

    def disconnect(self, queue: asyncio.Queue) -> None:
        with self._lock:
            self._clients.pop(queue, None)

    def publish(
        self,
        event_type: str,
        *,
        task_id: str | None = None,
        conversation_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        event = {
            "event_id": f"event_{uuid.uuid4().hex}",
            "type": event_type,
            "task_id": task_id,
            "conversation_id": conversation_id,
            "timestamp": datetime.now(UTC).isoformat(),
            "payload": payload or {},
        }
        with self._lock:
            clients = list(self._clients.items())
        for queue, loop in clients:
            if loop.is_closed():
                self.disconnect(queue)
                continue
            loop.call_soon_threadsafe(self._put, queue, event)
        return event

    @staticmethod
    def _put(queue: asyncio.Queue, event: dict[str, Any]) -> None:
        if queue.full():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        queue.put_nowait(event)


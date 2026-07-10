"""SQLite persistence for desktop conversations, tasks and confirmations."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class DesktopDatabase:
    def __init__(self, path: str | Path | None = None) -> None:
        default_dir = Path(
            os.environ.get(
                "DESKTOP_AGENT_DATA_DIR",
                Path.home() / ".agentic-playwright",
            )
        )
        self.path = Path(path) if path is not None else default_dir / "desktop-agent.db"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _initialize(self) -> None:
        schema = """
        CREATE TABLE IF NOT EXISTS conversations (
          id TEXT PRIMARY KEY,
          title TEXT NOT NULL,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS messages (
          id TEXT PRIMARY KEY,
          conversation_id TEXT NOT NULL,
          task_id TEXT,
          role TEXT NOT NULL,
          type TEXT NOT NULL,
          content TEXT,
          metadata_json TEXT,
          created_at TEXT NOT NULL,
          FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS tasks (
          id TEXT PRIMARY KEY,
          conversation_id TEXT NOT NULL,
          user_message_id TEXT,
          status TEXT NOT NULL,
          created_at TEXT NOT NULL,
          started_at TEXT,
          finished_at TEXT,
          error_json TEXT,
          FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS confirmations (
          id TEXT PRIMARY KEY,
          task_id TEXT NOT NULL,
          title TEXT,
          message TEXT,
          status TEXT NOT NULL,
          user_comment TEXT,
          metadata_json TEXT,
          created_at TEXT NOT NULL,
          resolved_at TEXT,
          FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_messages_conversation
          ON messages(conversation_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_tasks_conversation
          ON tasks(conversation_id, created_at);
        """
        with self._lock, self._connect() as connection:
            connection.executescript(schema)

    @staticmethod
    def _rows(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
        return [dict(row) for row in rows]

    def create_conversation(self, conversation_id: str, title: str) -> dict[str, Any]:
        now = utc_now()
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT INTO conversations(id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (conversation_id, title, now, now),
            )
        return self.get_conversation(conversation_id) or {}

    def get_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM conversations WHERE id = ?", (conversation_id,)
            ).fetchone()
        return dict(row) if row is not None else None

    def list_conversations(self) -> list[dict[str, Any]]:
        query = """
        SELECT c.*,
          (SELECT content FROM messages m WHERE m.conversation_id = c.id
           ORDER BY m.created_at DESC LIMIT 1) AS last_message,
          (SELECT status FROM tasks t WHERE t.conversation_id = c.id
           ORDER BY t.created_at DESC LIMIT 1) AS task_status
        FROM conversations c ORDER BY c.updated_at DESC
        """
        with self._lock, self._connect() as connection:
            return self._rows(connection.execute(query).fetchall())

    def rename_conversation(self, conversation_id: str, title: str) -> bool:
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
                (title, utc_now(), conversation_id),
            )
            return cursor.rowcount == 1

    def delete_conversation(self, conversation_id: str) -> bool:
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM conversations WHERE id = ?", (conversation_id,)
            )
            return cursor.rowcount == 1

    def clear_conversations(self) -> None:
        with self._lock, self._connect() as connection:
            connection.execute("DELETE FROM conversations")

    def add_message(
        self,
        message_id: str,
        conversation_id: str,
        *,
        role: str,
        message_type: str,
        content: str,
        task_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = utc_now()
        encoded = json.dumps(metadata or {}, ensure_ascii=False)
        with self._lock, self._connect() as connection:
            connection.execute(
                """INSERT INTO messages
                   (id, conversation_id, task_id, role, type, content, metadata_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    message_id,
                    conversation_id,
                    task_id,
                    role,
                    message_type,
                    content,
                    encoded,
                    now,
                ),
            )
            connection.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (now, conversation_id),
            )
        return {
            "id": message_id,
            "conversation_id": conversation_id,
            "task_id": task_id,
            "role": role,
            "type": message_type,
            "content": content,
            "metadata": metadata or {},
            "created_at": now,
        }

    def list_messages(self, conversation_id: str) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at",
                (conversation_id,),
            ).fetchall()
        messages = self._rows(rows)
        for message in messages:
            try:
                message["metadata"] = json.loads(message.pop("metadata_json") or "{}")
            except json.JSONDecodeError:
                message["metadata"] = {}
        return messages

    def create_task(
        self,
        task_id: str,
        conversation_id: str,
        user_message_id: str,
    ) -> dict[str, Any]:
        now = utc_now()
        with self._lock, self._connect() as connection:
            connection.execute(
                """INSERT INTO tasks
                   (id, conversation_id, user_message_id, status, created_at)
                   VALUES (?, ?, ?, 'queued', ?)""",
                (task_id, conversation_id, user_message_id, now),
            )
        return self.get_task(task_id) or {}

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()
        return dict(row) if row is not None else None

    def list_tasks(self, conversation_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            if conversation_id:
                rows = connection.execute(
                    "SELECT * FROM tasks WHERE conversation_id = ? ORDER BY created_at DESC",
                    (conversation_id,),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM tasks ORDER BY created_at DESC LIMIT 200"
                ).fetchall()
        return self._rows(rows)

    def update_task(
        self,
        task_id: str,
        status: str,
        *,
        error: dict[str, Any] | None = None,
    ) -> None:
        started_at = utc_now() if status == "running" else None
        finished_at = utc_now() if status in {"success", "failed", "cancelled"} else None
        with self._lock, self._connect() as connection:
            connection.execute(
                """UPDATE tasks SET status = ?,
                   started_at = COALESCE(started_at, ?),
                   finished_at = COALESCE(?, finished_at), error_json = ?
                   WHERE id = ?""",
                (
                    status,
                    started_at,
                    finished_at,
                    json.dumps(error, ensure_ascii=False) if error else None,
                    task_id,
                ),
            )

    def create_confirmation(
        self,
        confirmation_id: str,
        task_id: str,
        title: str,
        message: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = utc_now()
        with self._lock, self._connect() as connection:
            connection.execute(
                """INSERT INTO confirmations
                   (id, task_id, title, message, status, metadata_json, created_at)
                   VALUES (?, ?, ?, ?, 'pending', ?, ?)""",
                (
                    confirmation_id,
                    task_id,
                    title,
                    message,
                    json.dumps(metadata or {}, ensure_ascii=False),
                    now,
                ),
            )
        return self.get_confirmation(confirmation_id) or {}

    def get_confirmation(self, confirmation_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM confirmations WHERE id = ?", (confirmation_id,)
            ).fetchone()
        item = dict(row) if row is not None else None
        if item is not None:
            try:
                item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
            except json.JSONDecodeError:
                item["metadata"] = {}
        return item

    def resolve_confirmation(
        self, confirmation_id: str, status: str, comment: str
    ) -> bool:
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """UPDATE confirmations SET status = ?, user_comment = ?, resolved_at = ?
                   WHERE id = ? AND status = 'pending'""",
                (status, comment, utc_now(), confirmation_id),
            )
            return cursor.rowcount == 1

    def cancel_pending_confirmations(self, task_id: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """UPDATE confirmations SET status = 'cancelled', resolved_at = ?
                   WHERE task_id = ? AND status = 'pending'""",
                (utc_now(), task_id),
            )


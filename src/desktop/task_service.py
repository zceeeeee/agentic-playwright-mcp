"""Background task execution service used by the desktop application."""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from src.core.agent_loop import AgentLoop, AgentStep
from src.core.browser_manager import get_browser_manager
from src.core.user_interaction import get_user_interaction_broker
from src.desktop.database import DesktopDatabase
from src.desktop.events import DesktopEventHub
from src.desktop.prompts import parse_desktop_prompt
from src.desktop.sensitive_result_store import SensitiveResultStore
from src.logging import get_logger

logger = get_logger(__name__)


def _public_sensitive_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Strip backend-only cursor fields before sending a one-shot event."""

    return {
        key: value
        for key, value in payload.items()
        if not str(key).startswith("_")
    }


def _is_wechat_desktop_task(content: str) -> bool:
    normalized = content.strip().lower()
    if any(term in normalized for term in ("怎么", "如何", "安全吗", "恢复方法")):
        return False
    if "微信" in normalized or "wechat" in normalized:
        return any(
            term in normalized
            for term in (
                "发送",
                "发消息",
                "发文件",
                "传文件",
                "关注",
                "私信",
                "公众号",
                "服务号",
                "读取",
                "查看",
                "查询",
                "聊天记录",
                "聊天历史",
                "历史消息",
            )
        )
    history_terms = ("聊天记录", "聊天历史", "历史消息", "消息记录", "最近聊天")
    if any(term in normalized for term in ("公众号", "服务号")) and any(
        term in normalized for term in ("关注", "订阅", "私信", "发送", "发消息")
    ):
        return True
    if "文件传输助手" in normalized and any(term in normalized for term in history_terms):
        return True
    return (
        any(prefix in normalized for prefix in ("我和", "我与"))
        and any(term in normalized for term in ("最近", "历史", "以前", "从20"))
        and any(term in normalized for term in ("聊天", "消息", "记录"))
    )


class DesktopTaskCancelled(RuntimeError):
    pass


@dataclass
class ConfirmationWait:
    condition: threading.Condition = field(default_factory=threading.Condition)
    resolved: bool = False
    approved: bool = False
    comment: str = ""
    value: str = ""
    action_id: str = ""


@dataclass
class TaskControl:
    task_id: str
    conversation_id: str
    cancel_event: threading.Event = field(default_factory=threading.Event)
    future: Future | None = None


class DesktopInteractionAdapter:
    def __init__(self, service: "DesktopTaskService", control: TaskControl) -> None:
        self._service = service
        self._control = control
        self._last_data: dict[str, Any] | None = None
        self._events: list[dict[str, Any]] = []

    def log(self, message: str) -> None:
        self._service.add_progress(self._control, str(message), details={"source": "script"})

    def prompt(
        self,
        question: str,
        *,
        title: str = "",
        fields: list[dict[str, Any]] | None = None,
    ) -> Any:
        confirmation_id = f"confirm_{uuid.uuid4().hex}"
        wait = ConfirmationWait()
        prompt = parse_desktop_prompt(question, title=title, fields=fields)
        metadata = {key: value for key, value in prompt.items() if key not in {"title", "message"}}
        self._service.database.create_confirmation(
            confirmation_id,
            self._control.task_id,
            prompt["title"],
            prompt["message"],
            metadata,
        )
        self._service.register_confirmation(confirmation_id, wait)
        self._service.database.update_task(self._control.task_id, "waiting_confirmation")
        self._service.events.publish(
            "agent_state_changed",
            task_id=self._control.task_id,
            conversation_id=self._control.conversation_id,
            payload={"state": "waiting_confirmation"},
        )
        self._service.events.publish(
            "confirmation_required",
            task_id=self._control.task_id,
            conversation_id=self._control.conversation_id,
            payload={
                "confirmation_id": confirmation_id,
                "title": prompt["title"],
                "message": prompt["message"],
                **metadata,
            },
        )

        with wait.condition:
            while not wait.resolved:
                if self._control.cancel_event.is_set():
                    self._service.unregister_confirmation(confirmation_id)
                    raise DesktopTaskCancelled("任务已取消")
                wait.condition.wait(timeout=0.25)

        self._service.unregister_confirmation(confirmation_id)
        self._last_data = {
            "answer": wait.value,
            "approved": wait.approved,
            "action_id": wait.action_id,
            "comment": wait.comment,
        }
        self._events.append(
            {
                "action": "confirmation_resolved",
                "value": self._last_data,
                "timestamp": time.time(),
            }
        )
        if not wait.approved:
            raise DesktopTaskCancelled("用户拒绝继续执行")
        self._service.database.update_task(self._control.task_id, "running")
        self._service.events.publish(
            "agent_state_changed",
            task_id=self._control.task_id,
            conversation_id=self._control.conversation_id,
            payload={"state": "running"},
        )
        if prompt["prompt_type"] == "confirm_value" and wait.action_id == "keep":
            return ""
        return wait.value or ("yes" if prompt["prompt_type"] == "confirmation" else "")

    def read_data(self) -> dict[str, Any] | None:
        return self._last_data

    def read_events(self) -> list[dict[str, Any]]:
        events = list(self._events)
        self._events.clear()
        return events

    def cancel_event(self) -> threading.Event:
        return self._control.cancel_event

    def publish_sensitive_result(
        self,
        kind: str,
        payload: dict[str, Any],
        *,
        ttl_seconds: int = 1800,
    ) -> str:
        result_id = self._service.sensitive_results.put(
            task_id=self._control.task_id,
            conversation_id=self._control.conversation_id,
            kind=kind,
            payload=payload,
            ttl_seconds=ttl_seconds,
        )
        self._service.events.publish(
            f"{kind}_result",
            task_id=self._control.task_id,
            conversation_id=self._control.conversation_id,
            payload={
                "result_id": result_id,
                **_public_sensitive_payload(payload),
                "sensitive": True,
                "persist": False,
            },
        )
        return result_id

    def summarize_sensitive_result(self, result_id: str) -> dict[str, Any]:
        return self._service.summarize_sensitive_history(result_id)


class DesktopTaskService:
    """Serialize Playwright tasks onto one worker and stream structured events."""

    def __init__(self, database: DesktopDatabase, events: DesktopEventHub) -> None:
        self.database = database
        self.events = events
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="desktop-agent")
        self._lock = threading.RLock()
        self._controls: dict[str, TaskControl] = {}
        self._confirmations: dict[str, ConfirmationWait] = {}
        self._active_task_id: str | None = None
        self.sensitive_results = SensitiveResultStore()

    def create_task(
        self,
        content: str,
        *,
        conversation_id: str | None = None,
    ) -> dict[str, Any]:
        content = content.strip()
        if not content:
            raise ValueError("Task content cannot be empty")
        conversation_id = conversation_id or f"conversation_{uuid.uuid4().hex}"
        if self.database.get_conversation(conversation_id) is None:
            title = content.replace("\n", " ")[:40] or "新会话"
            self.database.create_conversation(conversation_id, title)

        task_id = f"task_{uuid.uuid4().hex}"
        message_id = f"message_{uuid.uuid4().hex}"
        message = self.database.add_message(
            message_id,
            conversation_id,
            role="user",
            message_type="user",
            content=content,
            task_id=task_id,
        )
        task = self.database.create_task(task_id, conversation_id, message_id)
        control = TaskControl(task_id=task_id, conversation_id=conversation_id)
        with self._lock:
            self._controls[task_id] = control

        self.events.publish(
            "assistant_message",
            task_id=task_id,
            conversation_id=conversation_id,
            payload={"message": message},
        )
        self.events.publish(
            "task_created",
            task_id=task_id,
            conversation_id=conversation_id,
            payload={"status": "queued"},
        )
        control.future = self._executor.submit(self._run_task, control, content)
        return task

    def _run_task(self, control: TaskControl, content: str) -> None:
        adapter = DesktopInteractionAdapter(self, control)
        broker = get_user_interaction_broker()
        with self._lock:
            self._active_task_id = control.task_id
        broker.attach(adapter)
        try:
            if control.cancel_event.is_set():
                raise DesktopTaskCancelled("任务已取消")
            self.database.update_task(control.task_id, "running")
            self.events.publish(
                "task_started",
                task_id=control.task_id,
                conversation_id=control.conversation_id,
                payload={"status": "running"},
            )
            self.events.publish(
                "agent_state_changed",
                task_id=control.task_id,
                conversation_id=control.conversation_id,
                payload={"state": "running"},
            )

            desktop_only = _is_wechat_desktop_task(content)
            browser = get_browser_manager()
            if desktop_only:
                if browser.is_alive():
                    browser.close()
                    self.events.publish(
                        "browser_closed",
                        task_id=control.task_id,
                        conversation_id=control.conversation_id,
                        payload={"reason": "desktop_only_task"},
                    )
                self._initialize_wechat_runtime(control)
            elif not browser.is_alive():
                headless = os.getenv("BROWSER_HEADLESS", "false").lower() == "true"
                browser.launch(headless=headless)
                self.events.publish(
                    "browser_started",
                    task_id=control.task_id,
                    conversation_id=control.conversation_id,
                    payload={"headless": headless, "engine": browser.engine},
                )

            def on_step(step: AgentStep) -> None:
                self.add_progress(
                    control,
                    step.result or step.action or step.state.value,
                    details={
                        "step": step.step_number,
                        "state": step.state.value,
                        "action": step.action,
                        "script": step.script,
                        "error": step.error,
                        "page_summary": step.page_summary,
                    },
                )

            agent = AgentLoop(
                max_steps=int(os.getenv("DESKTOP_AGENT_MAX_STEPS", "20")),
                on_step=on_step,
                cancel_check=control.cancel_event.is_set,
                desktop_only=desktop_only,
            )
            result = agent.run(content)
            if control.cancel_event.is_set() or result.error == "任务已取消":
                raise DesktopTaskCancelled("任务已取消")
            if not result.success:
                raise RuntimeError(result.error or "任务未完成")

            summary = result.output or "任务已经完成"
            message = self.database.add_message(
                f"message_{uuid.uuid4().hex}",
                control.conversation_id,
                role="assistant",
                message_type="result",
                content=summary,
                task_id=control.task_id,
                metadata={"final_url": result.final_url},
            )
            self.database.update_task(control.task_id, "success")
            self.events.publish(
                "assistant_message",
                task_id=control.task_id,
                conversation_id=control.conversation_id,
                payload={"message": message},
            )
            self.events.publish(
                "task_succeeded",
                task_id=control.task_id,
                conversation_id=control.conversation_id,
                payload={"summary": "任务已经完成", "result": summary},
            )
            self.events.publish(
                "agent_state_changed",
                task_id=control.task_id,
                conversation_id=control.conversation_id,
                payload={"state": "success"},
            )
            threading.Timer(3.0, self._return_to_idle, args=(control.task_id,)).start()
        except DesktopTaskCancelled as exc:
            self.sensitive_results.delete_for_task(control.task_id)
            self.database.cancel_pending_confirmations(control.task_id)
            self.database.update_task(control.task_id, "cancelled")
            message = self.database.add_message(
                f"message_{uuid.uuid4().hex}",
                control.conversation_id,
                role="system",
                message_type="system",
                content=str(exc),
                task_id=control.task_id,
            )
            self.events.publish(
                "assistant_message",
                task_id=control.task_id,
                conversation_id=control.conversation_id,
                payload={"message": message},
            )
            self.events.publish(
                "task_cancelled",
                task_id=control.task_id,
                conversation_id=control.conversation_id,
                payload={"message": str(exc)},
            )
            self.events.publish(
                "agent_state_changed",
                task_id=control.task_id,
                conversation_id=control.conversation_id,
                payload={"state": "idle"},
            )
        except Exception as exc:
            logger.exception("Desktop task failed: %s", exc)
            error = {"message": str(exc), "technical_details": f"{type(exc).__name__}: {exc}"}
            self.database.update_task(control.task_id, "failed", error=error)
            message = self.database.add_message(
                f"message_{uuid.uuid4().hex}",
                control.conversation_id,
                role="assistant",
                message_type="error",
                content=str(exc),
                task_id=control.task_id,
                metadata=error,
            )
            self.events.publish(
                "assistant_message",
                task_id=control.task_id,
                conversation_id=control.conversation_id,
                payload={"message": message},
            )
            self.events.publish(
                "task_failed",
                task_id=control.task_id,
                conversation_id=control.conversation_id,
                payload=error,
            )
            self.events.publish(
                "agent_state_changed",
                task_id=control.task_id,
                conversation_id=control.conversation_id,
                payload={"state": "error"},
            )
        finally:
            broker.detach(adapter)
            with self._lock:
                if self._active_task_id == control.task_id:
                    self._active_task_id = None

    def _initialize_wechat_runtime(self, control: TaskControl) -> None:
        from src.layer_1.wx_cli_client import WxCliClient, WxCliError

        self.add_progress(control, "正在自动初始化 wx-cli...", details={"source": "wx_cli"})
        try:
            status = WxCliClient().initialize(cancel_event=control.cancel_event)
        except WxCliError as exc:
            if control.cancel_event.is_set() or exc.code == "WX_CLI_CANCELLED":
                raise DesktopTaskCancelled("任务已取消") from exc
            raise
        self.add_progress(
            control,
            f"wx-cli {status.version or ''} 初始化完成。".replace("  ", " "),
            details={"source": "wx_cli", "version": status.version},
        )

    def add_progress(
        self,
        control: TaskControl,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        if not message:
            return
        stored = self.database.add_message(
            f"message_{uuid.uuid4().hex}",
            control.conversation_id,
            role="system",
            message_type="progress",
            content=message,
            task_id=control.task_id,
            metadata=details or {},
        )
        self.events.publish(
            "task_progress",
            task_id=control.task_id,
            conversation_id=control.conversation_id,
            payload={"message": message, "details": details or {}, "stored_message": stored},
        )

    def cancel_task(self, task_id: str) -> bool:
        with self._lock:
            control = self._controls.get(task_id)
        if control is None:
            return False
        control.cancel_event.set()
        self.sensitive_results.delete_for_task(task_id)
        with self._lock:
            waits = list(self._confirmations.values())
        for wait in waits:
            with wait.condition:
                wait.condition.notify_all()
        return True

    def wx_cli_status(self) -> dict[str, Any]:
        from dataclasses import asdict

        from src.layer_1.wx_cli_client import WxCliClient

        return asdict(WxCliClient().check_status())

    def load_more_sensitive_history(
        self, result_id: str, *, limit: int = 50
    ) -> dict[str, Any]:
        from src.layer_1.wechat_history_service import WechatHistoryService

        entry = self.sensitive_results.get_entry(result_id)
        if entry is None or entry.kind != "wechat_history":
            raise KeyError("SENSITIVE_RESULT_EXPIRED")
        payload = entry.payload
        cursor = payload.get("_cursor")
        if not isinstance(cursor, dict):
            raise KeyError("SENSITIVE_RESULT_EXPIRED")
        page = WechatHistoryService().read_more(
            username=str(cursor.get("username") or ""),
            display_name=str(payload.get("chat") or ""),
            chat_type=str(payload.get("chat_type") or "unknown"),
            limit=max(1, min(int(limit), 500)),
            offset=int(cursor.get("next_offset") or 0),
            since=cursor.get("since"),
            until=cursor.get("until"),
            message_type=cursor.get("message_type"),
        )
        current_messages = payload.get("messages")
        if not isinstance(current_messages, list):
            current_messages = []
        combined = _dedupe_sensitive_messages(
            [*current_messages, *[message.to_public_dict() for message in page.messages]]
        )
        updated = {
            **payload,
            "count": len(combined),
            "messages": combined,
            "meta": page.meta.to_public_dict(),
            "warnings": list(
                dict.fromkeys(
                    [
                        *list(payload.get("warnings") or []),
                        *list(page.warnings),
                    ]
                )
            ),
            "_cursor": {
                **cursor,
                "next_offset": int(cursor.get("next_offset") or 0) + page.count,
            },
        }
        if not self.sensitive_results.update(result_id, updated):
            raise KeyError("SENSITIVE_RESULT_EXPIRED")
        self.events.publish(
            "wechat_history_result",
            task_id=entry.task_id,
            conversation_id=entry.conversation_id,
            payload={
                "result_id": result_id,
                **_public_sensitive_payload(updated),
                "sensitive": True,
                "persist": False,
            },
        )
        return {"ok": True, "result_id": result_id, "count": len(combined)}

    def summarize_sensitive_history(self, result_id: str) -> dict[str, Any]:
        from src.core.llm_client import get_llm_client

        entry = self.sensitive_results.get_entry(result_id)
        if entry is None or entry.kind != "wechat_history":
            raise KeyError("SENSITIVE_RESULT_EXPIRED")
        messages = entry.payload.get("messages")
        if not isinstance(messages, list) or not messages:
            raise ValueError("没有可供总结的微信聊天记录")
        client = get_llm_client()
        if not client.available:
            raise ValueError("当前未配置可用的 AI 服务，无法总结")

        chunks = _summary_chunks(messages)
        partials = [
            client.chat(
                chunk,
                system_prompt=(
                    "以下是用户明确授权分析的微信聊天记录。只根据提供内容总结，"
                    "不推断未出现的事实。区分明确事实、待办事项和不确定信息。"
                    "不要进行人格、健康、政治倾向或信用评价。"
                ),
                temperature=0.1,
                max_tokens=1200,
            )
            for chunk in chunks
        ]
        if len(partials) == 1:
            summary = partials[0]
        else:
            summary = client.chat(
                "请合并以下分段总结，按主要话题、关键结论、待办事项、日期和承诺、"
                "需要跟进的问题组织，不新增事实：\n\n"
                + "\n\n---\n\n".join(partials),
                temperature=0.1,
                max_tokens=1600,
            )
        stored = self.database.add_message(
            f"message_{uuid.uuid4().hex}",
            entry.conversation_id,
            role="assistant",
            message_type="result",
            content=summary,
            task_id=entry.task_id,
            metadata={
                "source": "wechat_history_summary",
                "sensitive_source_omitted": True,
                "message_count": len(messages),
            },
        )
        self.events.publish(
            "assistant_message",
            task_id=entry.task_id,
            conversation_id=entry.conversation_id,
            payload={"message": stored},
        )
        return {"ok": True, "message": stored}

    def register_confirmation(self, confirmation_id: str, wait: ConfirmationWait) -> None:
        with self._lock:
            self._confirmations[confirmation_id] = wait

    def unregister_confirmation(self, confirmation_id: str) -> None:
        with self._lock:
            self._confirmations.pop(confirmation_id, None)

    def resolve_confirmation(
        self,
        confirmation_id: str,
        *,
        approved: bool,
        comment: str = "",
        value: str = "",
        action_id: str = "",
    ) -> bool:
        status = "approved" if approved else "rejected"
        if not self.database.resolve_confirmation(confirmation_id, status, comment):
            return False
        confirmation = self.database.get_confirmation(confirmation_id) or {}
        with self._lock:
            wait = self._confirmations.get(confirmation_id)
        if wait is not None:
            with wait.condition:
                wait.approved = approved
                wait.comment = comment
                wait.value = value
                wait.action_id = action_id
                wait.resolved = True
                wait.condition.notify_all()
        task_id = confirmation.get("task_id")
        task = self.database.get_task(str(task_id)) if task_id else None
        self.events.publish(
            "confirmation_resolved",
            task_id=str(task_id) if task_id else None,
            conversation_id=task.get("conversation_id") if task else None,
            payload={
                "confirmation_id": confirmation_id,
                "status": status,
                "comment": comment,
                "value": value,
                "action_id": action_id,
            },
        )
        return True

    def _return_to_idle(self, task_id: str) -> None:
        with self._lock:
            if self._active_task_id is not None and self._active_task_id != task_id:
                return
        task = self.database.get_task(task_id)
        if task is not None:
            self.events.publish(
                "agent_state_changed",
                task_id=task_id,
                conversation_id=task.get("conversation_id"),
                payload={"state": "idle"},
            )

    def close_browser(self) -> bool:
        def close_on_worker() -> bool:
            browser = get_browser_manager()
            if not browser.is_alive():
                return False
            browser.close()
            self.events.publish("browser_closed", payload={})
            return True

        return self._executor.submit(close_on_worker).result(timeout=30)

    def shutdown(self) -> None:
        with self._lock:
            controls = list(self._controls.values())
        for control in controls:
            control.cancel_event.set()
        self.sensitive_results.clear()
        self._executor.shutdown(wait=False, cancel_futures=True)


def _dedupe_sensitive_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[Any, ...]] = set()
    result: list[dict[str, Any]] = []
    for message in messages:
        key = (
            message.get("local_id"),
            message.get("timestamp"),
            message.get("sender_username") or message.get("sender"),
            message.get("content"),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(message)
    return result


def _summary_chunks(messages: list[dict[str, Any]], max_chars: int = 24_000) -> list[str]:
    chunks: list[str] = []
    lines: list[str] = []
    size = 0
    for message in messages:
        sender = (
            message.get("sender_group_nickname")
            or message.get("sender_contact_display")
            or message.get("sender")
            or "未知发送者"
        )
        content = str(message.get("content") or "")[:2000]
        line = json.dumps(
            {
                "time": message.get("time") or message.get("timestamp"),
                "sender": sender,
                "type": message.get("type") or "unknown",
                "content": content,
            },
            ensure_ascii=False,
        )
        if lines and size + len(line) > max_chars:
            chunks.append("\n".join(lines))
            lines = []
            size = 0
        lines.append(line)
        size += len(line)
    if lines:
        chunks.append("\n".join(lines))
    return chunks

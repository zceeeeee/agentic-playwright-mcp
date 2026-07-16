"""Background task execution service used by the desktop application."""

from __future__ import annotations

import os
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable

from src.core.agent_loop import AgentLoop, AgentStep
from src.core.browser_manager import get_browser_manager
from src.core.user_interaction import get_user_interaction_broker
from src.desktop.database import DesktopDatabase
from src.desktop.events import DesktopEventHub
from src.desktop.prompts import parse_desktop_prompt
from src.logging import get_logger

logger = get_logger(__name__)


def _is_wechat_desktop_task(content: str) -> bool:
    normalized = content.strip().lower()
    if any(term in normalized for term in ("怎么", "如何", "安全吗", "恢复方法")):
        return False
    ui_actions = (
        "发送",
        "发消息",
        "发文件",
        "传文件",
        "关注",
        "订阅",
        "私信",
    )
    if ("微信" in normalized or "wechat" in normalized) and any(
        term in normalized for term in ui_actions
    ):
        return True
    return any(term in normalized for term in ("公众号", "服务号")) and any(
        term in normalized for term in ui_actions
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
    blocking: bool = True
    on_resolve: Callable[[dict[str, Any]], None] | None = None


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

    def offer(
        self,
        question: str,
        *,
        title: str = "",
        fields: list[dict[str, Any]] | None = None,
        on_resolve: Callable[[dict[str, Any]], None] | None = None,
    ) -> str:
        """Publish a confirmation while allowing the task to keep running."""
        confirmation_id = f"confirm_{uuid.uuid4().hex}"
        wait = ConfirmationWait(blocking=False, on_resolve=on_resolve)
        prompt = parse_desktop_prompt(question, title=title, fields=fields)
        metadata = {
            key: value for key, value in prompt.items() if key not in {"title", "message"}
        }
        metadata["non_blocking"] = True
        self._service.database.create_confirmation(
            confirmation_id,
            self._control.task_id,
            prompt["title"],
            prompt["message"],
            metadata,
        )
        self._service.register_confirmation(confirmation_id, wait)
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
        return confirmation_id

    def read_data(self) -> dict[str, Any] | None:
        return self._last_data

    def read_events(self) -> list[dict[str, Any]]:
        events = list(self._events)
        self._events.clear()
        return events


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
        with self._lock:
            waits = list(self._confirmations.values())
        for wait in waits:
            with wait.condition:
                wait.condition.notify_all()
        return True

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
            if not wait.blocking:
                self.unregister_confirmation(confirmation_id)
                if wait.on_resolve is not None:
                    resolution = {
                        "approved": approved,
                        "comment": comment,
                        "value": value,
                        "action_id": action_id,
                    }
                    try:
                        wait.on_resolve(resolution)
                    except Exception as exc:
                        logger.exception(
                            "Non-blocking confirmation callback failed: %s", exc
                        )
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
        self._executor.shutdown(wait=False, cancel_futures=True)

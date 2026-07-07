"""Explore executor for synchronous atomic action batches."""

from __future__ import annotations

import time
from typing import Any

from pydantic import ValidationError

from src.core.login_guard import GenericLoginGuard

from .models import (
    Action,
    ActionBatch,
    ActionResult,
    ActionType,
    ErrorCode,
    ExecutionResult,
    SnapshotResponse,
    WaitCondition,
)


class ExploreError(Exception):
    """Base Explore execution error."""

    def __init__(self, message: str, error_code: ErrorCode, ref: str | None = None):
        super().__init__(message)
        self.error_code = error_code
        self.ref = ref


class RefExpiredError(ExploreError):
    """Raised when an action references a ref missing from the current snapshot."""

    def __init__(self, ref: str, snapshot_v: str):
        super().__init__(
            f"Ref {ref} 在当前快照中不存在",
            ErrorCode.REF_EXPIRED,
            ref,
        )
        self.snapshot_v = snapshot_v


class SnapshotStaleError(ExploreError):
    """Raised when an action targets a stale snapshot version."""

    def __init__(self, expected: str, actual: str):
        super().__init__(
            f"版本不匹配: 指令={actual}, 当前={expected}",
            ErrorCode.SNAPSHOT_STALE,
        )
        self.expected = expected
        self.actual = actual


class ElementNotInteractableError(ExploreError):
    """Raised when a referenced element cannot be interacted with."""

    def __init__(self, ref: str, reason: str):
        super().__init__(
            f"元素 {ref} 不可交互: {reason}",
            ErrorCode.ELEMENT_NOT_INTERACTABLE,
            ref,
        )


class ExploreExecutor:
    """Execute Explore actions in sequence with strict snapshot/ref validation."""

    def __init__(
        self,
        page: Any,
        snapshot_generator: Any | None = None,
        config: Any = None,
        browser_manager: Any | None = None,
    ) -> None:
        self._page = page
        self._snapshot_gen = snapshot_generator
        self._config = config
        self._browser_manager = browser_manager
        self._current_snapshot: SnapshotResponse | None = None
        self._valid_refs: set[str] = set()
        self._ref_locator_cache: dict[str, Any] = {}
        self._needs_snapshot = False
        self._login_guard = GenericLoginGuard(
            lambda: self._page,
            browser_manager=browser_manager,
            log_fn=lambda message: None,
            panel_manager_getter=self._get_panel_manager,
        )

    def execute(self, batch: ActionBatch | dict[str, Any]) -> ExecutionResult:
        """Execute an action batch and stop on the first failure."""

        results: list[ActionResult] = []
        try:
            self._needs_snapshot = False
            batch = self._coerce_batch(batch)
            self._validate_batch(batch)
            self._validate_version(batch.actions)
            self._validate_refs(batch.actions)

            terminator_idx = self._find_terminator(batch.actions)
            last_idx = terminator_idx if terminator_idx is not None else len(batch.actions) - 1
            for action in batch.actions[: last_idx + 1]:
                result = self._execute_single(action)
                results.append(result)
                if not result.success:
                    return ExecutionResult(
                        success=False,
                        status="failed",
                        results=results,
                        error=result.error,
                        error_code=result.error_code,
                    )
                if self._needs_snapshot:
                    return ExecutionResult(
                        success=True,
                        status="login_completed",
                        results=results,
                        need_snapshot=True,
                    )

            if terminator_idx is not None:
                return ExecutionResult(
                    success=True,
                    status=self._terminator_status(batch.actions[terminator_idx]),
                    results=results,
                    need_snapshot=True,
                )

            return ExecutionResult(success=True, status="success", results=results)
        except ExploreError as exc:
            return ExecutionResult(
                success=False,
                status="failed",
                results=results,
                error=str(exc),
                error_code=exc.error_code,
            )
        except Exception as exc:
            return ExecutionResult(
                success=False,
                status="failed",
                results=results,
                error=f"执行异常: {exc}",
                error_code=ErrorCode.EXECUTION_FAILED,
            )

    def _coerce_batch(self, batch: ActionBatch | dict[str, Any]) -> ActionBatch:
        if isinstance(batch, ActionBatch):
            return batch
        try:
            return ActionBatch.model_validate(batch)
        except ValidationError as exc:
            raise ExploreError(str(exc), ErrorCode.INVALID_FORMAT) from exc

    def _validate_batch(self, batch: ActionBatch) -> None:
        if not isinstance(batch.actions, list):
            raise ExploreError("actions 必须是列表", ErrorCode.INVALID_FORMAT)
        for action in batch.actions:
            if not action.action:
                raise ExploreError("缺少 action 字段", ErrorCode.INVALID_FORMAT)
            if action.action in {
                ActionType.CLICK,
                ActionType.FILL,
                ActionType.HOVER,
                ActionType.SELECT,
                ActionType.CHECK,
                ActionType.UNCHECK,
            } and not action.ref:
                raise ExploreError(
                    f"操作 {action.action} 缺少 ref",
                    ErrorCode.INVALID_FORMAT,
                )
            if action.action == ActionType.FILL and action.value is None:
                raise ExploreError("fill 操作缺少 value", ErrorCode.INVALID_FORMAT)
            if action.action == ActionType.GOTO and not action.url:
                raise ExploreError("goto 操作缺少 url", ErrorCode.INVALID_FORMAT)

    def _validate_version(self, actions: list[Action]) -> None:
        if not self._current_snapshot:
            return
        current_version = self._current_snapshot.version
        for action in actions:
            if action.snapshot_v and action.snapshot_v != current_version:
                raise SnapshotStaleError(current_version, action.snapshot_v)

    def _validate_refs(self, actions: list[Action]) -> None:
        for action in actions:
            if action.ref and action.ref not in self._valid_refs:
                snapshot_v = self._current_snapshot.version if self._current_snapshot else "unknown"
                raise RefExpiredError(action.ref, snapshot_v)

    def _find_terminator(self, actions: list[Action]) -> int | None:
        for idx, action in enumerate(actions):
            if action.action == ActionType.PANEL_PROMPT:
                return idx
            if action.condition in (WaitCondition.LOAD, WaitCondition.NETWORKIDLE):
                return idx
            if (
                action.action == ActionType.WAIT
                and action.condition in (WaitCondition.LOAD, WaitCondition.NETWORKIDLE)
            ):
                return idx
        return None

    def _terminator_status(self, action: Action) -> str:
        if action.action == ActionType.PANEL_PROMPT:
            return "user_input_received"
        return "navigation_occurred"

    def _execute_single(self, action: Action) -> ActionResult:
        start = time.time()
        try:
            if action.action not in {
                ActionType.GOTO,
                ActionType.BACK,
                ActionType.FORWARD,
                ActionType.PANEL_SHOW,
                ActionType.PANEL_SET_FIELDS,
                ActionType.PANEL_LOG,
                ActionType.PANEL_PROMPT,
            }:
                if self._login_guard.maybe_wait(f"before_{action.action}"):
                    self._needs_snapshot = True
                    return ActionResult(
                        action=action.action,
                        ref=action.ref,
                        success=True,
                        value="login_completed",
                        duration_ms=int((time.time() - start) * 1000),
                    )

            if action.action == ActionType.CLICK:
                self._click(action.ref or "")
            elif action.action == ActionType.FILL:
                self._fill(action.ref or "", action.value or "")
            elif action.action == ActionType.HOVER:
                self._hover(action.ref or "")
            elif action.action == ActionType.SELECT:
                self._select(action.ref or "", action.value or "")
            elif action.action == ActionType.CHECK:
                self._check(action.ref or "")
            elif action.action == ActionType.UNCHECK:
                self._uncheck(action.ref or "")
            elif action.action == ActionType.GOTO:
                self._goto(action.url or "")
            elif action.action == ActionType.BACK:
                self._page.go_back()
            elif action.action == ActionType.FORWARD:
                self._page.go_forward()
            elif action.action == ActionType.SCROLL:
                self._scroll(action.direction or "down", action.amount or 600)
            elif action.action == ActionType.WAIT:
                self._wait(action.condition or WaitCondition.NONE, action.timeout, action)
            elif action.action == ActionType.SCREENSHOT:
                self._page.screenshot(path=action.path)
            elif action.action == ActionType.SNAPSHOT:
                if self._snapshot_gen is not None:
                    self.update_snapshot(self._snapshot_gen.snapshot(self._page))
            elif action.action == ActionType.PANEL_SHOW:
                self._panel_show(action)
            elif action.action == ActionType.PANEL_SET_FIELDS:
                self._panel_set_fields(action)
            elif action.action == ActionType.PANEL_LOG:
                self._panel_log(action)
            elif action.action == ActionType.PANEL_PROMPT:
                answer = self._panel_prompt(action)
                return ActionResult(
                    action=action.action,
                    ref=action.ref,
                    success=True,
                    value=answer,
                    duration_ms=int((time.time() - start) * 1000),
                )
            else:
                raise ExploreError(
                    f"未知操作类型: {action.action}",
                    ErrorCode.INVALID_FORMAT,
                )

            if action.action not in {
                ActionType.PANEL_SHOW,
                ActionType.PANEL_SET_FIELDS,
                ActionType.PANEL_LOG,
                ActionType.PANEL_PROMPT,
                ActionType.SCREENSHOT,
                ActionType.SNAPSHOT,
            }:
                if self._login_guard.maybe_wait(f"after_{action.action}"):
                    self._needs_snapshot = True

            return ActionResult(
                action=action.action,
                ref=action.ref,
                success=True,
                duration_ms=int((time.time() - start) * 1000),
            )
        except ExploreError as exc:
            return ActionResult(
                action=action.action,
                ref=action.ref,
                success=False,
                error=str(exc),
                error_code=exc.error_code,
                duration_ms=int((time.time() - start) * 1000),
            )
        except Exception as exc:
            return ActionResult(
                action=action.action,
                ref=action.ref,
                success=False,
                error=str(exc),
                error_code=ErrorCode.EXECUTION_FAILED,
                duration_ms=int((time.time() - start) * 1000),
            )

    def _get_locator(self, ref: str) -> Any:
        if ref in self._ref_locator_cache:
            return self._ref_locator_cache[ref]
        locator = self._page.locator(f'[data-explore-ref="{ref}"]')
        self._ref_locator_cache[ref] = locator
        return locator

    def _click(self, ref: str) -> None:
        self._get_locator(ref).click(timeout=self._action_timeout())

    def _fill(self, ref: str, value: str) -> None:
        self._get_locator(ref).fill(value, timeout=self._action_timeout())

    def _hover(self, ref: str) -> None:
        self._get_locator(ref).hover(timeout=self._action_timeout())

    def _select(self, ref: str, value: str) -> None:
        self._get_locator(ref).select_option(value, timeout=self._action_timeout())

    def _check(self, ref: str) -> None:
        self._get_locator(ref).check(timeout=self._action_timeout())

    def _uncheck(self, ref: str) -> None:
        self._get_locator(ref).uncheck(timeout=self._action_timeout())

    def _goto(self, url: str) -> None:
        self._page.goto(url, wait_until="load")

    def _scroll(self, direction: str, amount: int) -> None:
        delta = amount if direction == "down" else -amount
        self._page.mouse.wheel(0, delta)

    def _wait(self, condition: WaitCondition | str, timeout: int | None, action: Action) -> None:
        timeout = timeout or self._wait_timeout(condition)
        if condition == WaitCondition.LOAD:
            self._page.wait_for_load_state("load", timeout=timeout)
        elif condition == WaitCondition.NETWORKIDLE:
            self._page.wait_for_load_state("networkidle", timeout=timeout)
        elif condition == WaitCondition.SELECTOR_VISIBLE and action.ref:
            self._get_locator(action.ref).wait_for(state="visible", timeout=timeout)
        elif condition == WaitCondition.TEXT_VISIBLE and action.value:
            self._page.get_by_text(action.value).wait_for(state="visible", timeout=timeout)
        elif timeout:
            self._page.wait_for_timeout(timeout)

    def _get_panel_manager(self):
        from src.panel import get_panel_manager

        return get_panel_manager()

    def _panel_show(self, action: Action) -> None:
        pm = self._get_panel_manager()
        if action.title:
            pm.set_title(self._page, action.title)
        if action.value:
            pm.log(self._page, action.value)
        pm.toggle(self._page, True)

    def _panel_prompt(self, action: Action) -> str:
        pm = self._get_panel_manager()
        if action.title:
            pm.set_title(self._page, action.title)
        pm.toggle(self._page, True)
        question = action.value or "Please provide the information needed to continue."
        return str(pm.prompt(self._page, question) or "")

    def _panel_set_fields(self, action: Action) -> None:
        pm = self._get_panel_manager()
        if action.title:
            pm.set_title(self._page, action.title)
        pm.set_fields(self._page, action.fields or [])
        pm.toggle(self._page, True)

    def _panel_log(self, action: Action) -> None:
        pm = self._get_panel_manager()
        if action.title:
            pm.set_title(self._page, action.title)
        pm.log(self._page, action.value or "")

    def update_snapshot(self, snapshot: SnapshotResponse) -> None:
        self._current_snapshot = snapshot
        self._valid_refs = self._extract_all_refs(snapshot.nodes)
        self._ref_locator_cache.clear()

    def _extract_all_refs(self, nodes) -> set[str]:
        refs: set[str] = set()
        for node in nodes:
            if node.ref:
                refs.add(node.ref)
            refs.update(self._extract_all_refs(node.children))
        return refs

    def get_ref_locator_mapping(self) -> dict[str, str]:
        mapping = {}
        for ref, locator in self._ref_locator_cache.items():
            try:
                mapping[ref] = locator.evaluate(
                    """
                    el => {
                      if (el.id) return '#' + CSS.escape(el.id);
                      return el.getAttribute('data-explore-ref')
                        ? `[data-explore-ref="${el.getAttribute('data-explore-ref')}"]`
                        : '';
                    }
                    """
                )
            except Exception:
                continue
        return {key: value for key, value in mapping.items() if value}

    def _action_timeout(self) -> int:
        return int(getattr(self._config, "action_timeout", 15000))

    def _wait_timeout(self, condition: WaitCondition | str) -> int:
        if condition == WaitCondition.LOAD:
            return int(getattr(self._config, "wait_for_load_timeout", 15000))
        if condition == WaitCondition.NETWORKIDLE:
            return int(getattr(self._config, "wait_for_networkidle_timeout", 15000))
        return int(getattr(self._config, "action_timeout", 15000))

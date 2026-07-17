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

# 需要 ref 的动作类型
_REF_REQUIRED_ACTIONS = frozenset({
    ActionType.CLICK,
    ActionType.FILL,
    ActionType.HOVER,
    ActionType.SELECT,
    ActionType.CHECK,
    ActionType.UNCHECK,
    ActionType.DOUBLE_CLICK,
    ActionType.DRAG,
    ActionType.UPLOAD,
})

# 用户输入类终止符（页面不变，不需要重新快照）
_USER_INPUT_TERMINATORS = frozenset({
    ActionType.PAUSE_FOR_INPUT,
})


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
        self._ref_role_map: dict[str, tuple[str, str]] = {}  # ref → (role, name)
        self._needs_snapshot = False
        self._deep_scan_requested = False
        # Explore 模式禁用 login_guard，因为 Explore 本身有 pause_for_input 机制处理登录
        # login_guard 会误检测页面上的"登录"文字，导致所有操作被跳过
        self._login_guard = GenericLoginGuard(
            lambda: self._page,
            browser_manager=browser_manager,
            log_fn=lambda message: None,
            panel_manager_getter=self._get_panel_manager,
            enabled=False,
        )

    def execute(self, batch: ActionBatch | dict[str, Any]) -> ExecutionResult:
        """Execute an action batch and stop on the first failure."""

        results: list[ActionResult] = []
        try:
            self._needs_snapshot = False
            self._deep_scan_requested = False
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
                if self._deep_scan_requested:
                    return ExecutionResult(
                        success=True,
                        status="deep_scan_completed",
                        results=results,
                        need_snapshot=True,
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
        if isinstance(batch, list):
            batch = {"actions": batch}
        elif isinstance(batch, dict):
            if "actions" in batch and isinstance(batch.get("actions"), dict):
                batch = {**batch, "actions": [batch["actions"]]}
            elif "actions" not in batch and "action" in batch:
                batch = {"actions": [batch]}
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
            if action.action in _REF_REQUIRED_ACTIONS and not action.ref:
                raise ExploreError(
                    f"操作 {action.action} 缺少 ref",
                    ErrorCode.INVALID_FORMAT,
                )
            if action.action == ActionType.FILL and action.value is None:
                raise ExploreError("fill 操作缺少 value", ErrorCode.INVALID_FORMAT)
            if action.action == ActionType.TYPE and action.value is None:
                raise ExploreError("type 操作缺少 value", ErrorCode.INVALID_FORMAT)
            if action.action == ActionType.GOTO and not action.url:
                raise ExploreError("goto 操作缺少 url", ErrorCode.INVALID_FORMAT)
            if action.action == ActionType.KEYBOARD and not action.value:
                raise ExploreError("keyboard 操作缺少 value", ErrorCode.INVALID_FORMAT)
            if action.action == ActionType.UPLOAD and not action.value:
                raise ExploreError("upload 操作缺少 value (文件路径)", ErrorCode.INVALID_FORMAT)
            if action.action == ActionType.DRAG and not action.value:
                raise ExploreError("drag 操作缺少 value (目标 ref)", ErrorCode.INVALID_FORMAT)
            if action.action == ActionType.CLICK_AT and (
                action.x is None or action.y is None
            ):
                raise ExploreError("click_at 操作缺少 x/y 坐标", ErrorCode.INVALID_FORMAT)
            if action.action == ActionType.DIALOG and not action.dialog_action:
                raise ExploreError("dialog 操作缺少 dialog_action (accept/dismiss)", ErrorCode.INVALID_FORMAT)

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
            # drag 的 value 是目标 ref，也需要校验
            if action.action == ActionType.DRAG and action.value and action.value not in self._valid_refs:
                snapshot_v = self._current_snapshot.version if self._current_snapshot else "unknown"
                raise RefExpiredError(action.value, snapshot_v)

    def _find_terminator(self, actions: list[Action]) -> int | None:
        for idx, action in enumerate(actions):
            if action.action in _USER_INPUT_TERMINATORS:
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
        if action.action in _USER_INPUT_TERMINATORS:
            return "user_input_received"
        return "navigation_occurred"

    def _execute_single(self, action: Action) -> ActionResult:
        start = time.time()
        try:
            if action.action not in {
                ActionType.GOTO,
                ActionType.BACK,
                ActionType.FORWARD,
                ActionType.EVALUATE,
                ActionType.DIALOG,
                ActionType.SCREENSHOT,
                ActionType.SNAPSHOT,
                ActionType.PAUSE_FOR_INPUT,
                ActionType.REQUEST_DEEP_SCAN,
                ActionType.COMPLETE,
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
            elif action.action == ActionType.REQUEST_DEEP_SCAN:
                if self._snapshot_gen is not None:
                    self.update_snapshot(self._snapshot_gen.force_deep_scan(self._page))
                    self._deep_scan_requested = True
                    return ActionResult(
                        action=action.action,
                        ref=action.ref,
                        success=True,
                        value="deep_scan_completed",
                        duration_ms=int((time.time() - start) * 1000),
                    )
                raise ExploreError(
                    "深度扫描不可用: SnapshotGenerator 未配置",
                    ErrorCode.EXECUTION_FAILED,
                )
            elif action.action == ActionType.COMPLETE:
                return ActionResult(
                    action=action.action,
                    ref=action.ref,
                    success=True,
                    value=action.value or "task_completed",
                    duration_ms=int((time.time() - start) * 1000),
                )
            # ── 新增动作类型 ──
            elif action.action == ActionType.DOUBLE_CLICK:
                self._double_click(action.ref or "")
            elif action.action == ActionType.KEYBOARD:
                self._keyboard(action.value or "", action.delay)
            elif action.action == ActionType.DRAG:
                self._drag(action.ref or "", action.value or "")
            elif action.action == ActionType.UPLOAD:
                self._upload(action.ref or "", action.value or "")
            elif action.action == ActionType.EVALUATE:
                eval_result = self._evaluate(action.value or "")
                return ActionResult(
                    action=action.action,
                    ref=action.ref,
                    success=True,
                    value=str(eval_result) if eval_result is not None else None,
                    duration_ms=int((time.time() - start) * 1000),
                )
            elif action.action == ActionType.PAUSE_FOR_INPUT:
                answer = self._pause_for_input(action)
                return ActionResult(
                    action=action.action,
                    ref=action.ref,
                    success=True,
                    value=answer,
                    duration_ms=int((time.time() - start) * 1000),
                )
            elif action.action == ActionType.CLICK_AT:
                self._click_at(action.x or 0, action.y or 0)
            elif action.action == ActionType.TYPE:
                self._type(action.ref or "", action.value or "", action.delay)
            elif action.action == ActionType.DIALOG:
                self._handle_dialog(action)
            else:
                raise ExploreError(
                    f"未知操作类型: {action.action}",
                    ErrorCode.INVALID_FORMAT,
                )

            if action.action not in {
                ActionType.SCREENSHOT,
                ActionType.SNAPSHOT,
                ActionType.EVALUATE,
                ActionType.DIALOG,
                ActionType.PAUSE_FOR_INPUT,
                ActionType.REQUEST_DEEP_SCAN,
                ActionType.COMPLETE,
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
        # 优先用 data-explore-ref 属性定位（由 _sync_refs_to_dom 添加）
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
        import logging
        logger = logging.getLogger(__name__)
        self._page.goto(url, wait_until="load")
        # SPA 页面 load 后内容可能尚未渲染，等待网络空闲和 DOM 内容
        try:
            self._page.wait_for_load_state("networkidle", timeout=10_000)
        except Exception:
            logger.debug("networkidle wait timed out for %s", url)
        try:
            self._page.wait_for_function(
                "() => document.body && document.body.children.length >= 2",
                timeout=5000,
            )
        except Exception:
            logger.debug("DOM content wait timed out for %s", url)
        # 诊断：输出页面实际状态
        try:
            diag = self._page.evaluate(
                "() => ({"
                "  url: location.href,"
                "  title: document.title,"
                "  bodyChildren: document.body ? document.body.children.length : -1,"
                "  bodyHTML: document.body ? document.body.innerHTML.length : 0,"
                "})"
            )
            logger.info("After goto %s: %s", url, diag)
        except Exception as exc:
            logger.warning("Post-goto diagnostic failed: %s", exc)

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

    # ── 新增动作执行方法 ──

    def _double_click(self, ref: str) -> None:
        self._get_locator(ref).dblclick(timeout=self._action_timeout())

    def _keyboard(self, value: str, delay: int | None = None) -> None:
        kwargs: dict[str, Any] = {}
        if delay:
            kwargs["delay"] = delay
        self._page.keyboard.press(value, **kwargs)

    def _drag(self, source_ref: str, target_ref: str) -> None:
        source = self._get_locator(source_ref)
        target = self._get_locator(target_ref)
        source.drag_to(target, timeout=self._action_timeout())

    def _upload(self, ref: str, file_path: str) -> None:
        self._get_locator(ref).set_input_files(file_path, timeout=self._action_timeout())

    def _evaluate(self, expression: str) -> Any:
        return self._page.evaluate(expression)

    def _pause_for_input(self, action: Action) -> str:
        """暂停等待用户输入，页面不变（不触发 need_snapshot）。

        支持两种交互模式：
        - 简单提问: value 是问题文本，弹出输入框
        - 结构化表单: fields 提供字段定义，弹出表单
        """
        pm = self._get_panel_manager()
        if action.title:
            pm.set_title(self._page, action.title)
        pm.toggle(self._page, True)
        # 结构化表单模式
        if action.fields:
            pm.set_fields(self._page, action.fields)
            return str(pm.prompt(self._page, action.value or "请填写以下信息") or "")
        # 简单提问模式
        question = action.value or "请提供需要的信息以继续。"
        return str(pm.prompt(self._page, question) or "")

    def _click_at(self, x: int, y: int) -> None:
        self._page.mouse.click(x, y)

    def _type(self, ref: str, value: str, delay: int | None = None) -> None:
        kwargs: dict[str, Any] = {}
        if delay:
            kwargs["delay"] = delay
        self._get_locator(ref).press_sequentially(value, **kwargs)

    def _handle_dialog(self, action: Action) -> None:
        """响应浏览器原生对话框 (alert/confirm/prompt)。"""
        # 等待对话框出现（短超时）
        try:
            dialog = self._page.wait_for_event(
                "dialog", timeout=action.timeout or 3000
            )
        except Exception:
            return  # 没有对话框出现，忽略
        if action.dialog_action == "accept":
            dialog.accept(action.value or "")
        else:
            dialog.dismiss()

    def update_snapshot(self, snapshot: SnapshotResponse) -> None:
        self._current_snapshot = snapshot
        self._valid_refs = self._extract_all_refs(snapshot.nodes)
        self._ref_role_map = self._build_ref_role_map(snapshot.nodes)
        self._ref_locator_cache.clear()

    def _extract_all_refs(self, nodes) -> set[str]:
        refs: set[str] = set()
        for node in nodes:
            if node.ref:
                refs.add(node.ref)
            refs.update(self._extract_all_refs(node.children))
        return refs

    def _build_ref_role_map(self, nodes) -> dict[str, tuple[str, str]]:
        """建立 ref → (role, name) 映射，用于 get_by_role 定位。"""
        mapping: dict[str, tuple[str, str]] = {}
        for node in self._iter_nodes(nodes):
            if node.ref:
                mapping[node.ref] = (node.role, node.name)
        return mapping

    def _iter_nodes(self, nodes):
        for node in nodes:
            yield node
            yield from self._iter_nodes(node.children)

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

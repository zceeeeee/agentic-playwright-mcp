"""Explore mode data models."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class SnapshotMode(str, Enum):
    """Snapshot output mode."""

    FULL = "full"
    COMPACT = "compact"


class ActionType(str, Enum):
    """Atomic Explore action type."""

    CLICK = "click"
    FILL = "fill"
    HOVER = "hover"
    SELECT = "select"
    CHECK = "check"
    UNCHECK = "uncheck"
    GOTO = "goto"
    BACK = "back"
    FORWARD = "forward"
    SCROLL = "scroll"
    SNAPSHOT = "snapshot"
    WAIT = "wait"
    SCREENSHOT = "screenshot"
    # Phase 1: 新增动作类型
    DOUBLE_CLICK = "double_click"
    KEYBOARD = "keyboard"
    DRAG = "drag"
    UPLOAD = "upload"
    EVALUATE = "evaluate"
    PAUSE_FOR_INPUT = "pause_for_input"
    CLICK_AT = "click_at"
    TYPE = "type"
    DIALOG = "dialog"
    REQUEST_DEEP_SCAN = "request_deep_scan"
    COMPLETE = "complete"


class WaitCondition(str, Enum):
    """Wait condition used by navigation terminators and wait actions."""

    NONE = "none"
    LOAD = "load"
    NETWORKIDLE = "networkidle"
    SELECTOR_VISIBLE = "selector_visible"
    TEXT_VISIBLE = "text_visible"


class ErrorCode(str, Enum):
    """Explore execution error codes."""

    REF_EXPIRED = "REF_EXPIRED"
    SNAPSHOT_STALE = "SNAPSHOT_STALE"
    ELEMENT_NOT_INTERACTABLE = "ELEMENT_NOT_INTERACTABLE"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    INVALID_FORMAT = "INVALID_FORMAT"


class AriaNode(BaseModel):
    """ARIA semantic tree node."""

    role: str = Field(..., description="ARIA role")
    name: str = Field("", description="Accessible name")
    ref: Optional[str] = Field(None, description="Explore ref id")
    tag: Optional[str] = Field(None, description="HTML tag")
    selector: Optional[str] = Field(None, description="Best-effort CSS selector")
    placeholder: Optional[str] = Field(None, description="Input placeholder")
    disabled: bool = Field(False, description="Whether element is disabled")
    level: Optional[int] = Field(None, description="Heading level")
    context: Optional[str] = Field(None, description="Parent semantic context")
    children: list["AriaNode"] = Field(default_factory=list)


class SnapshotResponse(BaseModel):
    """ARIA snapshot response."""

    version: str = Field(..., description="Snapshot version, e.g. snapshot_v3")
    mode: SnapshotMode = Field(..., description="Snapshot mode")
    url: str = ""
    title: str = ""
    nodes: list[AriaNode] = Field(default_factory=list)
    interactive_count: int = 0
    has_modal: bool = False
    deep_scanned: bool = Field(False, description="是否经过深度扫描")
    timestamp: datetime = Field(default_factory=datetime.now)


class FocusTarget(BaseModel):
    """Snapshot focus target."""

    type: str = Field(..., description="ref, role_name, or position")
    value: str
    scope: str = Field("children", description="self, parent, children, siblings")


class Action(BaseModel):
    """Atomic Explore action."""

    model_config = ConfigDict(use_enum_values=True)

    action: ActionType
    ref: Optional[str] = None
    value: Optional[str] = None
    url: Optional[str] = None
    direction: Optional[str] = None
    amount: Optional[int] = None
    condition: Optional[WaitCondition] = None
    timeout: Optional[int] = None
    path: Optional[str] = None
    title: Optional[str] = None
    fields: Optional[list[dict[str, Any]]] = None
    snapshot_v: Optional[str] = None
    snapshot_mode: Optional[SnapshotMode] = None
    focus: Optional[FocusTarget] = None
    # 模型意图与推理
    intent: Optional[str] = Field(None, description="模型对这步操作的意图说明")
    reasoning: Optional[str] = Field(None, description="模型的推理过程")
    # click_at 专用：视口坐标
    x: Optional[int] = Field(None, description="click_at 视口 X 坐标")
    y: Optional[int] = Field(None, description="click_at 视口 Y 坐标")
    # dialog 专用：对话框响应
    dialog_action: Optional[str] = Field(None, description="dialog 动作: accept / dismiss")
    # keyboard 专用：按键延迟
    delay: Optional[int] = Field(None, description="keyboard 逐键延迟(ms)")


class ActionBatch(BaseModel):
    """Batch of atomic Explore actions."""

    actions: list[Action]
    task_complete: bool = Field(
        False,
        description="Whether the current page already proves that the user task is complete",
    )
    completion_summary: Optional[str] = Field(
        None,
        description="Short user-facing summary when task_complete is true",
    )
    task_id: Optional[str] = None
    plan_intent: Optional[str] = Field(None, description="本批次的整体意图描述")
    steps_description: Optional[str] = Field(None, description="步骤说明")


class ActionResult(BaseModel):
    """Single action execution result."""

    model_config = ConfigDict(use_enum_values=True)

    action: ActionType
    ref: Optional[str] = None
    success: bool
    error: Optional[str] = None
    error_code: Optional[ErrorCode] = None
    value: Optional[str] = None
    duration_ms: int = 0


class ActionRecord(BaseModel):
    """轻量级操作记录，用于注入 LLM prompt 避免重复失败。"""

    action: str = Field(..., description="动作类型")
    ref: Optional[str] = Field(None, description="元素 ref")
    value: Optional[str] = Field(None, description="填充值或按键")
    url: Optional[str] = Field(None, description="导航 URL")
    success: bool = Field(..., description="是否成功")
    error: Optional[str] = Field(None, description="失败原因")
    step_number: int = Field(0, description="所在步骤编号")


class ExecutionResult(BaseModel):
    """Action batch execution result."""

    model_config = ConfigDict(use_enum_values=True)

    success: bool
    status: str = Field(..., description="success, navigation_occurred, or failed")
    results: list[ActionResult] = Field(default_factory=list)
    error: Optional[str] = None
    error_code: Optional[ErrorCode] = None
    need_snapshot: bool = False
    new_snapshot: Optional[SnapshotResponse] = None


class ElementInfo(BaseModel):
    """Element info persisted in Explore experience."""

    selector: str
    role: str = ""
    name: str = ""
    tag: str = ""


class ExploreExperience(BaseModel):
    """Explore experience entry."""

    id: str
    task: str
    site: str
    url_pattern: str = ""
    actions: list[Action] = Field(default_factory=list)
    action_count: int = 0
    element_map: dict[str, ElementInfo] = Field(default_factory=dict)
    snapshot_roles: list[str] = Field(default_factory=list)
    snapshot_names: list[str] = Field(default_factory=list)
    success_count: int = 1
    fail_count: int = 0
    confidence: float = 0.7
    last_used: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.now)
    from_explore: bool = True
    status: str = Field("active", description="active or deprecated")


class Skill(BaseModel):
    """Script skill upgraded from Explore experience."""

    id: str
    name: str
    triggers: list[str] = Field(default_factory=list)
    url_patterns: list[str] = Field(default_factory=list)
    source_code: str = ""
    source_file: Optional[str] = None
    from_explore: bool = False
    confidence: float = 0.9
    auto_generated: bool = False
    created_at: datetime = Field(default_factory=datetime.now)


class ExploreConfig(BaseModel):
    """Explore mode configuration."""

    snapshot_max_elements: int = 50
    compact_viewport_margin: int = 50
    max_retries: int = 3
    action_timeout: int = 15000
    wait_for_load_timeout: int = 15000
    wait_for_networkidle_timeout: int = 15000
    experience_save_threshold: int = 2
    experience_upgrade_threshold: int = 3
    experience_confidence_threshold: float = 0.8
    experience_deprecated_threshold: float = 0.3
    min_interactive_threshold: int = 5
    deep_scan_max_elements: int = 150
    interactive_roles: list[str] = Field(
        default_factory=lambda: [
            "button",
            "link",
            "textbox",
            "searchbox",
            "checkbox",
            "radio",
            "combobox",
            "listbox",
            "menuitem",
            "tab",
            "slider",
            "spinbutton",
        ]
    )

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
    PANEL_SHOW = "panel_show"
    PANEL_PROMPT = "panel_prompt"
    PANEL_SET_FIELDS = "panel_set_fields"
    PANEL_LOG = "panel_log"


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


class ActionBatch(BaseModel):
    """Batch of atomic Explore actions."""

    actions: list[Action]
    task_id: Optional[str] = None


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

# Explore 模式开发任务书

## 1. 文件结构规划

```
src/
├── core/
│   ├── explore/
│   │   ├── __init__.py
│   │   ├── models.py           # 数据模型定义
│   │   ├── snapshot.py         # ARIA 快照生成器
│   │   ├── executor.py         # Explore 执行器
│   │   ├── experience.py       # 经验管理器
│   │   └── ref_generator.py    # ref 生成器
│   ├── agent_loop.py           # 改造：集成 Explore 模式
│   └── dom_explorer.py         # 改造：输出 ARIA 格式
├── config.py                   # 改造：添加 Explore 配置项
└── tests/
    └── test_explore/
        ├── test_models.py
        ├── test_snapshot.py
        ├── test_executor.py
        └── test_experience.py
```

---

## 2. 数据模型定义

### 2.1 `src/core/explore/models.py`

```python
"""Explore 模式数据模型定义。"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# 枚举类型
# ---------------------------------------------------------------------------


class SnapshotMode(str, Enum):
    """快照模式。"""
    FULL = "full"
    COMPACT = "compact"


class ActionType(str, Enum):
    """操作类型。"""
    # 基础操作
    CLICK = "click"
    FILL = "fill"
    HOVER = "hover"
    SELECT = "select"
    CHECK = "check"
    UNCHECK = "uncheck"

    # 导航操作
    GOTO = "goto"
    BACK = "back"
    FORWARD = "forward"
    SCROLL = "scroll"

    # 状态操作
    SNAPSHOT = "snapshot"
    WAIT = "wait"
    SCREENSHOT = "screenshot"


class WaitCondition(str, Enum):
    """等待条件。"""
    NONE = "none"
    LOAD = "load"
    NETWORKIDLE = "networkidle"
    SELECTOR_VISIBLE = "selector_visible"
    TEXT_VISIBLE = "text_visible"


class ErrorCode(str, Enum):
    """错误码。"""
    REF_EXPIRED = "REF_EXPIRED"
    SNAPSHOT_STALE = "SNAPSHOT_STALE"
    ELEMENT_NOT_INTERACTABLE = "ELEMENT_NOT_INTERACTABLE"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    INVALID_FORMAT = "INVALID_FORMAT"


# ---------------------------------------------------------------------------
# 快照相关模型
# ---------------------------------------------------------------------------


class AriaNode(BaseModel):
    """ARIA 语义树节点。"""
    role: str = Field(..., description="ARIA 角色")
    name: str = Field("", description="元素名称")
    ref: Optional[str] = Field(None, description="唯一引用 ID")
    tag: Optional[str] = Field(None, description="HTML 标签")
    placeholder: Optional[str] = Field(None, description="输入框占位符")
    disabled: bool = Field(False, description="是否禁用")
    level: Optional[int] = Field(None, description="heading 层级")
    context: Optional[str] = Field(None, description="父级语义上下文")
    children: list[AriaNode] = Field(default_factory=list, description="子节点")


class SnapshotResponse(BaseModel):
    """快照响应。"""
    version: str = Field(..., description="快照版本号，如 snapshot_v3")
    mode: SnapshotMode = Field(..., description="快照模式")
    url: str = Field("", description="当前 URL")
    title: str = Field("", description="页面标题")
    nodes: list[AriaNode] = Field(default_factory=list, description="ARIA 语义树")
    interactive_count: int = Field(0, description="可交互元素数量")
    has_modal: bool = Field(False, description="是否有模态框")
    timestamp: datetime = Field(default_factory=datetime.now)


# ---------------------------------------------------------------------------
# 操作指令模型
# ---------------------------------------------------------------------------


class FocusTarget(BaseModel):
    """聚焦目标。"""
    type: str = Field(..., description="聚焦类型: ref, role_name, position")
    value: str = Field(..., description="目标值")
    scope: str = Field("children", description="范围: self, parent, children, siblings")


class Action(BaseModel):
    """原子操作指令。"""
    action: ActionType = Field(..., description="操作类型")
    ref: Optional[str] = Field(None, description="目标元素 ref")
    value: Optional[str] = Field(None, description="操作值（fill/select 时必填）")
    url: Optional[str] = Field(None, description="目标 URL（goto 时必填）")
    direction: Optional[str] = Field(None, description="滚动方向（scroll 时必填）")
    amount: Optional[int] = Field(None, description="滚动距离")
    condition: Optional[WaitCondition] = Field(None, description="等待条件")
    timeout: Optional[int] = Field(None, description="超时时间（毫秒）")
    path: Optional[str] = Field(None, description="截图保存路径")
    snapshot_v: Optional[str] = Field(None, description="快照版本号")
    snapshot_mode: Optional[SnapshotMode] = Field(None, description="快照模式")
    focus: Optional[FocusTarget] = Field(None, description="聚焦目标")

    class Config:
        use_enum_values = True


class ActionBatch(BaseModel):
    """操作批次（原子操作数组）。"""
    actions: list[Action] = Field(..., description="操作列表")
    task_id: Optional[str] = Field(None, description="任务 ID")


# ---------------------------------------------------------------------------
# 执行结果模型
# ---------------------------------------------------------------------------


class ActionResult(BaseModel):
    """单个操作执行结果。"""
    action: ActionType
    ref: Optional[str] = None
    success: bool
    error: Optional[str] = None
    error_code: Optional[ErrorCode] = None
    duration_ms: int = 0


class ExecutionResult(BaseModel):
    """批次执行结果。"""
    success: bool
    status: str = Field(..., description="执行状态: success, navigation_occurred, failed")
    results: list[ActionResult] = Field(default_factory=list)
    error: Optional[str] = None
    error_code: Optional[ErrorCode] = None
    need_snapshot: bool = Field(False, description="是否需要刷新快照")
    new_snapshot: Optional[SnapshotResponse] = Field(None, description="新快照（导航后自动返回）")


# ---------------------------------------------------------------------------
# 经验模型
# ---------------------------------------------------------------------------


class ElementInfo(BaseModel):
    """元素信息（用于经验存储）。"""
    selector: str = Field(..., description="CSS Selector")
    role: str = Field("", description="ARIA 角色")
    name: str = Field("", description="元素名称")
    tag: str = Field("", description="HTML 标签")


class ExploreExperience(BaseModel):
    """Explore 经验条目。"""
    id: str = Field(..., description="经验 ID")
    task: str = Field(..., description="用户任务描述")
    site: str = Field(..., description="站点域名")
    url_pattern: str = Field("", description="URL 匹配模式")

    # 操作序列
    actions: list[Action] = Field(default_factory=list)
    action_count: int = Field(0)

    # 元素映射
    element_map: dict[str, ElementInfo] = Field(default_factory=dict)

    # 快照上下文（用于相似性匹配）
    snapshot_roles: list[str] = Field(default_factory=list)
    snapshot_names: list[str] = Field(default_factory=list)

    # 质量指标
    success_count: int = Field(1)
    fail_count: int = Field(0)
    confidence: float = Field(0.7)
    last_used: Optional[datetime] = None

    # 元数据
    created_at: datetime = Field(default_factory=datetime.now)
    from_explore: bool = Field(True)
    status: str = Field("active", description="状态: active, deprecated")


class Skill(BaseModel):
    """脚本技能（从经验升级）。"""
    id: str = Field(..., description="技能 ID")
    name: str = Field(..., description="技能名称")
    triggers: list[str] = Field(default_factory=list, description="触发词")
    url_patterns: list[str] = Field(default_factory=list, description="URL 匹配模式")
    source_code: str = Field("", description="Python 脚本代码")
    source_file: Optional[str] = Field(None, description="脚本文件路径")
    from_explore: bool = Field(False, description="是否从 Explore 经验生成")
    confidence: float = Field(0.9)
    auto_generated: bool = Field(False)
    created_at: datetime = Field(default_factory=datetime.now)


# ---------------------------------------------------------------------------
# 配置模型
# ---------------------------------------------------------------------------


class ExploreConfig(BaseModel):
    """Explore 模式配置。"""
    # 快照配置
    snapshot_max_elements: int = Field(50, description="快照最大元素数")
    compact_viewport_margin: int = Field(50, description="compact 模式视口边距（px）")

    # 执行配置
    max_retries: int = Field(3, description="最大重试次数")
    action_timeout: int = Field(15000, description="操作超时时间（ms）")
    wait_for_load_timeout: int = Field(15000, description="wait_for=load 超时（ms）")
    wait_for_networkidle_timeout: int = Field(15000, description="wait_for=networkidle 超时（ms）")

    # 经验配置
    experience_save_threshold: int = Field(2, description="经验保存最小操作数")
    experience_upgrade_threshold: int = Field(3, description="经验升级为技能的最小成功次数")
    experience_confidence_threshold: float = Field(0.8, description="经验升级置信度阈值")
    experience_deprecated_threshold: float = Field(0.3, description="经验废弃置信度阈值")

    # 交互角色白名单（compact 模式）
    interactive_roles: list[str] = Field(
        default=[
            "button", "link", "textbox", "searchbox",
            "checkbox", "radio", "combobox", "listbox",
            "menuitem", "tab", "slider", "spinbutton",
        ],
        description="可交互角色白名单"
    )
```

---

## 3. 核心接口定义

### 3.1 `src/core/explore/ref_generator.py`

```python
"""ref 生成器 —— 为 ARIA 快照中的可交互元素分配唯一引用 ID。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import AriaNode


class RefGenerator:
    """ref 生成器。

    生成规则：
    1. 从 e1 开始递增
    2. 只分配给可交互元素
    3. 纯展示元素不分配 ref
    """

    # 可交互角色白名单
    INTERACTIVE_ROLES: set[str] = {
        "button", "link", "textbox", "searchbox",
        "checkbox", "radio", "combobox", "listbox",
        "menu", "menuitem", "tab", "switch",
        "slider", "spinbutton", "option", "treeitem",
    }

    def __init__(self) -> None:
        self._counter: int = 0

    def reset(self) -> None:
        """重置计数器（每次新快照时调用）。"""
        self._counter = 0

    def generate(self, role: str) -> str | None:
        """为元素生成 ref。

        Args:
            role: ARIA 角色

        Returns:
            ref 字符串（如 "e15"），非可交互元素返回 None
        """
        if role not in self.INTERACTIVE_ROLES:
            return None

        self._counter += 1
        return f"e{self._counter}"

    def assign_refs(self, nodes: list[AriaNode]) -> None:
        """为节点树中的可交互元素分配 ref（递归）。

        Args:
            nodes: ARIA 节点列表
        """
        for node in nodes:
            ref = self.generate(node.role)
            if ref:
                node.ref = ref
            if node.children:
                self.assign_refs(node.children)
```

### 3.2 `src/core/explore/snapshot.py`

```python
"""ARIA 快照生成器 —— 从 Playwright Page 生成语义化快照。"""

from __future__ import annotations

import hashlib
from typing import Any, TYPE_CHECKING

from .models import AriaNode, SnapshotMode, SnapshotResponse, FocusTarget
from .ref_generator import RefGenerator

if TYPE_CHECKING:
    from playwright.sync_api import Page


class SnapshotGenerator:
    """ARIA 快照生成器。"""

    # compact 模式的交互角色白名单
    COMPACT_INTERACTIVE_ROLES: set[str] = {
        "button", "link", "textbox", "searchbox",
        "checkbox", "radio", "combobox", "listbox",
        "menuitem", "tab", "slider", "spinbutton",
    }

    def __init__(self, config: Any = None) -> None:
        self._config = config
        self._ref_gen = RefGenerator()
        self._version_counter: int = 0

    def snapshot(
        self,
        page: Page,
        mode: SnapshotMode = SnapshotMode.COMPACT,
        focus: FocusTarget | None = None,
    ) -> SnapshotResponse:
        """生成 ARIA 快照。

        Args:
            page: Playwright Page 实例
            mode: 快照模式
            focus: 聚焦目标

        Returns:
            SnapshotResponse
        """
        # 递增版本号
        self._version_counter += 1
        version = f"snapshot_v{self._version_counter}"

        # 重置 ref 生成器
        self._ref_gen.reset()

        # 提取 ARIA 树
        raw_tree = self._extract_aria_tree(page, focus)

        # 过滤和构建节点
        nodes = self._build_nodes(raw_tree, mode)

        # 分配 ref
        self._ref_gen.assign_refs(nodes)

        # 统计可交互元素数量
        interactive_count = self._count_interactive(nodes)

        # 检测页面状态
        state = self._detect_page_state(page)

        return SnapshotResponse(
            version=version,
            mode=mode,
            url=page.url,
            title=page.title(),
            nodes=nodes,
            interactive_count=interactive_count,
            has_modal=state.get("has_modal", False),
        )

    def _extract_aria_tree(self, page: Page, focus: FocusTarget | None = None) -> dict:
        """从页面提取 ARIA 树（JavaScript 实现）。"""
        js_code = self._build_extraction_js(focus)
        return page.evaluate(js_code)

    def _build_extraction_js(self, focus: FocusTarget | None = None) -> str:
        """构建 ARIA 树提取的 JavaScript 代码。"""
        # TODO: 实现完整的 ARIA 树提取逻辑
        # 参考: https://github.com/nicolo-ribaudo/tc39-proposal-accessibility-object-model
        return """
        (focus) => {
            // 1. 获取根元素（如果有 focus，从 focus 目标开始）
            let root = document.body;
            if (focus) {
                if (focus.type === 'ref') {
                    // 通过 data-ref 属性查找
                    root = document.querySelector(`[data-ref="${focus.value}"]`) || root;
                } else if (focus.type === 'role_name') {
                    // 通过 role 和 name 查找
                    const [role, name] = focus.value.split(':');
                    root = document.querySelector(`[role="${role}"][aria-label="${name}"]`) || root;
                }
            }

            // 2. 递归提取 ARIA 语义
            function extractNode(element, depth = 0) {
                if (depth > 10) return null;  // 防止过深递归

                const role = element.getAttribute('role') || getImplicitRole(element);
                const name = element.getAttribute('aria-label') ||
                             element.getAttribute('title') ||
                             element.textContent?.trim().slice(0, 50) || '';

                const node = {
                    role: role,
                    name: name,
                    tag: element.tagName.toLowerCase(),
                    placeholder: element.getAttribute('placeholder'),
                    disabled: element.disabled || element.getAttribute('aria-disabled') === 'true',
                    children: []
                };

                // 递归处理子节点
                for (const child of element.children) {
                    const childNode = extractNode(child, depth + 1);
                    if (childNode) {
                        node.children.push(childNode);
                    }
                }

                return node;
            }

            function getImplicitRole(element) {
                const tag = element.tagName.toLowerCase();
                const type = element.getAttribute('type');
                const roleMap = {
                    'a': 'link',
                    'button': 'button',
                    'input': type === 'checkbox' ? 'checkbox' : type === 'radio' ? 'radio' : 'textbox',
                    'select': 'combobox',
                    'textarea': 'textbox',
                    'nav': 'navigation',
                    'main': 'main',
                    'header': 'banner',
                    'footer': 'contentinfo',
                    'article': 'article',
                    'section': 'region',
                    'h1': 'heading',
                    'h2': 'heading',
                    'h3': 'heading',
                    'h4': 'heading',
                    'h5': 'heading',
                    'h6': 'heading',
                };
                return roleMap[tag] || 'generic';
            }

            return extractNode(root);
        }
        """

    def _build_nodes(self, raw_tree: dict, mode: SnapshotMode) -> list[AriaNode]:
        """将原始 ARIA 树转换为节点列表。"""
        if not raw_tree:
            return []

        node = self._raw_to_node(raw_tree)

        if mode == SnapshotMode.COMPACT:
            # compact 模式：只保留可交互元素及其父级上下文
            return self._filter_compact([node])

        return [node] if node else []

    def _raw_to_node(self, raw: dict) -> AriaNode | None:
        """将原始字典转换为 AriaNode。"""
        if not raw or not isinstance(raw, dict):
            return None

        children = []
        for child in raw.get("children", []):
            child_node = self._raw_to_node(child)
            if child_node:
                children.append(child_node)

        return AriaNode(
            role=raw.get("role", "generic"),
            name=raw.get("name", ""),
            tag=raw.get("tag"),
            placeholder=raw.get("placeholder"),
            disabled=raw.get("disabled", False),
            children=children,
        )

    def _filter_compact(self, nodes: list[AriaNode]) -> list[AriaNode]:
        """compact 模式过滤：只保留可交互元素及其父级上下文。"""
        result = []
        for node in nodes:
            # 检查是否有可交互子节点
            has_interactive = self._has_interactive_descendant(node)

            # 如果自身可交互或有可交互子节点，保留
            if node.role in self.COMPACT_INTERACTIVE_ROLES or has_interactive:
                # 递归过滤子节点
                filtered_children = self._filter_compact(node.children)

                # 创建过滤后的节点副本
                filtered_node = AriaNode(
                    role=node.role,
                    name=node.name,
                    ref=node.ref,
                    tag=node.tag,
                    placeholder=node.placeholder,
                    disabled=node.disabled,
                    children=filtered_children,
                )
                result.append(filtered_node)

        return result

    def _has_interactive_descendant(self, node: AriaNode) -> bool:
        """检查节点是否有可交互的后代。"""
        for child in node.children:
            if child.role in self.COMPACT_INTERACTIVE_ROLES:
                return True
            if self._has_interactive_descendant(child):
                return True
        return False

    def _count_interactive(self, nodes: list[AriaNode]) -> int:
        """统计可交互元素数量。"""
        count = 0
        for node in nodes:
            if node.ref:
                count += 1
            count += self._count_interactive(node.children)
        return count

    def _detect_page_state(self, page: Page) -> dict:
        """检测页面状态（模态框、抽屉等）。"""
        return page.evaluate("""
            () => ({
                hasModal: Boolean(document.querySelector('[aria-modal="true"], [role="dialog"], .modal, .Modal')),
                hasDrawer: Boolean(document.querySelector('[class*="drawer" i], [class*="sheet" i]')),
                hasDropdown: Boolean(document.querySelector('[role="menu"], [role="listbox"], [class*="dropdown" i]')),
            })
        """)
```

### 3.3 `src/core/explore/executor.py`

```python
"""Explore 执行器 —— 同步顺序执行原子操作数组。"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from .models import (
    Action,
    ActionType,
    ActionResult,
    ActionBatch,
    ErrorCode,
    ExecutionResult,
    SnapshotMode,
    WaitCondition,
)

if TYPE_CHECKING:
    from playwright.sync_api import Page
    from .snapshot import SnapshotGenerator


class ExploreError(Exception):
    """Explore 执行错误基类。"""

    def __init__(self, message: str, error_code: ErrorCode, ref: str | None = None):
        super().__init__(message)
        self.error_code = error_code
        self.ref = ref


class RefExpiredError(ExploreError):
    """ref 已过期错误。"""

    def __init__(self, ref: str, snapshot_v: str):
        super().__init__(
            f"Ref {ref} 在当前快照中不存在",
            ErrorCode.REF_EXPIRED,
            ref,
        )
        self.snapshot_v = snapshot_v


class SnapshotStaleError(ExploreError):
    """快照版本过期错误。"""

    def __init__(self, expected: str, actual: str):
        super().__init__(
            f"版本不匹配: 指令={actual}, 当前={expected}",
            ErrorCode.SNAPSHOT_STALE,
        )
        self.expected = expected
        self.actual = actual


class ElementNotInteractableError(ExploreError):
    """元素不可交互错误。"""

    def __init__(self, ref: str, reason: str):
        super().__init__(
            f"元素 {ref} 不可交互: {reason}",
            ErrorCode.ELEMENT_NOT_INTERACTABLE,
            ref,
        )


class ExploreExecutor:
    """Explore 模式执行器。

    核心约束：
    1. 同步顺序执行（禁止异步并发）
    2. 版本号强校验
    3. ref 硬校验（绝不智能匹配）
    4. 导航终结者机制
    5. 事务回滚
    """

    def __init__(
        self,
        page: Page,
        snapshot_generator: SnapshotGenerator,
        config: Any = None,
    ) -> None:
        self._page = page
        self._snapshot_gen = snapshot_generator
        self._config = config

        # 当前快照状态
        self._current_snapshot = None
        self._valid_refs: set[str] = set()

        # ref → locator 缓存（用于元素映射提取）
        self._ref_locator_cache: dict[str, Any] = {}

    def execute(self, batch: ActionBatch) -> ExecutionResult:
        """执行操作批次。

        Args:
            batch: 操作批次

        Returns:
            ExecutionResult
        """
        results = []

        try:
            # 1. 严格格式校验
            self._validate_batch(batch)

            # 2. 版本号校验
            self._validate_version(batch.actions)

            # 3. Ref 防呆校验
            self._validate_refs(batch.actions)

            # 4. 检测导航终结者
            terminator_idx = self._find_terminator(batch.actions)

            # 5. 执行前置队列
            for i in range(terminator_idx + 1):
                action = batch.actions[i]
                result = self._execute_single(action)
                results.append(result)

                # 如果前置失败，终止执行
                if not result.success:
                    return ExecutionResult(
                        success=False,
                        status="failed",
                        results=results,
                        error=result.error,
                        error_code=result.error_code,
                    )

            # 6. 如果有终结者，执行后返回导航状态
            if terminator_idx is not None:
                return ExecutionResult(
                    success=True,
                    status="navigation_occurred",
                    results=results,
                    need_snapshot=True,
                )

            return ExecutionResult(
                success=True,
                status="success",
                results=results,
            )

        except ExploreError as e:
            return ExecutionResult(
                success=False,
                status="failed",
                results=results,
                error=str(e),
                error_code=e.error_code,
            )
        except Exception as e:
            return ExecutionResult(
                success=False,
                status="failed",
                results=results,
                error=f"执行异常: {e}",
                error_code=ErrorCode.EXECUTION_FAILED,
            )

    def _validate_batch(self, batch: ActionBatch) -> None:
        """校验批次格式。"""
        if not isinstance(batch.actions, list):
            raise ExploreError("actions 必须是列表", ErrorCode.INVALID_FORMAT)

        for action in batch.actions:
            if not action.action:
                raise ExploreError("缺少 action 字段", ErrorCode.INVALID_FORMAT)

            if action.action in (ActionType.CLICK, ActionType.FILL, ActionType.HOVER):
                if not action.ref:
                    raise ExploreError(
                        f"操作 {action.action} 缺少 ref",
                        ErrorCode.INVALID_FORMAT,
                    )

    def _validate_version(self, actions: list[Action]) -> None:
        """校验版本号。"""
        if not self._current_snapshot:
            return

        current_version = self._current_snapshot.version
        for action in actions:
            if action.snapshot_v and action.snapshot_v != current_version:
                raise SnapshotStaleError(current_version, action.snapshot_v)

    def _validate_refs(self, actions: list[Action]) -> None:
        """校验 ref 有效性。"""
        for action in actions:
            if action.ref and action.ref not in self._valid_refs:
                raise RefExpiredError(
                    action.ref,
                    self._current_snapshot.version if self._current_snapshot else "unknown",
                )

    def _find_terminator(self, actions: list[Action]) -> int | None:
        """找到导航终结者的索引。"""
        for i, action in enumerate(actions):
            if action.wait_for in (WaitCondition.LOAD, WaitCondition.NETWORKIDLE):
                return i
        return None

    def _execute_single(self, action: Action) -> ActionResult:
        """执行单个操作。"""
        import time
        start = time.time()

        try:
            if action.action == ActionType.CLICK:
                self._click(action.ref)
            elif action.action == ActionType.FILL:
                self._fill(action.ref, action.value)
            elif action.action == ActionType.HOVER:
                self._hover(action.ref)
            elif action.action == ActionType.SELECT:
                self._select(action.ref, action.value)
            elif action.action == ActionType.CHECK:
                self._check(action.ref)
            elif action.action == ActionType.UNCHECK:
                self._uncheck(action.ref)
            elif action.action == ActionType.GOTO:
                self._goto(action.url)
            elif action.action == ActionType.BACK:
                self._page.go_back()
            elif action.action == ActionType.FORWARD:
                self._page.go_forward()
            elif action.action == ActionType.SCROLL:
                self._scroll(action.direction, action.amount)
            elif action.action == ActionType.WAIT:
                self._wait(action.condition, action.timeout)
            else:
                raise ExploreError(
                    f"未知操作类型: {action.action}",
                    ErrorCode.INVALID_FORMAT,
                )

            duration = int((time.time() - start) * 1000)
            return ActionResult(
                action=action.action,
                ref=action.ref,
                success=True,
                duration_ms=duration,
            )

        except ExploreError as e:
            duration = int((time.time() - start) * 1000)
            return ActionResult(
                action=action.action,
                ref=action.ref,
                success=False,
                error=str(e),
                error_code=e.error_code,
                duration_ms=duration,
            )
        except Exception as e:
            duration = int((time.time() - start) * 1000)
            return ActionResult(
                action=action.action,
                ref=action.ref,
                success=False,
                error=str(e),
                error_code=ErrorCode.EXECUTION_FAILED,
                duration_ms=duration,
            )

    def _get_locator(self, ref: str) -> Any:
        """通过 ref 获取 Playwright Locator。"""
        # 先从缓存查找
        if ref in self._ref_locator_cache:
            return self._ref_locator_cache[ref]

        # 通过 data-ref 属性查找
        locator = self._page.locator(f'[data-ref="{ref}"]')

        # 缓存
        self._ref_locator_cache[ref] = locator

        return locator

    def _click(self, ref: str) -> None:
        """点击元素。"""
        locator = self._get_locator(ref)
        locator.click()

    def _fill(self, ref: str, value: str) -> None:
        """填充输入框。"""
        locator = self._get_locator(ref)
        locator.fill(value)

    def _hover(self, ref: str) -> None:
        """悬停元素。"""
        locator = self._get_locator(ref)
        locator.hover()

    def _select(self, ref: str, value: str) -> None:
        """选择下拉选项。"""
        locator = self._get_locator(ref)
        locator.select_option(value)

    def _check(self, ref: str) -> None:
        """勾选复选框。"""
        locator = self._get_locator(ref)
        locator.check()

    def _uncheck(self, ref: str) -> None:
        """取消勾选。"""
        locator = self._get_locator(ref)
        locator.uncheck()

    def _goto(self, url: str) -> None:
        """导航到 URL。"""
        self._page.goto(url, wait_until="load")

    def _scroll(self, direction: str, amount: int) -> None:
        """滚动页面。"""
        delta = amount if direction == "down" else -amount
        self._page.mouse.wheel(0, delta)

    def _wait(self, condition: WaitCondition, timeout: int | None) -> None:
        """等待条件满足。"""
        timeout = timeout or 15000

        if condition == WaitCondition.LOAD:
            self._page.wait_for_load_state("load", timeout=timeout)
        elif condition == WaitCondition.NETWORKIDLE:
            self._page.wait_for_load_state("networkidle", timeout=timeout)
        elif condition == WaitCondition.SELECTOR_VISIBLE:
            # 需要额外的 ref 参数
            pass
        elif condition == WaitCondition.TEXT_VISIBLE:
            # 需要额外的 value 参数
            pass

    def update_snapshot(self, snapshot) -> None:
        """更新当前快照状态。"""
        self._current_snapshot = snapshot
        self._valid_refs = self._extract_all_refs(snapshot.nodes)
        self._ref_locator_cache.clear()

    def _extract_all_refs(self, nodes) -> set[str]:
        """从节点树中提取所有 ref。"""
        refs = set()
        for node in nodes:
            if node.ref:
                refs.add(node.ref)
            refs.update(self._extract_all_refs(node.children))
        return refs

    def get_ref_locator_mapping(self) -> dict[str, str]:
        """获取 ref → selector 映射（用于经验沉淀）。"""
        mapping = {}
        for ref, locator in self._ref_locator_cache.items():
            try:
                selector = locator.evaluate("el => cssPath(el)")
                mapping[ref] = selector
            except Exception:
                pass
        return mapping
```

### 3.4 `src/core/explore/experience.py`

```python
"""经验管理器 —— 管理 Explore 经验的存储、查询和升级。"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import (
    Action,
    ElementInfo,
    ExploreExperience,
    Skill,
)


class ExperienceManager:
    """Explore 经验管理器。"""

    def __init__(self, storage_dir: str | Path | None = None) -> None:
        self._storage_dir = Path(storage_dir) if storage_dir else Path("data/explore_experiences")
        self._storage_dir.mkdir(parents=True, exist_ok=True)

        # 内存缓存
        self._experiences: dict[str, ExploreExperience] = {}
        self._load_from_disk()

    def save(self, experience: ExploreExperience) -> None:
        """保存经验。"""
        # 去重检查
        existing = self.find_similar(experience.task, experience.site)
        if existing:
            # 更新已有记录
            existing.success_count += 1
            existing.confidence = min(0.95, existing.confidence + 0.05)
            existing.last_used = datetime.now()
            self._experiences[existing.id] = existing
            self._save_to_disk(existing)
        else:
            # 新增记录
            self._experiences[experience.id] = experience
            self._save_to_disk(experience)

    def find_similar(self, task: str, site: str) -> ExploreExperience | None:
        """查找相似的经验。"""
        candidates = [e for e in self._experiences.values() if e.site == site]

        for existing in candidates:
            similarity = self._calculate_similarity(task, site, existing)
            if similarity > 0.8:
                return existing

        return None

    def find_by_url(self, url: str) -> list[ExploreExperience]:
        """根据 URL 查找相关经验。"""
        from urllib.parse import urlparse

        hostname = urlparse(url).hostname or ""
        site = hostname.removeprefix("www.").split(".")[0]

        return [e for e in self._experiences.values() if e.site == site]

    def update_confidence(self, experience_id: str, success: bool) -> None:
        """更新经验置信度。"""
        exp = self._experiences.get(experience_id)
        if not exp:
            return

        if success:
            exp.success_count += 1
            exp.confidence = min(0.95, exp.confidence + 0.05)
        else:
            exp.fail_count += 1
            exp.confidence = max(0.1, exp.confidence - 0.15)

        exp.last_used = datetime.now()

        if exp.confidence < 0.3:
            exp.status = "deprecated"

        self._experiences[experience_id] = exp
        self._save_to_disk(exp)

    def try_upgrade_to_skill(self, experience_id: str) -> Skill | None:
        """尝试将经验升级为技能。"""
        exp = self._experiences.get(experience_id)
        if not exp:
            return None

        # 升级条件
        if exp.success_count < 3:
            return None
        if exp.confidence < 0.8:
            return None
        if exp.fail_count > exp.success_count * 0.2:
            return None

        # 生成脚本
        script = self._generate_script(exp)
        if not script:
            return None

        # 生成技能
        skill_id = f"auto/{exp.site}_{hash(exp.task) % 10000}"
        skill = Skill(
            id=skill_id,
            name=exp.task,
            triggers=self._extract_triggers(exp.task),
            url_patterns=[exp.url_pattern],
            source_code=script,
            from_explore=True,
            confidence=exp.confidence,
            auto_generated=True,
        )

        return skill

    def _calculate_similarity(self, task: str, site: str, existing: ExploreExperience) -> float:
        """计算相似度。"""
        score = 0.0

        # 任务文本相似度（40%）
        task_sim = self._text_similarity(task, existing.task)
        score += task_sim * 0.4

        # 站点匹配（30%）
        if site == existing.site:
            score += 0.3

        # 任务长度相似度（30%）
        len_sim = 1.0 - abs(len(task) - len(existing.task)) / max(len(task), len(existing.task))
        score += len_sim * 0.3

        return score

    def _text_similarity(self, a: str, b: str) -> float:
        """简单的文本相似度计算。"""
        # 基于字符级别的 Jaccard 相似度
        set_a = set(a)
        set_b = set(b)
        intersection = len(set_a & set_b)
        union = len(set_a | set_b)
        return intersection / union if union > 0 else 0.0

    def _generate_script(self, exp: ExploreExperience) -> str | None:
        """从经验生成 Python 脚本。"""
        if not exp.actions or not exp.element_map:
            return None

        lines = []
        lines.append(f'"""自动从 Explore 经验生成: {exp.task}"""')
        lines.append("")
        lines.append("from src.layer_1.actions import *")
        lines.append("")
        lines.append("")

        # 提取参数
        params = self._extract_params(exp)
        param_str = ", ".join(params) if params else ""

        lines.append(f"def run({param_str}):")
        lines.append(f'    """{exp.task}"""')

        for action in exp.actions:
            ref = action.ref
            if not ref:
                continue

            element = exp.element_map.get(ref)
            if not element:
                continue

            selector = element.selector

            if action.action == "click":
                lines.append(f"    click('{selector}')")
            elif action.action == "fill":
                value = action.value or ""
                if self._is_user_input(value, exp.task):
                    param_name = self._guess_param_name(value, exp.task)
                    lines.append(f"    fill('{selector}', {param_name})")
                else:
                    lines.append(f"    fill('{selector}', '{value}')")

        return "\n".join(lines)

    def _extract_params(self, exp: ExploreExperience) -> list[str]:
        """提取用户输入参数。"""
        params = []
        for action in exp.actions:
            if action.action == "fill" and action.value:
                if self._is_user_input(action.value, exp.task):
                    param_name = self._guess_param_name(action.value, exp.task)
                    if param_name not in params:
                        params.append(param_name)
        return params

    def _is_user_input(self, value: str, task: str) -> bool:
        """判断是否是用户输入。"""
        if value in task:
            return True
        if re.match(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", value, re.I):
            return True
        if re.match(r"1[3-9]\d{9}", value):
            return True
        return False

    def _guess_param_name(self, value: str, task: str) -> str:
        """猜测参数名称。"""
        if "搜索" in task or "search" in task.lower():
            return "keyword"
        if "登录" in task or "login" in task.lower():
            if "@" in value:
                return "username"
            return "password"
        return "input_value"

    def _extract_triggers(self, task: str) -> list[str]:
        """从任务描述提取触发词。"""
        # 简单实现：分词
        triggers = [task]

        # 提取关键动词
        verbs = ["搜索", "登录", "注册", "提交", "点击", "输入", "打开"]
        for verb in verbs:
            if verb in task:
                triggers.append(verb)

        return triggers

    def _save_to_disk(self, experience: ExploreExperience) -> None:
        """保存到磁盘。"""
        file_path = self._storage_dir / f"{experience.id}.json"
        file_path.write_text(experience.model_dump_json(indent=2), encoding="utf-8")

    def _load_from_disk(self) -> None:
        """从磁盘加载。"""
        for file_path in self._storage_dir.glob("*.json"):
            try:
                data = json.loads(file_path.read_text(encoding="utf-8"))
                exp = ExploreExperience(**data)
                self._experiences[exp.id] = exp
            except Exception:
                pass
```

---

## 4. 配置项

### 4.1 `src/config.py` 改造

```python
# 在 _DEFAULTS 中添加 Explore 配置

_DEFAULTS: dict[str, str] = {
    # ... 现有配置 ...

    # Explore 模式配置
    "EXPLORE_MAX_RETRIES": "3",
    "EXPLORE_ACTION_TIMEOUT": "15000",
    "EXPLORE_SNAPSHOT_MAX_ELEMENTS": "50",
    "EXPERIENCE_STORAGE_DIR": str(_PROJECT_ROOT / "data" / "explore_experiences"),
    "EXPERIENCE_UPGRADE_THRESHOLD": "3",
    "EXPERIENCE_CONFIDENCE_THRESHOLD": "0.8",
}
```

### 4.2 `.env.example` 补充

```bash
# ===== Explore 模式配置 =====

# 最大重试次数
EXPLORE_MAX_RETRIES=3

# 操作超时时间（毫秒）
EXPLORE_ACTION_TIMEOUT=15000

# 快照最大元素数
EXPLORE_SNAPSHOT_MAX_ELEMENTS=50

# 经验存储目录
EXPERIENCE_STORAGE_DIR=data/explore_experiences

# 经验升级为技能的最小成功次数
EXPERIENCE_UPGRADE_THRESHOLD=3

# 经验升级置信度阈值
EXPERIENCE_CONFIDENCE_THRESHOLD=0.8
```

---

## 5. 集成改造点清单

### 5.1 `src/core/agent_loop.py` 改造

```python
# 改造点 1：导入 Explore 模块
from src.core.explore.executor import ExploreExecutor
from src.core.explore.snapshot import SnapshotGenerator
from src.core.explore.experience import ExperienceManager
from src.core.explore.models import ExploreConfig, SnapshotMode, ActionBatch

# 改造点 2：AgentLoop 初始化添加 Explore 模块
class AgentLoop:
    def __init__(self, ...):
        # ... 现有初始化 ...

        # Explore 模式模块
        self._snapshot_gen: SnapshotGenerator | None = None
        self._explore_executor: ExploreExecutor | None = None
        self._experience_mgr: ExperienceManager | None = None
        self._explore_config: ExploreConfig | None = None

    def _init_modules(self) -> None:
        """延迟初始化各模块。"""
        # ... 现有初始化 ...

        if self._snapshot_gen is None:
            self._snapshot_gen = SnapshotGenerator()

        if self._experience_mgr is None:
            from src.config import get_config
            config = get_config()
            storage_dir = config.get("EXPERIENCE_STORAGE_DIR")
            self._experience_mgr = ExperienceManager(storage_dir)

        if self._explore_config is None:
            self._explore_config = ExploreConfig()

# 改造点 3：PLAN 阶段增加模式选择逻辑
def _do_plan(self, step: AgentStep, task: str) -> AgentState:
    # ... 现有 SkillRouter 匹配逻辑 ...

    # 如果技能库未命中，检查经验库
    if not decision.skill:
        experience = self._find_experience(task, page.url)
        if experience and experience.confidence > 0.7:
            # 使用历史经验
            step.action = f"复用经验: {experience.task}"
            step.actions = experience.actions  # JSON 数组
            step.mode = "explore_reuse"
            return AgentState.ACT

    # 如果经验库也未命中，进入 Explore 模式
    if not decision.skill:
        step.action = "进入 Explore 模式"
        step.mode = "explore"
        return AgentState.EXPLORE  # 新增状态

    # ... 现有逻辑 ...

# 改造点 4：新增 EXPLORE 状态处理
def _do_explore(self, step: AgentStep, task: str) -> AgentState:
    """Explore 模式：获取快照，等待 LLM 决策。"""
    page = get_browser_manager().get_page()

    # 生成快照
    snapshot = self._snapshot_gen.snapshot(page, mode=SnapshotMode.COMPACT)
    step.snapshot = snapshot

    # 更新执行器状态
    self._explore_executor.update_snapshot(snapshot)

    # 返回 PLAN 状态，让 LLM 基于快照决策
    return AgentState.PLAN

# 改造点 5：ACT 阶段支持 Explore 执行
def _do_act(self, step: AgentStep) -> AgentState:
    # 判断模式
    if step.mode in ("explore", "explore_reuse"):
        return self._do_explore_act(step)

    # ... 现有脚本执行逻辑 ...

def _do_explore_act(self, step: AgentStep) -> AgentState:
    """执行 Explore 操作。"""
    if not step.actions:
        step.result = "无操作指令"
        return AgentState.FAILED

    # 构建 ActionBatch
    batch = ActionBatch(actions=step.actions)

    # 执行
    result = self._explore_executor.execute(batch)

    if result.success:
        step.success = True
        step.result = f"执行成功: {result.status}"

        # 如果需要刷新快照
        if result.need_snapshot:
            return AgentState.EXPLORE

        # 保存经验
        self._save_experience(step, result)

        return AgentState.DONE
    else:
        step.success = False
        step.error = result.error
        step.result = f"执行失败: {result.error}"

        # 重试逻辑
        if result.error_code == "REF_EXPIRED":
            return self._handle_ref_expired(step)

        return AgentState.FAILED
```

### 5.2 `src/core/dom_explorer.py` 改造

```python
# 改造点：添加 ARIA 格式输出

def summarize_page_aria(page: Any, max_elements: int = 50) -> dict:
    """生成 ARIA 格式的页面摘要（供 Explore 模式使用）。"""
    from src.core.explore.snapshot import SnapshotGenerator
    from src.core.explore.models import SnapshotMode

    gen = SnapshotGenerator()
    snapshot = gen.snapshot(page, mode=SnapshotMode.COMPACT)

    return snapshot.model_dump()
```

---

## 6. 验收标准

### 6.1 单元测试用例

```python
# tests/test_explore/test_executor.py

class TestExploreExecutor:
    """Explore 执行器测试。"""

    def test_validate_batch_missing_action(self):
        """缺少 action 字段应报错。"""
        ...

    def test_validate_batch_missing_ref(self):
        """click 操作缺少 ref 应报错。"""
        ...

    def test_validate_version_mismatch(self):
        """版本号不匹配应抛出 SnapshotStaleError。"""
        ...

    def test_validate_ref_expired(self):
        """ref 不存在应抛出 RefExpiredError。"""
        ...

    def test_navigation_terminator(self):
        """wait_for=load 应作为数组终结者。"""
        ...

    def test_rollback_on_failure(self):
        """前置队列失败应终止执行。"""
        ...

    def test_sequential_execution(self):
        """操作应按顺序同步执行。"""
        ...


# tests/test_explore/test_snapshot.py

class TestSnapshotGenerator:
    """快照生成器测试。"""

    def test_compact_mode_filter(self):
        """compact 模式应过滤非交互元素。"""
        ...

    def test_ref_assignment(self):
        """可交互元素应分配 ref。"""
        ...

    def test_version_increment(self):
        """每次快照版本号应递增。"""
        ...


# tests/test_explore/test_experience.py

class TestExperienceManager:
    """经验管理器测试。"""

    def test_save_experience(self):
        """保存经验应正确存储。"""
        ...

    def test_find_similar(self):
        """相似任务应能匹配到已有经验。"""
        ...

    def test_upgrade_to_skill(self):
        """满足条件时应能升级为技能。"""
        ...

    def test_confidence_update(self):
        """置信度应随成功/失败更新。"""
        ...
```

### 6.2 集成测试场景

```python
# tests/test_explore/test_integration.py

class TestExploreIntegration:
    """Explore 模式集成测试。"""

    def test_search_jd(self):
        """场景：在京东搜索商品。"""
        # 1. 进入京东首页
        # 2. 获取快照
        # 3. 输出 fill + click 指令
        # 4. 验证执行成功
        # 5. 验证经验保存
        ...

    def test_login_flow(self):
        """场景：登录流程（跨页面）。"""
        # 1. 进入登录页
        # 2. 填写表单
        # 3. 点击登录（终结者）
        # 4. 验证导航发生
        # 5. 获取新快照
        # 6. 验证登录成功
        ...

    def test_ref_expired_recovery(self):
        """场景：ref 过期恢复。"""
        # 1. 获取快照
        # 2. 模拟页面变化
        # 3. 执行操作（应失败）
        # 4. 获取新快照
        # 5. 重试操作（应成功）
        ...
```

### 6.3 验收清单

| 序号 | 验收项 | 验收标准 | 优先级 |
|------|--------|----------|--------|
| 1 | ref 生成 | 可交互元素正确分配 ref，纯展示元素不分配 | P0 |
| 2 | 快照生成 | compact 模式正确过滤，Token < 1500 | P0 |
| 3 | 版本校验 | 版本不匹配时硬失败 | P0 |
| 4 | ref 校验 | ref 不存在时硬失败 | P0 |
| 5 | 导航终结者 | wait_for=load 后强制中断 | P0 |
| 6 | 事务回滚 | 前置失败时终结者不执行 | P0 |
| 7 | 经验保存 | 成功操作自动入库 | P1 |
| 8 | 经验查询 | 相似任务能匹配历史经验 | P1 |
| 9 | 经验升级 | 满足条件自动生成脚本 | P2 |
| 10 | 置信度更新 | 成功+0.05，失败-0.15 | P2 |

---

## 7. 开发顺序建议

```
Phase 1 (P0): 核心执行能力
├── models.py（数据模型）
├── ref_generator.py（ref 生成）
├── snapshot.py（快照生成）
└── executor.py（执行器）

Phase 2 (P1): 经验积累
└── experience.py（经验管理器）

Phase 3 (P2): Agent Loop 集成
├── agent_loop.py 改造
└── dom_explorer.py 改造

Phase 4: 测试与优化
├── 单元测试
├── 集成测试
└── 性能优化
```

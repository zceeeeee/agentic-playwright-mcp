# Explore 模式设计方案

## 1. 模式定义

### 1.1 什么是 Explore 模式

Explore 模式是一种**页面理解驱动**的浏览器自动化模式。Agent 通过 ARIA 语义快照理解页面结构，输出原子化操作指令，由解析器同步执行。

**核心理念**：Agent 是"快照翻译官"，不是"选择器生成器"。

### 1.2 与当前模式的对比

| 维度 | 当前模式（Script-Driven） | Explore 模式（Snapshot-Driven） |
|------|--------------------------|--------------------------------|
| Agent 输出 | Python 脚本 | JSON 数组（原子操作） |
| 元素定位 | CSS Selector | ref（语义化引用） |
| 页面理解 | DOM Explorer 摘要 | ARIA 语义快照 |
| 执行方式 | 脚本引擎 | 解析器同步执行 |
| Token 消耗 | 高（脚本代码） | 低（compact 快照） |

---

## 2. 核心数据结构

### 2.1 ARIA 语义快照（Snapshot）

```yaml
# 完整模式（Full）示例
- role: navigation
  name: 主导航
  children:
    - role: link
      name: 首页
      ref: e1
    - role: link
      name: 产品中心
      ref: e2
    - role: link
      name: 登录
      ref: e3

- role: main
  name: 搜索区域
  children:
    - role: textbox
      name: 搜索框
      placeholder: 输入关键词...
      ref: e10
    - role: button
      name: 搜索
      ref: e11

- role: main
  name: 商品列表
  children:
    - role: article
      name: 商品卡片 - 无线鼠标
      children:
        - role: heading
          level: 3
          name: 无线鼠标
        - role: button
          name: 加入购物车
          ref: e23
```

### 2.2 元素属性定义

| 属性 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `ref` | string | 是 | 全局唯一引用 ID，格式 `e{数字}`，如 `e15` |
| `role` | string | 是 | ARIA 角色：button, link, textbox, heading, article 等 |
| `name` | string | 是 | 元素名称（屏幕阅读器读出的文字） |
| `tag` | string | 否 | HTML 标签名（辅助信息） |
| `placeholder` | string | 否 | 输入框占位符 |
| `disabled` | boolean | 否 | 是否禁用（默认 false） |
| `level` | integer | 否 | heading 层级（1-6） |
| `context` | string | 否 | 父级语义上下文 |

### 2.3 ref 生成规则

```python
# ref 是快照绑定的一次性门票
# 每次快照重新生成，不保证跨快照一致

def generate_ref(element, index):
    """
    生成规则：
    1. 从 e1 开始递增
    2. 只分配给可交互元素（button, link, textbox, select 等）
    3. 纯展示元素（heading, paragraph, img）不分配 ref
    """
    return f"e{index}"
```

### 2.4 快照版本号（Snapshot Version）

**目的**：防止 ref 跨快照误用

**机制**：
1. 每次生成快照时，赋予全局递增的 `version_id`（如 `snapshot_v3`）
2. Agent 返回的每条指令必须携带该 `version_id`
3. 解析器校验时，若版本号不匹配，立即硬失败

**指令格式**：
```json
[
    {"action": "fill", "ref": "e10", "value": "关键词", "snapshot_v": "v3"},
    {"action": "click", "ref": "e11", "snapshot_v": "v3"}
]
```

**可交互角色列表**（分配 ref）：
- `button`, `link`, `textbox`, `checkbox`, `radio`
- `combobox`, `listbox`, `menu`, `menuitem`
- `tab`, `switch`, `slider`, `spinbutton`
- `searchbox`, `option`, `treeitem`

**纯展示角色**（不分配 ref）：
- `heading`, `paragraph`, `img`, `banner`
- `navigation`, `main`, `region`, `article`
- `list`, `listitem`, `table`, `row`, `cell`

---

## 3. 快照模式

### 3.1 完整模式（Full）

**用途**：首次进入页面、页面跳转后

**内容**：
- 完整语义树（所有角色和层级）
- 所有可交互元素的 ref
- 页面状态标记（Modal, Drawer, Dropdown）

**Token 消耗**：3000-5000 tokens

**请求指令**：
```json
{"action": "snapshot", "mode": "full"}
```

### 3.2 精简模式（Compact）

**用途**：日常操作（默认模式）

**过滤规则**：
1. **可见性判定**：`element.checkVisibility()` = true，且在视口内或距离视口顶部/底部 50px 以内
2. **角色白名单**（仅这些进 compact）：
   - `button`, `link`, `textbox`, `searchbox`
   - `checkbox`, `radio`, `combobox`, `listbox`
   - `menuitem`, `tab`, `slider`, `spinbutton`
3. **剔除噪音**：纯文本段落、无交互属性的 `generic` 容器、`img`（除非带 `role=button`）
4. **上下文保留**：保留交互元素的直接父级 `region` / `navigation` / `main` 角色

**Token 消耗**：800-1500 tokens

**请求指令**：
```json
{"action": "snapshot", "mode": "compact"}
```

### 3.3 聚焦模式（Focus）

**用途**：消除歧义、查看特定区域

**内容**：仅指定区域的子元素

**请求指令**：
```json
{"action": "snapshot", "mode": "compact", "focus": {"type": "ref", "value": "e15", "scope": "parent"}}
```

---

## 4. 行动指令规范

### 4.1 指令格式

所有指令必须是 **JSON 数组**，支持单条或多条原子操作：

```json
[
    {"action": "fill", "ref": "e10", "value": "搜索关键词"},
    {"action": "click", "ref": "e11", "wait_for": "load"}
]
```

### 4.2 指令类型

#### 基础操作

| action | 必填参数 | 可选参数 | 说明 |
|--------|----------|----------|------|
| `click` | `ref` | `wait_for` | 点击元素 |
| `fill` | `ref`, `value` | `wait_for` | 清空并输入文本 |
| `hover` | `ref` | — | 悬停触发 CSS :hover |
| `select` | `ref`, `value` | — | 下拉选择选项 |
| `check` | `ref` | — | 勾选复选框 |
| `uncheck` | `ref` | — | 取消勾选 |

#### 导航操作

| action | 必填参数 | 说明 |
|--------|----------|------|
| `goto` | `url` | 导航到指定 URL |
| `back` | — | 浏览器后退 |
| `forward` | — | 浏览器前进 |
| `scroll` | `direction` (up/down), `amount` | 滚动页面 |

#### 状态操作

| action | 必填参数 | 可选参数 | 说明 |
|--------|----------|----------|------|
| `snapshot` | — | `mode`, `focus` | 获取新快照 |
| `wait` | `condition` | `timeout` | 等待条件满足 |
| `screenshot` | — | `path` | 截图保存 |

### 4.3 wait_for 参数

| 值 | 含义 | 超时 |
|----|------|------|
| `none` | 不等待（默认） | — |
| `load` | 页面加载完成 | 15s |
| `networkidle` | 500ms 网络空闲 | 15s |
| `selector_visible` | 目标元素可见 | 10s |

**示例**：
```json
{"action": "click", "ref": "e15", "wait_for": "load"}
```

### 4.5 导航终结者规则（Navigation Terminator）

**核心规则**：任何带有 `wait_for: "load"` 或 `wait_for: "networkidle"` 的操作，**必须是该 JSON 数组中的最后一个元素**。

**解析器行为**：
1. 执行前预扫描数组，检测是否存在 `wait_for: "load"`
2. 若存在，将动作队列切分为"前置队列"和"终结动作"
3. 执行终结动作后，强制中断数组剩余指令，立即返回新快照
4. 前置队列中任何 ref 失效，终结动作都不执行（事务回滚）

**示例**：
```json
// 回合 1：登录（终结者在最后）
[
    {"action": "fill", "ref": "e1", "value": "user@email.com", "snapshot_v": "v3"},
    {"action": "fill", "ref": "e2", "value": "123456", "snapshot_v": "v3"},
    {"action": "click", "ref": "e3", "wait_for": "load", "snapshot_v": "v3"}  // 终结者
]
// 执行完 e3 后，页面跳转，强制触发快照刷新

// 回合 2：搜索（基于新快照）
[
    {"action": "fill", "ref": "e20", "value": "机械键盘", "snapshot_v": "v4"},
    {"action": "click", "ref": "e21", "wait_for": "load", "snapshot_v": "v4"}
]
```

### 4.4 wait 指令

```json
{"action": "wait", "condition": "selector_visible", "ref": "e20", "timeout": 10000}
{"action": "wait", "condition": "text_visible", "value": "提交成功", "timeout": 5000}
{"action": "wait", "condition": "networkidle", "timeout": 15000}
```

---

## 5. Focus 结构化语法

### 5.1 语法定义

```json
{
    "type": "ref" | "role_name" | "position",
    "value": "目标值",
    "scope": "self" | "parent" | "children" | "siblings"
}
```

### 5.2 类型说明

#### 按 Ref 聚焦

```json
{"type": "ref", "value": "e15", "scope": "parent"}
```
- 用途：查看 e15 所在的父容器
- 场景：解决同名按钮歧义

#### 按角色/名称聚焦

```json
{"type": "role_name", "value": "dialog:确认弹窗", "scope": "children"}
```
- 用途：查看特定角色/名称的元素内部
- 场景：弹窗、下拉菜单

#### 按位置聚焦

```json
{"type": "position", "value": "viewport"}
```
- 用途：仅返回视口内可见元素
- 场景：长页面裁剪，省 Token

### 5.3 Scope 说明

| scope | 含义 | 返回内容 |
|-------|------|----------|
| `self` | 仅自己 | 该元素自身属性 |
| `parent` | 父容器 | 父元素及其所有子元素 |
| `children` | 所有子元素 | 该元素内部的完整子树 |
| `siblings` | 兄弟元素 | 同级元素列表 |

---

## 6. Agent 决策流程

### 6.1 标准流程

```
1. 意图识别
   用户要我做什么？
       ↓
2. 快照扫描
   在 YAML 中查找匹配的 role + name
       ↓
3. 提取 ref
   锁定目标元素，提取 ref 值
       ↓
4. 歧义检查
   多个匹配？→ 用 focus 消歧
       ↓
5. 打包返回
   连续操作合并为数组
       ↓
6. 状态重置
   页面跳转后，丢弃所有旧 ref
```

### 6.2 决策示例

**用户指令**：帮我在搜索框输入"无线鼠标"，然后点击搜索

**Agent 思考**：
1. 意图：输入 + 点击搜索
2. 扫描快照：找到 `textbox` name=搜索框 (ref=e10) 和 `button` name=搜索 (ref=e11)
3. 无歧义
4. 打包：fill + click 一次性返回

**Agent 输出**：
```json
[
    {"action": "fill", "ref": "e10", "value": "无线鼠标"},
    {"action": "click", "ref": "e11", "wait_for": "load"}
]
```

---

## 7. 异常处理

### 7.1 ref 失效（REF_EXPIRED）

**场景**：操作时 ref 已不存在（页面变化）

**解析器行为**：硬失败，绝不尝试智能匹配
```json
{
    "error": "REF_EXPIRED",
    "ref": "e15",
    "snapshot_v": "v3",
    "hint": "请调用 snapshot 刷新视图"
}
```

**Agent 恢复策略**：
1. 立即输出 `{"action": "snapshot", "mode": "compact"}` 获取最新快照
2. 基于新快照，重试刚才失败的操作（不重试已成功的操作）
3. 单次任务总重试上限 = 3 次
4. 超过 3 次仍失败，输出失败状态

**重试计数**：Agent 在上下文记忆中维护 `retry_count`

### 7.2 版本号不匹配（SNAPSHOT_STALE）

**场景**：指令中的 `snapshot_v` 与当前快照版本不一致

**解析器行为**：硬失败
```json
{
    "error": "SNAPSHOT_STALE",
    "expected": "v4",
    "actual": "v3",
    "hint": "请用最新快照的版本号重新生成指令"
}
```

### 7.2 元素不可交互

**场景**：ref 存在但元素被禁用或被遮挡

**处理**：
```json
// 解析器返回错误
{"error": "ElementNotInteractableError", "ref": "e15", "message": "元素被禁用"}

// Agent 响应：等待或寻找替代方案
[{"action": "wait", "condition": "selector_visible", "ref": "e15"}]
```

### 7.3 同名元素歧义

**场景**：多个 button name="确定"

**处理**：
```json
// Agent 请求聚焦查看上下文
[{"action": "snapshot", "mode": "compact", "focus": {"type": "ref", "value": "e20", "scope": "parent"}}]

// 拿到更详细的快照后，区分是哪个弹窗中的确定按钮
```

### 7.4 页面跳转

**场景**：点击链接后页面完全刷新

**处理**：
```json
// Agent 输出：点击 + 等待加载 + 获取新快照
[
    {"action": "click", "ref": "e3", "wait_for": "load"},
    {"action": "snapshot", "mode": "compact"}
]
```

---

## 8. Token 控制策略

### 8.1 快照模式选择

| 场景 | 推荐模式 | Token 消耗 |
|------|----------|-----------|
| 首次进入页面 | full | 3000-5000 |
| 日常操作 | compact | 800-1500 |
| 消除歧义 | compact + focus | 300-800 |
| 长页面 | compact + viewport | 500-1000 |

### 8.2 省 Token 技巧

1. **默认用 compact**：只在首次或跳转后用 full
2. **用 focus 裁剪**：只看需要的区域
3. **viewport 裁剪**：长页面只看当前视口
4. **批量操作**：多个操作合并为一个数组，减少快照次数

### 8.3 Token 预算示例

```
30 步操作的 Token 消耗估算：
- 快照：30 × 1000 (compact) = 30,000 tokens
- 指令：30 × 50 (JSON) = 1,500 tokens
- 总计：~31,500 tokens

对比当前模式：
- 脚本：30 × 200 (Python) = 6,000 tokens
- DOM 摘要：30 × 500 = 15,000 tokens
- 总计：~21,000 tokens

Explore 模式略高，但准确率大幅提升。
```

---

## 9. 解析器实现要求

### 9.1 核心约束

```python
class ExploreExecutor:
    """Explore 模式解析器铁律"""

    def __init__(self):
        self._snapshot_version = 0
        self._valid_refs: set[str] = set()

    def execute(self, actions: list[dict], snapshot: dict):
        # 1. 严格格式校验
        assert isinstance(actions, list), "响应必须是 JSON 数组"
        for action in actions:
            assert "action" in action
            if action["action"] in ["click", "fill", "hover"]:
                assert "ref" in action
                assert "snapshot_v" in action

        # 2. 版本号校验（硬失败）
        current_version = snapshot.get("version")
        for action in actions:
            v = action.get("snapshot_v")
            if v and v != current_version:
                raise SnapshotStaleError(
                    f"版本不匹配: 指令={v}, 当前={current_version}"
                )

        # 3. Ref 防呆校验（硬失败，绝不智能匹配）
        valid_refs = snapshot.get_all_refs()
        for action in actions:
            ref = action.get("ref")
            if ref and ref not in valid_refs:
                raise RefExpiredError(f"Ref {ref} 在当前快照中不存在")

        # 4. 检测导航终结者
        terminator_idx = self._find_terminator(actions)

        # 5. 执行前置队列
        for i in range(terminator_idx + 1):
            self._execute_single(actions[i])

        # 6. 如果有终结者，执行后强制刷新快照
        if terminator_idx is not None:
            return {"status": "navigation_occurred", "need_snapshot": True}

        return {"status": "success"}

    def _find_terminator(self, actions: list[dict]) -> int | None:
        """找到导航终结者的索引"""
        for i, action in enumerate(actions):
            if action.get("wait_for") in ("load", "networkidle"):
                return i
        return None

    def _execute_single(self, action: dict):
        """执行单个操作"""
        if action["action"] == "click":
            self._click(action["ref"])
        elif action["action"] == "fill":
            self._fill(action["ref"], action["value"])
        # ...
```

### 9.2 关键规则

1. **同步顺序执行**：数组中的操作按顺序执行，禁止并行
2. **版本号强校验**：snapshot_v 不匹配立即硬失败
3. **ref 消费后即失效**：每个 ref 只能使用一次
4. **导航终结者**：`wait_for: "load"` 必须是数组最后一个元素
5. **事务回滚**：前置队列任何 ref 失效，终结动作不执行
6. **最大超时**：wait_for 最长 15s，防止死循环

---

## 10. 集成到 Agent Loop

### 10.1 模式定位

Explore 模式是**可选的、可被激活的**浏览器自动化模式：

| 触发条件 | 模式选择 |
|----------|----------|
| 技能库匹配成功 | Script 模式（优先） |
| 技能库匹配失败 | Explore 模式（降级） |
| 用户显式指定 | 按用户选择 |
| 未知网站首次访问 | Explore 模式（探索） |

### 10.2 三层经验架构

```
┌─────────────────────────────────────────────────────────────┐
│                    Layer 3: 脚本技能库                        │
│  成熟的、可复用的 Python 脚本（如 GitHub 登录、Gmail 发送）      │
│  来源：手动编写 + Explore 经验沉淀                              │
└─────────────────────────────────────────────────────────────┘
                              ▲
                              │ 经验沉淀（自动/手动）
┌─────────────────────────────────────────────────────────────┐
│                    Layer 2: Explore 经验库                    │
│  成功的操作序列（JSON 数组 + 快照上下文）                        │
│  结构：{task, site, actions[], snapshot_context, success}     │
└─────────────────────────────────────────────────────────────┘
                              ▲
                              │ 操作记录
┌─────────────────────────────────────────────────────────────┐
│                    Layer 1: 实时 Explore 会话                 │
│  当前页面的 ARIA 快照 + Agent 的原子操作                        │
│  生命周期：单次任务                                             │
└─────────────────────────────────────────────────────────────┘
```

### 10.3 自动经验沉淀机制

#### 沉淀触发条件

```python
def should_save_experience(result: ExploreResult) -> bool:
    """判断是否触发经验沉淀"""
    # 必须成功
    if not result.success:
        return False

    # 必须有至少 2 步操作（单步太简单，不值得沉淀）
    if len(result.actions) < 2:
        return False

    # 必须有明确的任务描述
    if not result.task or len(result.task) < 5:
        return False

    return True
```

#### 沉淀数据结构

```python
@dataclass
class ExploreExperience:
    """Explore 经验条目"""

    # 基础信息
    task: str                    # 用户任务描述
    site: str                    # 站点域名
    url_pattern: str             # URL 匹配模式（用于后续匹配）

    # 操作序列
    actions: list[dict]          # 原子操作数组
    action_count: int            # 操作步数

    # 元素映射（关键：ref → selector）
    element_map: dict[str, ElementInfo]
    # {
    #   "e10": {
    #     "selector": "#search-input",
    #     "role": "textbox",
    #     "name": "搜索框",
    #     "tag": "input"
    #   }
    # }

    # 快照上下文（用于相似性匹配）
    snapshot_roles: list[str]    # ["textbox", "button", "link"]
    snapshot_names: list[str]    # ["搜索框", "搜索", "首页"]

    # 质量指标
    success_count: int = 1       # 成功次数
    fail_count: int = 0          # 失败次数
    confidence: float = 0.7      # 初始置信度
    last_used: datetime = None   # 最后使用时间

    # 元数据
    created_at: datetime = None
    from_explore: bool = True    # 标记来源
```

#### 沉淀流程（全自动）

```
Step 1: Explore 任务成功完成
        ↓
Step 2: 提取元素映射（ref → selector）
        ↓
Step 3: 生成经验条目
        ↓
Step 4: 去重检查（相似任务是否已存在）
        ↓
Step 5: 入库 Layer 2
        ↓
Step 6: 判断是否可升级到 Layer 3
```

#### Step 2 详细：元素映射提取

```python
def extract_element_map(actions: list[dict], page) -> dict[str, ElementInfo]:
    """从成功执行的操作中提取 ref → selector 映射"""
    element_map = {}

    for action in actions:
        ref = action.get("ref")
        if not ref:
            continue

        # 通过 ref 找到对应的 Playwright Locator
        # （执行时已缓存了 ref → locator 的映射）
        locator = get_cached_locator(ref)
        if not locator:
            continue

        # 提取稳定的 selector
        selector = extract_stable_selector(locator)

        # 提取语义信息
        role = action.get("role", "")
        name = action.get("name", "")

        element_map[ref] = ElementInfo(
            selector=selector,
            role=role,
            name=name,
            tag=get_tag(locator),
        )

    return element_map


def extract_stable_selector(locator) -> str:
    """提取稳定的 CSS Selector"""
    # 优先级：
    # 1. [data-testid] / [data-test-id]
    # 2. #id
    # 3. 有意义的 class 组合
    # 4. aria-label
    # 5. 结构化路径（最后手段）

    # 尝试 data-testid
    test_id = locator.get_attribute("data-testid")
    if test_id:
        return f'[data-testid="{test_id}"]'

    # 尝试 id
    el_id = locator.get_attribute("id")
    if el_id and not re.match(r"^[a-f0-9-]+$", el_id):  # 排除 UUID
        return f'#{el_id}'

    # 尝试 aria-label
    aria = locator.get_attribute("aria-label")
    if aria:
        return f'[aria-label="{aria}"]'

    # 降级：结构化路径
    return locator.evaluate("el => cssPath(el)")
```

#### Step 4 详细：去重检查

```python
def find_similar_experience(new_exp: ExploreExperience, db: ExperienceDB) -> ExploreExperience | None:
    """查找相似的已有经验"""
    candidates = db.query(site=new_exp.site)

    for existing in candidates:
        # 相似度计算
        similarity = calculate_similarity(new_exp, existing)

        if similarity > 0.8:
            # 高度相似，更新已有记录
            return existing

    return None


def calculate_similarity(a: ExploreExperience, b: ExploreExperience) -> float:
    """计算两个经验的相似度"""
    score = 0.0

    # 1. 任务文本相似度（40%）
    task_sim = text_similarity(a.task, b.task)
    score += task_sim * 0.4

    # 2. 操作序列相似度（30%）
    action_sim = action_sequence_similarity(a.actions, b.actions)
    score += action_sim * 0.3

    # 3. 元素角色相似度（20%）
    role_sim = len(set(a.snapshot_roles) & set(b.snapshot_roles)) / max(len(a.snapshot_roles), 1)
    score += role_sim * 0.2

    # 4. URL 模式匹配（10%）
    url_sim = 1.0 if a.url_pattern == b.url_pattern else 0.0
    score += url_sim * 0.1

    return score
```

#### Step 6 详细：升级到 Layer 3

```python
def try_upgrade_to_skill(exp: ExploreExperience) -> Skill | None:
    """尝试将经验升级为脚本技能"""
    # 升级条件
    if exp.success_count < 3:
        return None  # 成功次数不足
    if exp.confidence < 0.8:
        return None  # 置信度不足
    if exp.fail_count > exp.success_count * 0.2:
        return None  # 失败率过高

    # 生成脚本
    script = generate_script_from_experience(exp)
    if not script:
        return None

    # 生成技能条目
    skill = Skill(
        id=f"auto/{exp.site}_{hash(exp.task) % 10000}",
        name=exp.task,
        triggers=extract_triggers(exp.task),
        url_patterns=[exp.url_pattern],
        source_code=script,
        from_explore=True,
        confidence=exp.confidence,
        auto_generated=True,
    )

    return skill


def generate_script_from_experience(exp: ExploreExperience) -> str | None:
    """从经验生成 Python 脚本"""
    lines = []
    lines.append(f'"""自动从 Explore 经验生成: {exp.task}"""')
    lines.append("")
    lines.append("from src.layer_1.actions import *")
    lines.append("")
    lines.append("")

    # 提取参数
    params = extract_params(exp)
    param_str = ", ".join(params) if params else ""

    lines.append(f"def run({param_str}):")
    lines.append(f'    """{exp.task}"""')

    # 生成操作序列
    for action in exp.actions:
        ref = action.get("ref")
        if not ref:
            continue

        element = exp.element_map.get(ref)
        if not element:
            continue

        selector = element.selector
        action_type = action["action"]

        if action_type == "click":
            lines.append(f"    click('{selector}')")
        elif action_type == "fill":
            value = action.get("value", "")
            # 判断是否是参数
            if is_user_input(value, exp.task):
                param_name = guess_param_name(value, exp.task)
                lines.append(f"    fill('{selector}', {param_name})")
            else:
                lines.append(f"    fill('{selector}', '{value}')")
        elif action_type == "select":
            lines.append(f"    select('{selector}', '{action['value']}')")

        # 等待
        wait_for = action.get("wait_for")
        if wait_for == "load":
            lines.append("    wait_for_load()")
        elif wait_for == "networkidle":
            lines.append("    wait(1)")

    lines.append("")
    lines.append("")
    lines.append(f"# 自动调用")
    if params:
        lines.append(f"# run({', '.join(['...' for _ in params])})")
    else:
        lines.append("run()")

    return "\n".join(lines)


def extract_params(exp: ExploreExperience) -> list[str]:
    """从经验中提取用户输入参数"""
    params = []
    for action in exp.actions:
        if action["action"] == "fill":
            value = action.get("value", "")
            if is_user_input(value, exp.task):
                param_name = guess_param_name(value, exp.task)
                if param_name not in params:
                    params.append(param_name)
    return params


def is_user_input(value: str, task: str) -> bool:
    """判断填入的值是否是用户输入"""
    # 如果值出现在任务描述中，说明是用户指定的
    if value in task:
        return True
    # 如果是邮箱、手机号等格式
    if re.match(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", value, re.I):
        return True
    if re.match(r"1[3-9]\d{9}", value):
        return True
    return False


def guess_param_name(value: str, task: str) -> str:
    """猜测参数名称"""
    # 根据上下文猜测
    if "搜索" in task or "search" in task.lower():
        return "keyword"
    if "登录" in task or "login" in task.lower():
        if "@" in value:
            return "username"
        return "password"
    if "邮箱" in task or "email" in task.lower():
        return "email"
    return "input_value"
```

#### 经验置信度更新

```python
def update_confidence(exp: ExploreExperience, success: bool):
    """更新经验置信度"""
    if success:
        exp.success_count += 1
        # 成功时置信度缓慢上升
        exp.confidence = min(0.95, exp.confidence + 0.05)
    else:
        exp.fail_count += 1
        # 失败时置信度快速下降
        exp.confidence = max(0.1, exp.confidence - 0.15)

    exp.last_used = datetime.now()

    # 如果置信度过低，标记为不可用
    if exp.confidence < 0.3:
        exp.status = "deprecated"
```

### 10.4 经验查询机制

Agent 执行任务时的查询顺序：

```python
def plan_action(task, page_url):
    # 1. 查 Layer 3：脚本技能库（精确匹配）
    skill = skill_router.route(task, url=page_url)
    if skill:
        return ScriptMode(skill)

    # 2. 查 Layer 2：Explore 经验库（相似匹配）
   经验 = experience_manager.find_similar(task, url=page_url)
    if 经验 and 经验.confidence > 0.7:
        return ExploreMode(reuse=经验)  # 复用历史操作序列

    # 3. 降级到 Layer 1：实时 Explore
    return ExploreMode(fresh=True)
```

### 10.5 状态机变更

```
当前：OBSERVE → PLAN → ACT → DONE

Explore 模式：
OBSERVE → PLAN → ACT → SNAPSHOT → PLAN → ...
                ↑__________________________|
                      （循环直到完成）

混合模式：
OBSERVE → PLAN → [Script|Explore] → ACT → DONE
```

---

## 11. 附录：完整示例

### 场景：在电商网站搜索商品

**Step 1：进入页面**
```json
// Agent 请求
[{"action": "goto", "url": "https://example.com"}]

// 解析器返回快照
- role: navigation
  name: 主导航
  children:
    - role: link
      name: 首页
      ref: e1
    - role: link
      name: 登录
      ref: e2
- role: main
  name: 搜索区域
  children:
    - role: textbox
      name: 搜索框
      ref: e10
    - role: button
      name: 搜索
      ref: e11
```

**Step 2：搜索商品**
```json
// Agent 输出
[
    {"action": "fill", "ref": "e10", "value": "无线鼠标"},
    {"action": "click", "ref": "e11", "wait_for": "load"}
]

// 解析器返回新快照（compact 模式）
- role: main
  name: 搜索结果
  children:
    - role: article
      name: 商品 - 罗技MX Master
      children:
        - role: button
          name: 加入购物车
          ref: e30
    - role: article
      name: 商品 - 雷蛇毒蝰
      children:
        - role: button
          name: 加入购物车
          ref: e40
```

**Step 3：加入购物车**
```json
// Agent 输出
[{"action": "click", "ref": "e30", "wait_for": "networkidle"}]

// 完成
```

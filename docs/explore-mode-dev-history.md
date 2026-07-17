# Explore 模式开发历史

## 2026-07-08 开发记录

### 问题 1: 全角字符导致 SyntaxError

**现象**: LLM 生成的 Python 脚本包含全角标点（如 `，` U+FF0C），导致 `exec()` 抛出 `SyntaxError: invalid character '，' (U+FF0C)`。

**根因**: LLM（特别是中文模型）生成脚本时混入全角标点符号。

**修复**: 在 `src/core/script_engine.py` 的 `execute()` 方法中，`exec()` 前加入全角→半角字符清洗：

```python
_FULLWIDTH_MAP: dict[str, str] = str.maketrans(
    # 全角标点
    "，。；：？！（）【】｛｝＝＋－＊／＼｜＆＾％＄＃＠～｀＜＞＂＇"
    # 智能引号（弯引号，LLM 极常生成）
    """''",
    ",.;:?!()[]{}=+-*/\\|&^%$#@~`<>\"'"
    "\"\"''",
)
```

覆盖范围：全角标点 + 智能引号（`""''`）。

---

### 问题 2: LLM 响应被截断

**现象**: LLM 返回的 JSON 响应不完整，解析失败。

**根因**: `max_tokens` 设置过小（256/512），LLM 输出推理过程后 JSON 还没输出完就被截断。

**修复**: 增大各处 `max_tokens`：

| 位置 | 原值 | 新值 |
|------|------|------|
| `explore/agent.py` 搜索结果选择 | 256 | 1024 |
| `explore/agent.py` 入口 URL 解析 | 512 | 1024 |
| `skill_router.py` LLM 精排 | 1024 (默认) | 2048 |
| `skill_router.py` 参数提取 | 1024 (默认) | 2048 |
| `agent_loop.py` LLM 仲裁 | 1024 (默认) | 2048 |
| `explore/agent.py` Explore planner | 1024 | 2048 |

---

### 问题 3: LLM 返回推理内容而非最终答案

**现象**: `_find_skill_via_llm` 返回整段推理文本（"首先，用户指令是..."）而非技能 ID。

**根因**: `_call_openai()` 缺少 `"chat_template_kwargs": {"enable_thinking": False}`，导致模型开启思考模式，把推理过程放在 `content` 字段返回。

**修复**: 在 `src/core/llm_client.py` 的 `_call_openai()` 中添加：
```python
payload = {
    ...
    "chat_template_kwargs": {"enable_thinking": False},
}
```

**附带修复**: 新增 `_extract_skill_id()` 方法作为兜底，从 LLM 推理文本中提取已知技能 ID。

---

### 问题 4: Explore planner 返回 schema 类型名字面量

**现象**: LLM 返回 `{"actions": ["string", "null"]}` 而非实际操作对象。

**根因**: LLM 把 JSON Schema 的类型定义（`"type": "string"`）当成了示例值。

**修复**:
1. `normalize_action_batch_data()` 增加过滤逻辑，移除 `actions` 数组中的非字典项
2. prompt 中增加规则 16 和具体示例，明确告知 LLM 每个 action 必须是对象

---

### 问题 5: Explore 模式下误匹配技能

**现象**: 已导航到千问页面，但 PLAN 阶段仍匹配到"百度搜索"或"豆包搜索"。

**根因**: `has_pending_snapshot` 检查在技能匹配之后，且 Explore planner 失败时 fall through 到技能匹配。

**修复**:
1. 在 PLAN 阶段**技能匹配之前**检查 `has_pending_snapshot`，优先使用 Explore
2. Explore planner 失败时，重新进入 Explore 模式重试，不 fall through
3. 新增 `explore_mode_active` 标记，一旦进入 Explore 模式，整个任务生命周期内跳过所有技能匹配

---

### 问题 6: executor 找不到 DOM 元素

**现象**: `Locator.fill: Timeout 15000ms exceeded. waiting for locator("[data-explore-ref="e166"]")`。

**根因**: native `aria_snapshot` API 的 YAML 解析（`_parse_aria_yaml`）设置 `selector: None`，导致 `_sync_refs_to_dom` 跳过所有节点，`data-explore-ref` 属性从未添加到 DOM。

**修复**: 修改 executor 的 `_get_locator` 方法，直接使用 `page.get_by_role(role, name=name)` 定位元素，不再依赖 `data-explore-ref` 属性：

```python
def _get_locator(self, ref: str) -> Any:
    role_info = self._ref_role_map.get(ref)
    if role_info:
        role, name = role_info
        locator = self._page.get_by_role(role, name=name or None, exact=bool(name)).first
    else:
        locator = self._page.locator(f'[data-explore-ref="{ref}"]')
    return locator
```

同时在 `update_snapshot` 时建立 `ref → (role, name)` 映射。

---

### 问题 7: native aria_snapshot API 检测不到自定义组件

**现象**: 千问页面的搜索输入框未出现在快照中，只有 3 个 button。

**根因**: 千问使用自定义组件（可能是 `div[contenteditable]` 或 React 组件），没有标准 ARIA 角色。native API 的 `mode="ai"` 和 `mode="full"` 都无法检测。

**修复**: 在 custom JS 方法的 `implicitRole` 函数中增加检测：
1. `contenteditable` 属性 → 识别为 `textbox`
2. 常见编辑器 CSS 类名（`editor`、`composer`、`chat-input`）→ 识别为 `textbox`

同时将 `_use_native` 设为 `False`，使用 custom JS 方法。

---

### 问题 8: Explore strict mode violation

**现象**: `Locator.click: Error: strict mode violation: get_by_role("button", name="新建对话", exact=True) resolved to 2 elements`。

**根因**: `get_by_role` 找到多个同名元素，strict mode 报错。

**修复**: `_get_locator` 使用 `.first` 获取第一个匹配元素。

---

## 当前状态

### 待解决

- [ ] 千问搜索框仍未被检测到（可能需要更多 CSS 类名匹配或不同的检测策略）
- [ ] Explore planner 规划的操作不正确（点了"新建对话"而非搜索框）

### 已修复

- [x] 全角字符清洗（script_engine.py）
- [x] LLM max_tokens 不足（多处）
- [x] 思考模式关闭（llm_client.py）
- [x] Explore 模式与技能匹配分离（agent_loop.py）
- [x] executor 使用 get_by_role 定位（executor.py）
- [x] normalize_action_batch_data 过滤非字典项（agent.py）
- [x] contenteditable 检测（snapshot.py）

---

## 架构决策

### Explore 模式 vs Script 模式

- **Script 模式**: 使用技能库匹配 + LLM 生成 Python 脚本，通过 `exec()` 执行
- **Explore 模式**: 使用 ARIA 快照 + LLM 规划原子操作，通过 executor 直接调用 Playwright API

**设计原则**: 一旦进入 Explore 模式（通过入口导航），整个任务生命周期内不匹配技能，严格分离两种模式。

### 快照策略

- **native API**: 准确但无法检测自定义组件
- **custom JS**: 可检测更多元素但准确性略低
- **当前方案**: 使用 custom JS，通过 `implicitRole` 扩展检测 `contenteditable` 和常见 CSS 类名

### 元素定位策略

- **旧方案**: 通过 `_sync_refs_to_dom` 给 DOM 添加 `data-explore-ref` 属性，executor 用 `[data-explore-ref]` 选择器定位
- **新方案**: executor 直接用 `get_by_role(role, name=name)` 定位，不修改 DOM
- **优势**: 不依赖 CSS selector，不修改 DOM，更简洁可靠

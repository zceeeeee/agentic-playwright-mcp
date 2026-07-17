# Explore 模式遗留问题修复 — 开发任务书

## 0. 前置条件

| 项目 | 当前值 | 目标值 |
|------|--------|--------|
| Playwright 安装版本 | 1.60.0 | 1.60.0（不变） |
| pyproject.toml 约束 | `>=1.40.0` | `>=1.59.0` |
| ariaSnapshot() 可用 | ✅ | ✅ |

---

## 1. Phase 1: 快照引擎替换

### 1.1 目标

将 `src/core/explore/snapshot.py` 中的自定义 JS（`_ARIA_EXTRACTION_JS`，154 行）替换为 Playwright 原生 `page.aria_snapshot(mode="ai", boxes=True)`。

### 1.2 Playwright 原生 API 行为

调用方式：
```python
yaml_text = page.locator("body").aria_snapshot(mode="ai", boxes=True)
```

返回 YAML 格式，示例：
```yaml
- navigation "主导航":
  - link "首页" [ref=e1]
  - link "产品中心" [ref=e2]
- main "搜索区域":
  - textbox "搜索框" [ref=e3]
  - button "搜索" [ref=e4]
- dialog "确认弹窗" [ref=e5]:
  - button "确定" [ref=e6]
  - button "取消" [ref=e7]
```

关键特性：
- `mode="ai"` 自动包含 `[ref=eN]` 标签（Playwright 分配的 ref）
- 自动穿透 Shadow DOM（通过浏览器原生无障碍树）
- 自动穿透 iframe（mode="ai" 时）
- 遵循 W3C Accessible Name 计算规范
- `boxes=True` 时返回 `[x=0 y=0 width=100 height=50]` 边界框

### 1.3 需要新增的代码

#### 1.3.1 YAML 解析器：`_parse_aria_yaml(yaml_text: str) -> dict`

将 Playwright 返回的 YAML 文本解析为现有 `AriaNode` 树结构。

**解析规则**：
- 每行一个节点，缩进表示层级关系
- 格式：`- role "name" [attr=value]` 或 `- role "name":`（有子节点时带冒号）
- 无引号的 name：`- button Submit [ref=e3]`
- 带引号的 name：`- button "Sign In" [ref=e3]`
- 属性：`[ref=e3]`、`[checked]`、`[level=2]`、`[x=10 y=20 width=100 height=50]`
- 特殊子节点：`- /url: "https://..."`（link 的 href）
- 纯文本：`- text: Hello world`

**解析算法**：
```
1. 按行分割，跳过空行
2. 计算每行缩进层级（空格数 / 2）
3. 用栈维护父节点关系
4. 解析每行的 role、name、attributes
5. 构建 AriaNode 树
```

**输出格式**：与现有 `_extract_aria_tree` 返回的 dict 结构一致：
```python
{
    "role": "navigation",
    "name": "主导航",
    "tag": None,
    "selector": None,
    "placeholder": None,
    "disabled": False,
    "level": None,
    "context": "",
    "children": [...]
}
```

注意：Playwright 的 ref（如 `e3`）直接映射到 `AriaNode.ref` 字段，不再需要 `RefGenerator` 重新分配。

#### 1.3.2 修改 `SnapshotGenerator.__init__`

```python
def __init__(self, config: Any = None) -> None:
    self._config = config
    self._ref_gen = RefGenerator()  # 保留，fallback 时使用
    self._version_counter = 0
    self._use_native = True  # 新增：优先使用原生 API
```

#### 1.3.3 修改 `_extract_aria_tree`

```python
def _extract_aria_tree(self, page: Any, focus: FocusTarget | None = None) -> dict:
    if self._use_native:
        try:
            return self._extract_via_native(page, focus)
        except (AttributeError, TypeError, Exception) as exc:
            logger.warning("aria_snapshot() failed, falling back: %s", exc)
    return self._extract_via_custom_js(page, focus)
```

#### 1.3.4 新增 `_extract_via_native`

```python
def _extract_via_native(self, page: Any, focus: FocusTarget | None = None) -> dict:
    """使用 Playwright 原生 aria_snapshot 提取语义树。"""
    locator = page.locator("body")

    # 处理 focus 聚焦
    if focus:
        if focus.type == "ref":
            locator = page.locator(f'[data-explore-ref="{focus.value}"]')
        elif focus.type == "role_name":
            role, name = focus.value.split(":", 1)
            locator = page.get_by_role(role, name=name)

    yaml_text = locator.aria_snapshot(mode="ai", boxes=True)
    return self._parse_aria_yaml(yaml_text)
```

#### 1.3.5 修改 `_build_nodes`

原生 API 已经返回 ref，不需要再调用 `_ref_gen.assign_refs()`：

```python
def _build_nodes(self, raw_tree: dict, mode: SnapshotMode) -> list[AriaNode]:
    if not raw_tree:
        return []
    node = self._raw_to_node(raw_tree)
    if not node:
        return []
    if mode == SnapshotMode.COMPACT:
        return self._filter_compact([node])
    return [node]
```

#### 1.3.6 修改 `snapshot` 方法

```python
def snapshot(self, page, mode=SnapshotMode.COMPACT, focus=None):
    self._version_counter += 1
    version = f"snapshot_v{self._version_counter}"

    raw_tree = self._extract_aria_tree(page, focus)
    nodes = self._build_nodes(raw_tree, mode)

    # 如果原生 API 没有返回 ref（降级情况），用 RefGenerator 补充
    if not self._has_any_ref(nodes):
        self._ref_gen.reset()
        self._ref_gen.assign_refs(nodes)

    self._sync_refs_to_dom(page, nodes)
    interactive_count = self._count_interactive(nodes)
    state = self._detect_page_state(page)

    return SnapshotResponse(
        version=version,
        mode=mode,
        url=str(getattr(page, "url", "") or ""),
        title=self._page_title(page),
        nodes=nodes,
        interactive_count=interactive_count,
        has_modal=state.get("has_modal", False),
    )
```

#### 1.3.7 重命名现有 JS

将 `_ARIA_EXTRACTION_JS` 重命名为 `_ARIA_EXTRACTION_JS_FALLBACK`，函数 `_extract_aria_tree` 拆分为 `_extract_via_native` 和 `_extract_via_custom_js`。

### 1.4 保留不变的部分

- `_filter_compact()` — compact 模式过滤逻辑不变
- `_sync_refs_to_dom()` — ref 同步到 DOM 的逻辑不变
- `_detect_page_state()` — 页面状态检测不变
- `_count_interactive()` — 可交互元素计数不变
- `RefGenerator` — 保留，fallback 时使用

### 1.5 测试

在 `tests/test_explore/test_snapshot.py` 中新增：

```python
class TestNativeAriaSnapshot:
    """测试 Playwright 原生 aria_snapshot 集成。"""

    def test_parse_simple_yaml(self):
        """解析简单 YAML 快照。"""
        yaml_text = """
- button "Submit" [ref=e1]
- textbox "Email" [ref=e2]
"""
        result = SnapshotGenerator._parse_aria_yaml(yaml_text)
        assert result["role"] == "generic"  # root
        assert len(result["children"]) == 2
        assert result["children"][0]["role"] == "button"
        assert result["children"][0]["name"] == "Submit"
        assert result["children"][0]["ref"] == "e1"

    def test_parse_nested_yaml(self):
        """解析嵌套 YAML（带缩进的子节点）。"""
        yaml_text = """
- navigation "Main Nav":
  - link "Home" [ref=e1]
  - link "About" [ref=e2]
- main "Content":
  - button "Click me" [ref=e3]
"""
        result = SnapshotGenerator._parse_aria_yaml(yaml_text)
        assert len(result["children"]) == 2
        nav = result["children"][0]
        assert nav["role"] == "navigation"
        assert len(nav["children"]) == 2

    def test_parse_yaml_with_attributes(self):
        """解析带属性的 YAML（checked, level, disabled）。"""
        yaml_text = """
- checkbox [checked] [ref=e1]
- heading "Title" [level=2]
- textbox "Name" [disabled] [ref=e2]
"""
        result = SnapshotGenerator._parse_aria_yaml(yaml_text)
        assert result["children"][0]["ref"] == "e1"
        assert result["children"][2]["disabled"] is True

    def test_parse_yaml_with_text_node(self):
        """解析纯文本节点。"""
        yaml_text = """
- paragraph:
  - text: Hello world
"""
        result = SnapshotGenerator._parse_aria_yaml(yaml_text)
        # text 节点不应生成 AriaNode，但内容应体现在 paragraph 的 name 中

    def test_fallback_to_custom_js(self):
        """当 aria_snapshot 不可用时，降级到自定义 JS。"""
        # 模拟 aria_snapshot 抛出 AttributeError
        ...

    def test_shadow_dom_penetration(self):
        """验证原生 API 能穿透 Shadow DOM。"""
        # 需要一个含 Shadow DOM 的测试页面
        ...
```

---

## 2. Phase 2: LoginGuard 多语言 + 性能优化

### 2.1 目标

修改 `src/core/login_guard.py`：
1. 支持英文 "Sign in / Login / Log in" 检测
2. 减少非必要 JS 调用次数

### 2.2 修改 `_detect_login_prompt` JS

**文件**: `src/core/login_guard.py`，第 191-269 行

**改动 1**: 替换登录关键词检测

将：
```javascript
const LOGIN_TEXT = '登录';    // 登录
const LOGIN_ALT_TEXT = '登陆'; // 登陆
```

替换为：
```javascript
const LOGIN_KEYWORDS = [
  '登录', '登陆',  // 登录、登陆
  '注册',                    // 注册
  '短信验证',        // 短信验证
  'sign in', 'log in', 'login', 'signin',
  'sign up', 'signup', 'register',
  'continue with', 'authorize', 'authentication',
];
const hasLoginText = (text) => {
  const lower = text.toLowerCase();
  return LOGIN_KEYWORDS.some(kw => lower.includes(kw));
};
```

**改动 2**: 扩展 modalClass 正则

将：
```javascript
const modalClass = /(modal|popup|dialog|overlay|mask|passport|login|auth|sign)/i;
```

替换为：
```javascript
const modalClass = /(modal|popup|dialog|overlay|mask|passport|login|auth|sign|signin|register|oauth|sso|credential)/i;
```

### 2.3 新增频率限制

**文件**: `src/core/login_guard.py`，`GenericLoginGuard` 类

新增属性：
```python
def __init__(self, ...):
    # ... 现有属性 ...
    self._last_check_time: float = 0.0
    self._check_interval: float = 0.5  # 500ms 间隔
```

修改 `maybe_wait`：
```python
def maybe_wait(self, action_name: str) -> bool:
    if not self._enabled or self._waiting:
        return False
    # 跳过非交互操作
    if action_name in {
        "before_scroll", "after_scroll",
        "before_wait", "after_wait",
        "before_screenshot", "after_screenshot",
        "before_snapshot", "after_snapshot",
    }:
        return False
    # 频率限制
    now = time.monotonic()
    if now - self._last_check_time < self._check_interval:
        return False
    self._last_check_time = now
    prompt = self._detect_login_prompt()
    if prompt.get("login_required"):
        self._wait_for_completion(action_name)
        return True
    return False
```

### 2.4 优化 JS 选择器

将 `_detect_login_prompt` 中的全量扫描：
```javascript
const loginNodes = Array.from(document.querySelectorAll(
  'button,[role="button"],a,div,section,article,form,span,p'
)).filter(visible).map(...)
```

改为两阶段扫描：
```javascript
// 第一阶段：高命中选择器（快速）
const quickSelectors = [
  'button', '[role="button"]', 'a[href]',
  'input[type="submit"]', 'input[type="button"]',
  '[class*="login" i]', '[class*="sign" i]', '[class*="auth" i]',
  '[class*="register" i]', '[id*="login" i]', '[id*="sign" i]',
];
let loginNodes = Array.from(document.querySelectorAll(quickSelectors.join(',')))
  .filter(visible).map(el => ({el, text: compact(el)}))
  .filter(item => hasLoginText(item.text) && item.text.length <= 1200);

// 第二阶段：如果第一阶段没找到，全量扫描（兜底）
if (loginNodes.length === 0) {
  loginNodes = Array.from(document.querySelectorAll(
    'button,[role="button"],a,div,section,article,form,span,p'
  )).filter(visible).map(el => ({el, text: compact(el)}))
    .filter(item => hasLoginText(item.text) && item.text.length <= 1200);
}
```

### 2.5 测试

在 `tests/test_explore/test_executor.py` 中新增：

```python
def test_english_login_detection():
    """英文登录弹窗应被检测到。"""
    class EnglishLoginPage(FakePage):
        def __init__(self):
            super().__init__()
            self.url = "https://github.com"
            self.login_detected = True

        def evaluate(self, code):
            if "GENERIC_LOGIN_PROMPT_DETECTOR" in code:
                return {
                    "success": True,
                    "login_required": True,
                    "url": self.url,
                    "text": "Sign in",
                }
            return None

    page = EnglishLoginPage()
    executor = ExploreExecutor(page)
    executor.update_snapshot(_snapshot())

    result = executor.execute(
        ActionBatch(actions=[
            Action(action="fill", ref="e2", value="test"),
        ])
    )
    assert result.success is True
    assert result.status == "login_completed"
```

```python
def test_login_check_frequency_limit():
    """500ms 内不重复检查登录弹窗。"""
    page = FakePage()
    check_count = 0
    original_evaluate = page.evaluate

    def counting_evaluate(code):
        nonlocal check_count
        if "GENERIC_LOGIN_PROMPT_DETECTOR" in code:
            check_count += 1
        return original_evaluate(code)

    page.evaluate = counting_evaluate
    executor = ExploreExecutor(page)
    executor.update_snapshot(_snapshot())

    # 快速执行 3 个操作
    executor.execute(ActionBatch(actions=[
        Action(action="fill", ref="e2", value="a"),
        Action(action="fill", ref="e2", value="b"),
        Action(action="fill", ref="e2", value="c"),
    ]))

    # 应该只有 1-2 次检查，而不是 6 次（3*2）
    assert check_count <= 2
```

---

## 3. Phase 3: 自定义 JS Fallback 增强

**仅在 Phase 1 的 `ariaSnapshot()` 方案因兼容性问题无法落地时执行。**

### 3.1 Shadow DOM 穿透

**文件**: `src/core/explore/snapshot.py`，`_ARIA_EXTRACTION_JS` 中的 `walk` 函数

在 `walk` 函数中，遍历子节点之前，先检查 `el.shadowRoot`：

```javascript
const walk = (el, depth = 0, context = '') => {
  if (!el || depth > 10 || !isVisible(el)) return null;
  // ... 现有节点构建逻辑 ...

  const nextContext = name || context;

  // 新增：处理 Shadow DOM
  if (el.shadowRoot) {
    for (const child of Array.from(el.shadowRoot.children)) {
      const childNode = walk(child, depth + 1, nextContext);
      if (childNode) node.children.push(childNode);
    }
  }

  // 现有：处理常规子节点
  for (const child of Array.from(el.children || [])) {
    const childNode = walk(child, depth + 1, nextContext);
    if (childNode) node.children.push(childNode);
  }
  return node;
};
```

同时修改 `isVisible`，使其能处理 Shadow DOM 中的元素：
```javascript
const isVisible = (el) => {
  if (el.nodeType !== Node.ELEMENT_NODE) return false;
  // ... 现有逻辑不变 ...
};
```

### 3.2 扩展 implicitRole

在 `implicitRole` 函数开头，优先检查显式 role 属性：

```javascript
const implicitRole = (el) => {
  // 优先使用显式 role
  const explicit = el.getAttribute('role');
  if (explicit) return explicit;

  const tag = el.tagName.toLowerCase();
  const type = (el.getAttribute('type') || '').toLowerCase();
  // ... 现有映射 ...

  // 补充：常见 class 推断（仅当无显式 role 时）
  const cls = (el.className || '').toString().toLowerCase();
  if (/\bbtn\b/.test(cls) || /\bbutton\b/.test(cls)) return 'button';
  if (/\binput\b/.test(cls) && tag === 'div') return 'textbox';

  return 'generic';
};
```

### 3.3 扩展 accessibleName

在现有降级链中插入 `label[for]` 和 SVG `<title>` 检测：

```javascript
const accessibleName = (el) => {
  // 1. aria-labelledby（现有）
  const ariaLabelledBy = el.getAttribute('aria-labelledby');
  if (ariaLabelledBy) { /* 现有逻辑 */ }

  // 2. aria-label（现有）
  const ariaLabel = el.getAttribute('aria-label');
  if (ariaLabel) return truncate(ariaLabel);

  // 3. title（现有）
  const title = el.getAttribute('title');
  if (title) return truncate(title);

  // 4. alt（现有）
  const alt = el.getAttribute('alt');
  if (alt) return truncate(alt);

  // 5. 新增：label[for] 关联
  if (el.id) {
    const label = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
    if (label) return truncate(label.innerText || label.textContent || '');
  }

  // 6. 新增：closest label 包裹
  const parentLabel = el.closest('label');
  if (parentLabel) return truncate(parentLabel.innerText || parentLabel.textContent || '');

  // 7. placeholder（现有）
  const placeholder = el.getAttribute('placeholder');
  if (placeholder) return truncate(placeholder);

  // 8. 新增：input[type=button/submit] 的 value
  if (el.tagName === 'INPUT') {
    const value = el.getAttribute('value');
    if (value) return truncate(value);
  }

  // 9. 新增：SVG <title>
  const svgTitle = el.querySelector('title');
  if (svgTitle) return truncate(svgTitle.textContent || '');

  // 10. innerText / textContent（现有）
  return truncate(el.innerText || el.textContent || '');
};
```

---

## 4. Phase 4: 脚本跳过逻辑扩展

### 4.1 目标

扩展 `_should_skip_generated_script_for_explore`，使其拦截所有通用搜索引擎脚本。

### 4.2 修改

**文件**: `src/core/agent_loop.py`

新增常量：
```python
_GENERIC_SEARCH_ENGINES = (
    "baidu.com", "google.com", "bing.com",
    "sogou.com", "360.cn", "yandex.com", "duckduckgo.com",
)
```

修改 `_should_skip_generated_script_for_explore`：
```python
def _should_skip_generated_script_for_explore(self, task: str, script: str) -> bool:
    if not self._should_resolve_entry_with_llm(task):
        return False
    try:
        page_url = get_browser_manager().get_page().url
    except Exception:
        page_url = ""
    if not self._is_blank_page(page_url):
        return False
    lowered_script = script.lower()
    return any(engine in lowered_script for engine in self._GENERIC_SEARCH_ENGINES)
```

---

## 5. 文件改动清单

| Phase | 文件 | 改动类型 | 说明 |
|-------|------|----------|------|
| 1 | `pyproject.toml` | 修改 | `playwright>=1.40.0` → `>=1.59.0` |
| 1 | `src/core/explore/snapshot.py` | 重构 | 新增 `_parse_aria_yaml`、`_extract_via_native`；重命名现有 JS 为 fallback |
| 1 | `tests/test_explore/test_snapshot.py` | 新增 | YAML 解析测试、原生 API 测试、fallback 测试 |
| 2 | `src/core/login_guard.py` | 修改 | 多语言关键词、频率限制、JS 选择器优化 |
| 2 | `tests/test_explore/test_executor.py` | 新增 | 英文登录检测测试、频率限制测试 |
| 3 | `src/core/explore/snapshot.py` | 修改 | Shadow DOM 穿透、implicitRole 扩展、accessibleName 扩展（仅在 Phase 1 失败时） |
| 4 | `src/core/agent_loop.py` | 修改 | `_GENERIC_SEARCH_ENGINES` 常量 + 方法修改 |

---

## 6. 验收标准

| 序号 | 验收项 | 验收标准 | Phase |
|------|--------|----------|-------|
| 1 | 原生快照 | `aria_snapshot(mode="ai")` 正确返回 YAML 并解析为 AriaNode 树 | 1 |
| 2 | ref 分配 | 原生 API 返回的 `[ref=eN]` 正确映射到 `AriaNode.ref` | 1 |
| 3 | Shadow DOM | 含 Shadow DOM 的页面，快照能穿透获取内部元素 | 1 |
| 4 | Fallback | Playwright 版本不够时，自动降级到自定义 JS | 1 |
| 5 | Compact 模式 | 原生 API 快照经 `_filter_compact` 过滤后，只保留可交互元素 | 1 |
| 6 | 英文登录 | GitHub 等英文网站的 "Sign in" 弹窗被正确检测 | 2 |
| 7 | 频率限制 | 500ms 内不重复调用 `_detect_login_prompt` | 2 |
| 8 | 非交互跳过 | scroll/wait/screenshot 操作不触发登录检查 | 2 |
| 9 | 搜索引擎拦截 | "在 Google 搜索 xxx" 不生成 baidu.com 脚本 | 4 |

---

## 7. 开发顺序

```
Step 1: pyproject.toml — 更新 Playwright 版本约束
Step 2: snapshot.py — 实现 _parse_aria_yaml()
Step 3: snapshot.py — 实现 _extract_via_native() + fallback 逻辑
Step 4: snapshot.py — 修改 snapshot() 方法集成原生 API
Step 5: test_snapshot.py — 编写并运行测试
Step 6: login_guard.py — 多语言关键词 + 频率限制 + JS 优化
Step 7: test_executor.py — 编写并运行登录检测测试
Step 8: agent_loop.py — 搜索引擎拦截扩展
Step 9: 全量测试 — pytest tests/test_explore/ tests/test_script_engine.py tests/test_agent_loop.py
```

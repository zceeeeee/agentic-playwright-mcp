# 技能开发完整流程

本文档介绍如何从零开始设计、开发、测试和部署一个站点技能。

---

## 流程总览

```
1. 调研 → 2. 设计 → 3. 编码 → 4. 测试 → 5. 部署
   ↓          ↓         ↓         ↓         ↓
 分析网站   定义接口   写脚本    验证功能   提交上线
 选择器     YAML      .py       pytest    git push
```

---

## 第一步：调研目标网站

### 1.1 分析页面结构

```bash
# 启动浏览器，手动探索目标网站
browser-agent gui --port 8081
```

在 GUI 中输入 `打开 https://目标网站.com`，观察页面结构。

### 1.2 识别关键元素

用浏览器开发者工具（F12）找到：

| 元素 | 选择器 | 备选选择器 |
|------|--------|-----------|
| 搜索框 | `#search` | `input[name='q']` |
| 搜索按钮 | `#search-btn` | `button[type='submit']` |
| 登录按钮 | `.login-btn` | `text=登录` |

**选择器优先级**：
1. `#id` — 最稳定
2. `[data-testid='xxx']` — 测试专用，较稳定
3. `input[name='xxx']` — 表单元素常用
4. `.class` — 可能变化
5. `text=xxx` — 文本选择器，易变
6. `//xpath` — 最灵活但最脆弱

### 1.3 记录发现

创建调研文档：

```markdown
# 目标网站调研

## 网站信息
- URL: https://example.com
- 类型: 搜索引擎 / 电商 / 社交

## 关键元素
| 功能 | 选择器 | 备选 | 备注 |
|------|--------|------|------|
| 搜索框 | #q | input[name='q'] | 需要先点击激活 |
| 搜索按钮 | .btn-search | text=Search | 有时用 Enter 提交 |

## 特殊情况
- 需要登录才能使用某些功能
- 有验证码保护
- 页面加载较慢
```

---

## 第二步：设计技能接口

### 2.1 定义 YAML 配置

创建 `domains/目标网站.yaml`：

```yaml
name: example
base_url: https://example.com
locators:
  search_input:
    css:
      - "#q"
      - "input[name='q']"
      - ".search-input"
    xpath:
      - "//input[@id='q']"
  search_button:
    css:
      - "#search-btn"
      - "button[type='submit']"
      - ".btn-search"
    xpath:
      - "//button[contains(text(), 'Search')]"
  login_button:
    css:
      - ".login-btn"
      - "text=登录"
```

### 2.2 定义技能元数据

在 `skills.yaml` 中添加：

```yaml
skills:
  - id: domain/example
    name: 示例网站
    type: domain
    triggers: ["example", "示例", "搜索"]
    url_patterns: ["example.com"]
    description: 在示例网站搜索
    version: "1.0.0"

sources:
  - id: domain/example
    file: "domains/example.py"
    entry: "run"
```

### 2.3 定义函数接口

设计 `run()` 函数的参数：

```python
def run(keyword: str):
    """在示例网站搜索关键词。

    Args:
        keyword: 搜索关键词。

    流程:
        1. 导航到首页
        2. 在搜索框输入关键词
        3. 点击搜索按钮
        4. 等待结果加载
    """
```

---

## 第三步：编写技能脚本

### 3.1 创建技能文件

创建 `src/skill_library/domains/example.py`：

```python
"""示例网站适配器 —— 直接执行或作为范例参考。"""


def run(keyword: str):
    """在示例网站搜索关键词。

    Args:
        keyword: 搜索关键词。
    """
    # 1. 导航到首页
    goto("https://example.com")
    wait_for_navigation()

    # 2. 填写搜索框
    fill("#q", keyword)           # 主选择器

    # 3. 点击搜索按钮
    click("#search-btn")          # 主选择器

    # 4. 等待结果
    wait_for_navigation()
    log(f"搜索完成: {keyword}")


# 选择器备选方案（注释即文档）:
# search_input: #q → input[name='q'] → .search-input
# search_button: #search-btn → button[type='submit'] → .btn-search
```

### 3.2 编写规范

| 规则 | 说明 |
|------|------|
| 函数名 | 必须是 `run` |
| 参数 | 从任务描述中提取的关键词/URL |
| 选择器 | 使用域配置中的选择器，不要硬编码 |
| 等待 | 每次导航后都要 `wait_for_navigation()` |
| 日志 | 用 `log()` 记录关键步骤 |
| 注释 | 在文件末尾记录选择器备选方案 |

### 3.3 可用函数

```python
# 导航
goto(url)                    # 导航到 URL
go_back()                    # 后退
go_forward()                 # 前进
reload()                     # 刷新

# 元素操作
click(selector, ...)         # 点击（支持多个备选）
fill(selector, value, ...)   # 填写（支持多个备选）

# 域配置驱动
smart_click(element, domain) # 域配置点击（带自愈）
smart_fill(element, value, domain)  # 域配置填写

# 组合操作
smart_login(domain, user, pass)
smart_search(domain, keyword)
smart_fill_form(domain, {field: value})

# 等待
wait_for_navigation(timeout=10)
wait_for_element(selector, timeout=10)
wait(seconds)

# 页面信息
url = get_url()
title = get_title()
text = get_text()
screenshot("page.png")

# 输出
print("hello")
log("step completed")
```

---

## 第四步：测试

### 4.1 手动测试（开发阶段）

```bash
# 1. 用 GUI 测试
browser-agent gui --port 8081
# 输入: 在示例网站搜索 Python

# 2. 用 CLI 测试
browser-agent run "在示例网站搜索 Python"

# 3. 用 Python 直接测试
python -c "
from src.core.browser_manager import get_browser_manager, reset_browser_manager
from src.core.script_engine import get_script_engine, reset_script_engine
from src.layer_2.controls import get_controls_exports

reset_browser_manager()
reset_script_engine()

bm = get_browser_manager()
bm.launch(headless=False)  # 有头模式，方便观察

engine = get_script_engine()
engine.register_functions(get_controls_exports())

# 加载并执行技能
from src.skill_library.registry import get_skill_registry, reset_skill_registry
reset_skill_registry()
registry = get_skill_registry(library_dir='src/skill_library')
detail = registry.get_detail('domain/example')

if detail:
    script = detail.source_code + '\\nrun(\"Python\")'
    result = engine.execute(script)
    print(f'Success: {result.success}')
    print(f'Output: {result.output}')
    print(f'URL: {bm.get_page().url}')

bm.close()
"
```

### 4.2 单元测试

创建 `tests/test_skill_example.py`：

```python
"""Tests for example.com skill."""

from unittest.mock import MagicMock, patch
import pytest


class TestExampleSkill:
    """Tests for example.com site adapter."""

    @patch("src.layer_2.controls._DOMAINS_DIR", "/tmp/domains")
    @patch("src.layer_2.controls.load_domain")
    @patch("src.layer_2.controls.get_element_selectors")
    def test_search_success(self, mock_get_sels, mock_load, mock_bm):
        """Should search successfully with valid selectors."""
        from src.layer_3.domain_loader import DomainConfig

        mock_load.return_value = DomainConfig(
            name="example",
            base_url="https://example.com",
            locators={
                "search_input": {"css": ["#q"]},
                "search_button": {"css": ["#search-btn"]},
            },
        )

        def get_sels(config, name):
            return config.locators[name].css

        mock_get_sels.side_effect = get_sels
        bm, page = mock_bm
        page.is_visible.return_value = True

        # Test the skill
        from src.layer_2.controls import smart_search
        result = smart_search("example", "Python")
        assert result["success"] is True

    def test_skill_file_importable(self):
        """Should be able to import the skill file."""
        from src.skill_library.domains.example import run
        assert callable(run)

    def test_skill_registered(self):
        """Should be registered in skills.yaml."""
        import yaml
        with open("src/skill_library/skills.yaml") as f:
            config = yaml.safe_load(f)

        skill_ids = [s["id"] for s in config["skills"]]
        assert "domain/example" in skill_ids
```

### 4.3 集成测试

```bash
# 运行所有测试
make test

# 只运行技能相关测试
python -m pytest tests/test_skill_example.py -v

# 运行测试并查看覆盖率
python -m pytest tests/ -v --tb=short
```

### 4.4 测试检查清单

| 检查项 | 说明 |
|--------|------|
| ✅ 选择器有效 | 所有选择器都能找到元素 |
| ✅ 流程完整 | 从导航到结果，每步都成功 |
| ✅ 错误处理 | 选择器失败时有备选方案 |
| ✅ 等待合理 | 不会因为太快而失败 |
| ✅ 日志清晰 | 关键步骤都有 log 输出 |
| ✅ 单元测试 | mock 测试通过 |
| ✅ 集成测试 | 真实浏览器测试通过 |

---

## 第五步：部署

### 5.1 提交代码

```bash
# 1. 检查代码质量
make lint

# 2. 运行测试
make test

# 3. 提交
git add src/skill_library/domains/example.py
git add src/skill_library/skills.yaml
git add domains/example.yaml
git add tests/test_skill_example.py
git commit -m "feat: add example.com skill with search support"

# 4. 推送
git push
```

### 5.2 更新文档

更新 `README.md` 的已适配站点列表：

```markdown
| 示例网站 | 搜索关键词 |
```

### 5.3 发布

```bash
# 打标签
git tag v0.1.1
git push --tags
```

---

## 完整示例：百度搜索技能

### 调研

```
网站: https://www.baidu.com
搜索框: #kw (CSS), //input[@id='kw'] (XPath)
搜索按钮: #su (CSS), //input[@id='su'] (XPath)
特殊情况: headless 模式需要 CloakBrowser
```

### YAML 配置

```yaml
# domains/example_baidu.yaml
name: baidu
base_url: https://www.baidu.com
locators:
  search_input:
    css: ["#kw", "input[name='wd']", ".s_ipt"]
    xpath: ["//input[@id='kw']"]
  search_button:
    css: ["#su", "input[type='submit']"]
    xpath: ["//input[@id='su']"]
```

### 技能脚本

```python
# src/skill_library/domains/baidu_search.py
def run(keyword: str):
    goto("https://www.baidu.com")
    fill("#kw", keyword)
    click("#su")
    wait_for_navigation()
    log(f"百度搜索完成: {keyword}")
```

### 技能注册

```yaml
# skills.yaml
skills:
  - id: domain/baidu_search
    name: 百度搜索
    type: domain
    triggers: ["百度", "baidu", "搜索"]
    url_patterns: ["baidu.com"]
    description: 在百度搜索关键词
```

### 测试

```python
# tests/test_skill_baidu.py
def test_baidu_search_skill():
    from src.skill_library.domains.baidu_search import run
    assert callable(run)
```

---

## 常见问题

### Q: 选择器找不到元素怎么办？

A:
1. 用浏览器开发者工具确认选择器
2. 添加多个备选选择器
3. 用 `wait_for_element()` 等待元素出现
4. 用 `screenshot()` 截图查看页面状态

### Q: 页面加载太慢怎么办？

A:
1. 增加 `wait_for_navigation()` 的 timeout
2. 用 `wait(seconds)` 等待
3. 检查是否需要登录

### Q: 被反爬检测怎么办？

A:
1. 使用 CloakBrowser（默认已启用）
2. 添加 `humanize=True` 参数
3. 使用代理
4. 增加操作间隔

### Q: 如何处理验证码？

A:
1. 目前框架不支持自动验证码
2. 用有头模式，手动处理
3. 记录到技能文档中，提醒用户

---

## 文件清单

一个完整的技能包含以下文件：

```
agentic-playwright-mcp/
├── domains/
│   └── example.yaml              # 域配置（选择器）
├── src/skill_library/
│   ├── skills.yaml               # 技能注册（元数据）
│   ├── domains/
│   │   └── example.py            # 技能脚本（可执行）
│   └── guides/
│       └── how_to_example.md     # 说明文档
└── tests/
    └── test_skill_example.py     # 单元测试
```

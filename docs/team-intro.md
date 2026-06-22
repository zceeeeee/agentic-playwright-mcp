# 项目介绍：Agentic Playwright MCP

> 本文档面向团队成员，帮助快速理解项目目标、架构设计和协作方式。

---

## 一、这个项目是什么？

**一句话定义**：让 AI Agent 通过编写 Python 脚本来控制浏览器的 MCP Server 框架。

### 解决什么问题？

LLM 能推理、能生成代码，但它**摸不到屏幕**。它需要一个"手"去操作浏览器——点按钮、填表单、截截图。

现有的两种方案都有问题：

| 方案 | 问题 |
|------|------|
| AI 逐个调用工具（navigate→click→screenshot） | 效率低，每步都要等结果，上下文丢失多 |
| 人写固定脚本（Selenium/Playwright） | 不能适应变化，网站改版就失效 |

**我们的方案**：AI 写脚本，脚本引擎在安全沙箱中执行。兼顾灵活性和效率。

### 核心工作流

```
用户说"帮我在百度搜索 Python 教程"
       ↓
AI 查找技能库 → 找到 baidu_search.py（范例）
       ↓
AI 参考范例，生成 Python 脚本
       ↓
脚本引擎在受限沙箱中执行
       ↓
浏览器完成操作，返回结果
```

---

## 二、技术栈

| 组件 | 技术 | 说明 |
|------|------|------|
| 浏览器自动化 | Playwright 1.60 | 控制 Chromium 浏览器 |
| 工具协议 | MCP 1.28 | Model Context Protocol，让 AI 调用工具 |
| 数据校验 | Pydantic 2.13 | 配置文件校验 |
| 配置格式 | YAML | 站点选择器配置 |
| 反检测引擎 | CloakBrowser（可选） | 绕过 Cloudflare 等检测 |
| 文档 | MkDocs + Material | 自动生成 API 文档 |
| 测试 | pytest + pytest-mock | 475 个测试，全部通过 |
| 代码质量 | ruff | lint + format |
| 包管理 | pip + pyproject.toml | 标准 Python 打包 |

---

## 三、架构设计

### 3.1 整体架构

```
┌─────────────────────────────────────────────────────────┐
│  MCP 协议层（8 个工具）                                    │
│  run_task / browse_skills / run_script / analyze_page   │
└──────┬──────────┬──────────┬────────────┬───────────────┘
       │          │          │            │
       ▼          ▼          ▼            ▼
  ┌─────────┐ ┌────────┐ ┌──────────┐ ┌────────┐
  │  Skill  │ │ Script │ │  Agent   │ │ Vision │
  │ Library │ │ Engine │ │  Loop    │ │ Module │
  │ (知识库) │ │(执行器) │ │(状态机)  │ │ (眼睛) │
  └─────────┘ └────┬───┘ └──────────┘ └────────┘
                   │
       ┌───────────┼───────────┐
       ▼           ▼           ▼
 ┌──────────┐ ┌────────┐ ┌─────────┐
 │ Controls │ │ Layer1 │ │ Layer3  │
 │ (控件层)  │ │(原语层) │ │(域配置) │
 └──────────┘ └────────┘ └─────────┘
                   │
                   ▼
 ┌─────────────────────────────────┐
 │  Playwright / CloakBrowser      │
 └─────────────────────────────────┘
```

### 3.2 分层职责

| 层 | 目录 | 职责 | 谁来写 |
|----|------|------|--------|
| **MCP 协议层** | `src/server.py` | 对外暴露工具，薄封装 | 框架维护者 |
| **Agent 循环** | `src/core/agent_loop.py` | 自主执行任务的状态机 | 框架维护者 |
| **脚本引擎** | `src/core/script_engine.py` | 受限沙箱执行 AI 脚本 | 框架维护者 |
| **视觉模块** | `src/core/vision.py` | 截图 + LLM 分析页面 | 框架维护者 |
| **控件层** | `src/layer_2/controls.py` | 高级操作函数 | 框架维护者 |
| **原语层** | `src/layer_1/actions.py` | 原子操作 | 框架维护者 |
| **域配置层** | `src/layer_3/` | YAML 管理 + 自愈 | 框架维护者 |
| **技能库** | `src/skill_library/` | 站点适配器 + 通用模板 | **所有人** |
| **域配置文件** | `domains/*.yaml` | 站点选择器 | **所有人** |

**核心思想**：框架层（core/layer_*）由框架维护者负责，**技能库和域配置是所有人可以贡献的内容层**。

---

## 四、关键概念

### 4.1 脚本引擎（Script Engine）

AI 生成的 Python 脚本在一个**受限沙箱**中执行：

```python
# ✅ 可以用的函数
goto("https://example.com")      # 导航
click("#button", ".fallback")    # 点击（支持多个备选选择器）
fill("#input", "hello")          # 输入
screenshot("page.png")           # 截图
smart_login("github", "u", "p")  # 自动登录
print("done")                    # 输出
log("step completed")            # 日志

# ❌ 禁止的操作
import os                        # 禁止 import
open("/etc/passwd")              # 禁止文件访问
eval("1+1")                      # 禁止 eval
subprocess.run(["rm", "-rf"])    # 禁止子进程
```

### 4.2 自愈机制（Self-Healing）

选择器不是写死的，是运行时动态排序的：

```yaml
# domains/baidu.yaml
search_input:
  css:
    - "#kw"                # 主选择器
    - "input[name='wd']"   # 备选 1
    - ".s_ipt"             # 备选 2
```

运行时：
1. 先尝试 `#kw` → 如果失败
2. 尝试 `input[name='wd']` → 如果成功
3. **自动将 `input[name='wd']` 提升到第一位**
4. 下次运行时优先使用提升后的选择器

像免疫系统一样自我修复。

### 4.3 Agent 循环（Agent Loop）

自主执行任务的状态机：

```
OBSERVE（观察）→ PLAN（规划）→ ACT（执行）→ OBSERVE ...
     ↓                ↓             ↓
  截图+分析       查技能库/       执行脚本
  当前页面        生成脚本        返回结果
```

**失败恢复**：
1. 脚本执行失败 → 自愈机制（选择器降级）
2. 选择器全部失败 → 视觉 fallback（用 LLM 看截图找元素）
3. 视觉 fallback 失败 → 记录经验，尝试其他方案

### 4.4 插件系统（SkillBase）

所有技能继承 `SkillBase` 抽象类：

```python
from src.skill_library.skill_base import SkillBase, SkillContext, SkillResult

class BaiduSearchSkill(SkillBase):
    id = "domain/baidu_search"
    name = "百度搜索"
    type = "domain"
    triggers = ["百度", "搜索", "baidu"]
    url_patterns = ["baidu.com"]
    description = "在百度搜索关键词"

    def execute(self, page, context: SkillContext) -> SkillResult:
        goto("https://www.baidu.com")
        fill("#kw", context.variables.get("keyword", ""))
        click("#su")
        wait_for_navigation()
        return SkillResult(success=True, output="搜索完成")
```

---

## 五、目录结构

```
agentic-playwright-mcp/
│
├── src/                              # 源代码
│   ├── server.py                     # MCP 入口（8 个工具）
│   ├── cli.py                        # CLI (serve/run/doctor)
│   ├── config.py                     # 配置加载
│   ├── logging.py                    # 结构化日志
│   │
│   ├── core/                         # 核心引擎
│   │   ├── agent_loop.py             # Agent 循环
│   │   ├── script_engine.py          # 脚本执行引擎
│   │   ├── browser_manager.py        # 浏览器管理
│   │   ├── event_bus.py              # 事件钩子
│   │   └── vision.py                 # 视觉模块
│   │
│   ├── layer_1/                      # 原语层
│   │   └── actions.py                # goto/click/fill/screenshot
│   │
│   ├── layer_2/                      # 控件层
│   │   └── controls.py               # smart_login/smart_search/...
│   │
│   ├── layer_3/                      # 域配置层
│   │   ├── domain_loader.py          # YAML 加载
│   │   └── config_updater.py         # 自愈写回
│   │
│   └── skill_library/                # 技能库（**主要贡献区**）
│       ├── skill_base.py             # SkillBase 抽象类
│       ├── skills.yaml               # 声明式配置
│       ├── registry.py               # 技能注册
│       ├── domains/                  # 站点适配器
│       │   ├── baidu_search.py
│       │   └── github_login.py
│       ├── interactions/             # 通用模板
│       │   ├── login_flow.py
│       │   ├── search_flow.py
│       │   ├── form_fill.py
│       │   └── pagination.py
│       └── guides/                   # 说明文档
│
├── domains/                          # 站点选择器配置（**主要贡献区**）
│   └── example_baidu.yaml
│
├── skills/                           # 声明式技能配置
│   ├── baidu_search.yaml
│   └── generic_login.yaml
│
├── tests/                            # 测试（475 个）
├── docs/                             # MkDocs 文档
├── examples/                         # 示例脚本
└── .github/workflows/ci.yml         # CI 配置
```

---

## 六、快速上手

### 6.1 环境准备

```bash
# 克隆仓库
git clone https://github.com/zceeeeee/agentic-playwright-mcp.git
cd agentic-playwright-mcp

# 创建虚拟环境
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 一键安装（依赖 + Playwright 浏览器）
make dev

# 配置环境变量
cp .env.example .env
# 编辑 .env，填入 API Key（可选，analyze_page 工具需要）
```

### 6.2 验证安装

```bash
# 跑测试
make test

# 检查环境
python -m src.cli doctor

# 启动 MCP 服务
make run
```

### 6.3 运行示例

```bash
python examples/01_basic_browser.py    # 基础浏览器操作
python examples/02_script_engine.py    # 脚本引擎演示
python examples/03_domain_automation.py # 域配置自动化
```

---

## 七、如何贡献

### 7.1 添加站点适配器（最常见）

**第一步**：创建域配置文件

```yaml
# domains/my_site.yaml
name: my_site
base_url: https://www.mysite.com
locators:
  login_button:
    css:
      - "#login-btn"
      - "a[href='/login']"
      - "text=登录"
    xpath:
      - "//button[contains(text(), '登录')]"
  search_input:
    css:
      - "#search"
      - "input[name='q']"
```

**第二步**：创建技能脚本

```python
# src/skill_library/domains/my_site.py
"""我的网站适配器。"""

def run(keyword: str):
    """在搜索关键词。"""
    goto("https://www.mysite.com")
    fill("#search", keyword)          # 主选择器
    click("#search-btn")              # 主选择器
    wait_for_navigation()
    log(f"搜索完成: {keyword}")

# 选择器备选方案（注释即文档）:
# search_input: #search → input[name='q'] → .search-box
# search_button: #search-btn → button[type='submit'] → .btn-search
```

**第三步**：注册到 skills.yaml

```yaml
# skills.yaml
skills:
  - id: domain/my_site
    name: 我的网站
    type: domain
    triggers: ["我的网站", "mysite", "搜索"]
    url_patterns: ["mysite.com"]
    description: 在我的网站搜索
```

**第四步**：测试

```bash
# 测试选择器
python -c "
from src.layer_3.domain_loader import load_domain, get_element_selectors
cfg = load_domain('my_site', domains_dir='domains')
print(get_element_selectors(cfg, 'search_input'))
"

# 测试完整流程
make test
```

### 7.2 添加通用交互模板

```python
# src/skill_library/interactions/download_flow.py
"""通用下载流程模板。"""

def run(url: str, download_selector: str, wait_seconds: float = 5.0):
    """点击下载按钮并等待下载开始。"""
    goto(url)
    click(download_selector)
    wait(wait_seconds)
    log("下载已触发")
```

### 7.3 添加说明文档

```markdown
# src/skill_library/guides/how_to_download_flow.md

# 如何实现下载流程

## 适用场景
需要从网站下载文件。

## 模式
1. 导航到目标页
2. 定位下载按钮
3. 点击下载
4. 等待下载完成

## 常见陷阱
- 有的网站下载按钮是 `<a>` 标签
- 有的需要先登录才能下载
- 下载可能需要较长时间
```

---

## 八、开发规范

### 8.1 代码规范

- **Python 版本**：3.11+
- **类型注解**：公开函数必须有类型注解
- **文档字符串**：Google 风格（中文或英文，同一文件内保持一致）
- **命名**：函数/变量用 `snake_case`，类用 `PascalCase`
- **导入**：每个模块顶部加 `from __future__ import annotations`

### 8.2 选择器规范

**严禁在 Python 代码中硬编码选择器。** 所有选择器必须：
- 存放在 `domains/*.yaml` 中
- 通过 `load_domain()` + `get_element_selectors()` 加载
- 每个元素至少提供 2 个备选选择器

### 8.3 Git 工作流

```bash
# 1. 从 main 创建分支
git checkout -b feat/my-feature

# 2. 开发 + 测试
make test
make lint

# 3. 提交
git add .
git commit -m "feat: add my_site adapter"

# 4. 推送 + 创建 PR
git push origin feat/my-feature
```

### 8.4 提交信息规范

```
<type>: <简短描述>

# type: feat, fix, refactor, test, docs, chore
# 示例:
feat: add my_site adapter with search support
fix: handle timeout in do_click fallback chain
docs: update architecture diagram
test: add agent loop integration tests
```

---

## 九、测试

### 9.1 运行测试

```bash
make test           # 运行所有测试（475 个）
make test-verbose   # 详细输出
make lint           # 代码检查
make format         # 自动修复格式
```

### 9.2 测试结构

| 测试文件 | 覆盖范围 |
|---------|---------|
| `test_actions.py` | 原子操作 |
| `test_controls.py` | 控件层 |
| `test_script_engine.py` | 脚本引擎 + 沙箱安全 |
| `test_agent_loop.py` | Agent 循环 |
| `test_skill_registry.py` | 技能注册 |
| `test_domain_loader.py` | YAML 解析 |
| `test_config_updater.py` | 自愈机制 |
| `test_vision.py` | 视觉模块 |
| `test_browser_manager.py` | 浏览器管理 |
| `test_server.py` | MCP 工具 |

### 9.3 添加新测试

```python
# tests/test_my_module.py
from unittest.mock import MagicMock, patch
import pytest

class TestMyFeature:
    def test_success(self):
        # 测试成功路径
        pass

    def test_failure(self):
        # 测试失败路径
        pass

    @patch("src.my_module.some_dependency")
    def test_with_mock(self, mock_dep):
        # 测试依赖 mock
        pass
```

---

## 十、CLI 命令

```bash
# 启动 MCP 服务
browser-agent serve

# 启动 Web GUI
browser-agent gui --port 8081

# 单次执行任务（调试用）
browser-agent run "帮我在百度搜索 Python 教程"
browser-agent run "截图" --headless
browser-agent run "访问某网站" --cloak

# 检查环境
browser-agent doctor
```

---

## 十一、当前能力与限制

### 能直接用的 ✅

| 场景 | 怎么用 | 效果 |
|------|--------|------|
| **Web GUI** | `browser-agent gui` | 网页可视化操作，输入任务直接执行 |
| **MCP Server** | Claude Desktop 连接 | 8 个工具直接可用 |
| **自主任务** | `run_task("帮我在百度搜索 Python 教程")` | Agent 自动：截图→查技能→执行→返回结果 |
| **脚本执行** | `run_script(code="goto('https://baidu.com')")` | 沙箱执行，返回结果 |
| **经验复用** | 自动 | 相同任务第二次执行时自动复用已保存脚本 |
| **技能查找** | `browse_skills(query="百度")` | 返回匹配的 16 个技能 |
| **页面分析** | `analyze_page(question="登录按钮在哪？")` | 截图 + LLM 分析页面 |
| **CLI 调试** | `browser-agent run "截图"` | 单次执行，查看结果 |
| **Python SDK** | `from src.sdk import AgentLoop` | 代码集成 |

### 能用但有限制的 ⚠️

| 场景 | 限制 |
|------|------|
| **复杂任务**（登录→搜索→翻页→提取数据） | Agent 循环的脚本生成是规则匹配，不能处理复杂逻辑 |
| **未适配的网站** | 13 个站点适配器，其他网站靠通用模板或视觉 fallback |
| **视觉 fallback** | 需要 API Key，有延迟，坐标精度有限 |
| **Agent 循环** | 最大步数限制（默认 10 步），超长任务会中断 |

### 还不能做的 ❌

| 场景 | 原因 |
|------|------|
| **全自动无人值守** | Agent 循环的推理能力依赖 LLM 客户端，服务端没有自己的 AI |
| **脚本保存复用** | 没有持久化机制，每次都是重新生成 |
| **多页面/多 tab** | 只支持单页面操作 |
| **记住登录状态** | 没有状态管理，每次重新开始 |
| **处理验证码** | 没有验证码识别能力 |
| **处理弹窗/模态框** | 没有专门的弹窗处理逻辑 |
| **文件上传/下载** | 没有实现 |
| **iframe 内操作** | 没有处理 |

### 能力评估

| 维度 | 程度 | 说明 |
|------|------|------|
| **简单任务**（搜索、导航、截图） | 90% | 直接能用 |
| **中等任务**（登录、填表、翻页） | 60% | 有模板，但需要适配 |
| **复杂任务**（多步骤、跨页面） | 30% | Agent 循环能跑，但推理能力有限 |
| **企业级任务**（无人值守、高可靠） | 10% | 需要脚本持久化、状态管理、错误恢复 |

### 待完成 🔲

| 功能 | 优先级 | 说明 |
|------|--------|------|
| LLM 驱动脚本生成 | 高 | 用 LLM 生成脚本，覆盖任意网站 |
| 更多站点适配器 | 高 | 扩充到 30+ 站点 |
| 多页面支持 | 中 | 多 tab、多窗口、iframe |
| 页面状态管理 | 中 | 记住"已登录"等状态 |
| 性能监控 | 低 | 脚本执行时间、成功率统计 |

---

## 十二、常见问题

### Q: 需要配置 API Key 吗？

A: 只有 `analyze_page` 工具需要 API Key（ANTHROPIC_API_KEY 或 OPENAI_API_KEY）。其他工具不需要。

### Q: 如何切换 CloakBrowser？

A: 在 `.env` 中设置 `USE_CLOAKBROWSER=true`，然后 `pip install -e ".[stealth]"`。

### Q: 测试怎么跑？

A: `make test`，558 个测试全部用 mock，不需要真实浏览器。

### Q: 如何调试脚本？

A: 用 `browser-agent run "任务描述"` 单次执行，查看输出和截图。

### Q: 选择器失效了怎么办？

A: 自愈机制会自动降级到备选选择器，并提升成功的备选到第一位。如果所有选择器都失败，Agent 会用视觉 fallback。

### Q: 怎么启动 GUI？

A: 运行 `browser-agent gui --port 8081`，然后打开浏览器访问 http://localhost:8081

### Q: 怎么用 Python SDK？

A: `from src.sdk import AgentLoop`，然后 `with AgentLoop() as agent: result = agent.run("任务描述")`

---

## 十三、联系方式

- **仓库地址**：https://github.com/zceeeeee/agentic-playwright-mcp
- **Issues**：在 GitHub 上提 issue
- **文档**：`make docs` 启动本地文档服务器

---

## 附录：架构决策记录（ADR）

| ADR | 标题 | 状态 |
|-----|------|------|
| [001](adr/001-three-layer-architecture.md) | 三层架构设计 | 已采纳 |
| [002](adr/002-sandboxed-script-engine.md) | 受限沙箱脚本引擎 | 已采纳 |
| [003](adr/003-agent-loop-design.md) | Agent 循环设计 | 已采纳 |

详细内容见 `docs/adr/` 目录。

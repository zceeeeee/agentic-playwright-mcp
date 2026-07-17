# Agentic Playwright MCP

让 AI Agent 写 Python 脚本来控制浏览器的 MCP Server 框架。

基于 Playwright，支持可选的 [CloakBrowser](https://github.com/CloakHQ/CloakBrowser) 反检测引擎。

## 核心理念

**AI 不是逐个调用工具，而是编写 Python 脚本。** 用得越多，系统越聪明。

```
用户意图 → 技能路由器（关键词快筛 + LLM 精排）→ 命中 → 参数化脚本生成 → 脚本引擎执行 → 浏览器操作
   ↳ 若未命中 → 经验库查找 → 生成临时脚本 → 沙箱执行 → 保存经验
   ↳ 若规则失败 → LLM 意图解析（兜底） → 结构化意图 → 生成脚本
   ↳ 若执行失败 → 自愈机制 → 视觉 fallback → 记录新知识
```

## 四层架构

```
Layer 0: Panel    (用户交互)     ← panel/: inject.js + panel_manager.py
Layer 3: Domains  (站点经验)     ← domains/*.yaml + workspace/knowledge/
Layer 2: Skills   (肌肉记忆)     ← controls.py + skill_library/
Layer 1: Helpers  (原语)          ← actions.py: goto/click/fill/screenshot
```

| 层级 | 职责 | 进化方式 |
|------|------|---------|
| **Layer 0** | 浏览器内交互面板 | Shadow DOM 注入，脚本/MCP 双向控制 |
| **Layer 1** | 原子操作 | 不变 |
| **Layer 2** | 控件函数 | 扩展新函数 |
| **Layer 3** | 站点经验 | 选择器自愈 + 知识积累 |

## 当前能力

| 场景 | 程度 | 说明 |
|------|------|------|
| **简单任务**（搜索、导航、截图） | ✅ 可用 | 直接跑通 |
| **中等任务**（登录、填表、翻页） | ⚠️ 有限 | 有模板，需要适配站点 |
| **复杂任务**（多步骤、跨页面） | ⚠️ 有限 | Agent 循环能跑，推理能力有限 |

**已适配站点**：百度、搜狗、当当、B站、头条、CSDN、百科、天气、微博、掘金、IT之家、菜鸟教程、开源中国

## 交互面板（Layer 0）

浏览器启动后自动注入一个交互面板，用户可以通过输入框、按钮与自动化程序双向通信。

```
┌─────────────────────────┐
│ 🤖  Agentic Panel   [—] │  ← 默认最小化，点击展开
├─────────────────────────┤
│ 输入                    │
│ [________________] [提交]│  ← 用户输入数据，程序通过 panel_read() 读取
│                         │
│ 日志                    │
│ ┌─────────────────────┐ │
│ │ 正在搜索...          │ │  ← 程序通过 panel_log() 写入
│ │ 找到 10 个结果       │ │
│ └─────────────────────┘ │
│                         │
│      Agentic Playwright │
└─────────────────────────┘
```

**技术特性**：
- **Shadow DOM 隔离**：面板样式不受宿主页面影响
- **键盘事件隔离**：页面 JS 无法拦截面板输入
- **自动存活保护**：被页面移除后自动重建
- **跨页面持久**：通过 `addInitScript` 注入，导航/刷新/新标签页自动生效

**三种操控方式**：

| 方式 | 场景 | 示例 |
|------|------|------|
| 脚本函数 | `run_script` / agent loop | `panel_log("进度 50%")` |
| MCP 工具 | Claude 等客户端 | `panel_prompt(question="继续?")` |
| Python API | 项目内部代码 | `get_panel_manager().log(page, "msg")` |

## 快速开始

```bash
# 克隆
git clone https://github.com/zceeeeee/agentic-playwright-mcp.git
cd agentic-playwright-mcp

# 安装
pip install -e .
playwright install chromium

# 启动 GUI
browser-agent gui --port 8081
```

打开浏览器访问 **http://localhost:8081**

## Docker 部署

```bash
# 克隆
git clone https://github.com/zceeeeee/agentic-playwright-mcp.git
cd agentic-playwright-mcp

# 构建镜像
docker compose build

# 启动服务（后台运行）
docker compose up -d

# 查看日志
docker compose logs -f
```

服务启动后，MCP 客户端可通过 `http://localhost:8000` 连接。

**环境变量**：在项目根目录创建 `.env` 文件配置 API Key：

```env
ANTHROPIC_API_KEY=sk-ant-your-key-here
OPENAI_API_KEY=sk-your-key-here

# LLM 意图解析兜底（可选，规则失败时自动调用）
# OPENAI_BASE_URL=https://api.openai.com/v1
# OPENAI_MODEL=gpt-4o-mini
```

**MCP 配置（Claude Desktop）**：

```json
{
  "mcpServers": {
    "browser": {
      "url": "http://localhost:8000/mcp"
    }
  }
}
```

**停止服务**：

```bash
docker compose down
```

## 使用方式

### Web GUI

```bash
browser-agent gui --port 8081
```

### CLI

```bash
browser-agent setup                                    # 首次配置（交互式）
browser-agent serve                                    # MCP 服务
browser-agent run "帮我在百度搜索 Python 教程"          # 单次执行
browser-agent doctor                                   # 检查环境
browser-agent gui                                      # 启动 Web GUI
```

### Python SDK

```python
from src.sdk import AgentLoop

with AgentLoop(headless=True) as agent:
    result = agent.run("帮我在百度搜索 Python 教程")
    print(result.output)
```

### MCP（Claude Desktop）

```json
{
  "mcpServers": {
    "browser": {
      "command": "browser-agent",
      "args": ["serve"]
    }
  }
}
```

## MCP 工具列表（18 个）

| 工具 | 说明 |
|------|------|
| `run_task` | 自然语言驱动的自主 Agent 循环 |
| `browse_skills` | 按关键词或 URL 查找技能库 |
| `get_skill` | 获取技能源码和说明文档 |
| `run_script` | 在受限沙箱中执行 Python 脚本 |
| `analyze_page` | 截图 + 多模态 LLM 分析页面 |
| `browser_launch` | 启动 Chromium 浏览器 |
| `browser_launch_with_domain` | 带站点 cookie 启动浏览器 |
| `auth_list` | 列出所有站点的登录状态 |
| `auth_save` | 保存当前站点的 cookie |
| `auth_delete` | 删除某站点的 cookie |
| `screenshot` | 截取当前页面截图 |
| `ping` | 健康检查 |
| `panel_toggle` | 显示/隐藏交互面板 |
| `panel_read` | 读取用户输入数据和事件 |
| `panel_log` | 向面板写入日志 |
| `panel_set_title` | 设置面板标题 |
| `panel_prompt` | 向用户提问并等待回答 |
| `panel_set_fields` | 动态更新面板表单字段 |

## 脚本引擎可用函数

```python
# 导航
goto("https://example.com")
go_back()

# 元素操作（支持多个备选选择器）
click("#button", ".fallback-btn")
fill("#input", "hello")

# 域配置驱动（带自愈）
smart_click("search_button", domain="baidu")
smart_fill("search_input", "Python 教程", domain="baidu")

# 组合操作
smart_login("github", "user", "pass")  # 登录后自动保存 cookie
smart_search("baidu", "Python 教程")
smart_fill_form("example", {"name": "张三", "email": "test@test.com"})

# Cookie 持久化
save_cookies("baidu")        # 手动保存当前站点 cookie
load_cookies("baidu")        # 加载已保存的 cookie（重建 context）

# JavaScript 执行
run_js('document.querySelector("#kw").value = "Python"')

# 等待
wait_for_navigation(timeout=10)
wait_for_element("#result", timeout=10)
wait(2.0)

# 页面信息
url = get_url()
title = get_title()
text = get_text()
screenshot("page.png")

# 交互面板（Layer 0）
panel_log("正在搜索...")                    # 写日志到面板
answer = panel_prompt("请输入关键词:")       # 向用户提问（阻塞等待）
data = panel_read()                         # 读取用户输入数据
events = panel_read_events()                # 读取并清空事件队列
panel_show()                                # 显示面板
panel_hide()                                # 隐藏面板
panel_set_title("任务进度")                  # 设置面板标题
panel_set_fields([                          # 动态更新表单字段
    {"name": "keyword", "label": "关键词", "type": "text", "placeholder": "输入搜索词"},
    {"name": "action", "label": "操作", "type": "select", "options": ["搜索", "取消"]},
])
```

## 经验进化系统

参考 Browser Harness 的 `agent-workspace` 模式：

```
workspace/
├── scripts/              # 成功的脚本（自动保存，自动复用）
├── selectors/            # 选择器经验（成功/失败记录）
└── knowledge/            # 站点知识（gotchas + patterns）
```

- **脚本复用**：相同任务第二次执行时自动复用已保存脚本
- **选择器经验**：记录每个选择器的成功/失败次数，按可靠性排序
- **站点知识**：记录每个网站的特殊行为和注意事项

## LLM 客户端

统一的 AI 模型调用接口，支持 OpenAI 兼容 API 和 Anthropic Claude。

```python
from src.core.llm_client import get_llm_client

client = get_llm_client()

# 接口 1: 自由文本对话
reply = client.chat("用一句话解释什么是 Playwright")

# 接口 2: 结构化 JSON 输出
result = client.chat_json(
    "用户说: 在百度搜索 Python 教程",
    system_prompt="提取站点和关键词",
    schema={"site": "string", "keyword": "string"},
)
# → {"site": "baidu", "keyword": "Python 教程"}
```

**Provider 配置**（`.env`）：

```env
# 切换 provider: "openai" (默认) | "anthropic"
LLM_PROVIDER=openai

# OpenAI 兼容 API
OPENAI_API_KEY=sk-your-key
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o-mini

# Anthropic
ANTHROPIC_API_KEY=sk-ant-your-key
ANTHROPIC_MODEL=claude-haiku-4-5-20251001

# 通用参数
LLM_TEMPERATURE=0
LLM_MAX_TOKENS=1024
LLM_TIMEOUT=30
```

启动 GUI 时如果没有配置 API Key，会自动弹出引导界面。

## CloakBrowser 反检测引擎

```bash
pip install -e ".[stealth]"
USE_CLOAKBROWSER=true browser-agent gui
```

| 检测服务 | Playwright | CloakBrowser |
|---------|-----------|-------------|
| reCAPTCHA v3 | 0.1 (bot) | **0.9** (human) |
| Cloudflare Turnstile | FAIL | **PASS** |
| FingerprintJS | DETECTED | **PASS** |

## 本地 Chrome 持久登录模式

桌面端进入“浏览器设置”，将“浏览器模式”切换为“本地 Chrome”。
FeatherDesk 会打开电脑上安装的 Google Chrome，并使用独立且持久保存的
`~/.featherdesk/chrome-profile`。第一次在这个窗口手动登录网站后，后续任务会
复用该登录状态。

也可以通过环境变量启用：

```bash
BROWSER_ENGINE=local_chrome
LOCAL_CHROME_DEBUG_PORT=9222
# 可选：LOCAL_CHROME_PATH=C:\Program Files\Google\Chrome\Application\chrome.exe
# 可选：LOCAL_CHROME_USER_DATA=D:\FeatherDesk\chrome-profile
```

不要把 `LOCAL_CHROME_USER_DATA` 设置成日常 Chrome 的默认 User Data 目录。
Chrome 136 起不允许对默认数据目录启用远程调试；使用专属目录也能避免配置
冲突或损坏。关闭任务时 FeatherDesk 只关闭任务标签页，不会退出本地 Chrome。

## Cookie 持久化

支持按站点保存和恢复登录状态（cookie + localStorage），使用 Playwright 的 `storage_state` 机制。

```bash
# 启动时自动加载已保存的 cookie
browser_launch_with_domain("baidu")

# 登录后自动保存（smart_login 会自动触发）
smart_login("github", "user", "pass")

# 手动管理
auth_list          # 查看所有站点的登录状态
auth_save("baidu") # 手动保存
auth_delete("baidu") # 删除
```

**存储位置**：`~/.agentic-playwright/auth/{domain}.json`

**自动适配**：新增 `domains/*.yaml` 站点时，自动支持对应的 cookie 管理，无需额外配置。

## 项目结构

```
agentic-playwright-mcp/
├── src/
│   ├── server.py                  # MCP 入口（18 个工具）
│   ├── cli.py                     # CLI (serve/run/doctor/gui)
│   ├── sdk.py                     # Python SDK
│   ├── core/
│   │   ├── agent_loop.py          # Agent 循环引擎
│   │   ├── skill_router.py        # 技能路由器（关键词快筛 + LLM 精排）
│   │   ├── llm_client.py          # LLM 客户端（chat / chat_json 双接口）
│   │   ├── auth_manager.py        # Cookie 持久化管理
│   │   ├── script_engine.py       # 脚本执行引擎（注入面板函数）
│   │   ├── script_generator.py    # 任务意图解析（规则）
│   │   ├── intent_parser.py       # LLM 意图解析（兜底）
│   │   ├── experience.py          # 经验进化系统
│   │   ├── browser_manager.py     # 多引擎浏览器管理（自动注入面板）
│   │   ├── event_bus.py           # 事件钩子系统
│   │   ├── recovery.py            # 错误恢复
│   │   └── vision.py              # 视觉模块
│   ├── panel/                     # Layer 0: 交互面板
│   │   ├── inject.js              # Shadow DOM 面板（注入浏览器）
│   │   └── panel_manager.py       # 面板管理器（Python 端）
│   ├── gui/app.py                 # Web GUI
│   ├── layer_1/actions.py         # 原子操作
│   ├── layer_2/controls.py        # 高级控件函数
│   ├── layer_3/                   # 域配置 + 自愈
│   └── skill_library/             # 标准脚本库
├── domains/                       # 站点选择器配置（19 个）
├── workspace/                     # 经验存储
├── tests/                         # 685 个测试
├── docs/                          # MkDocs 文档
├── examples/                      # 示例脚本
└── Makefile
```

## 开发

```bash
make dev      # 安装依赖
make test     # 跑测试（570 个）
make lint     # 代码检查
make format   # 自动修复
make docs     # 启动文档服务器
```

## License

MIT

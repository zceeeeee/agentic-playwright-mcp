# Agentic Playwright MCP

让 AI Agent 写 Python 脚本来控制浏览器的 MCP Server 框架。

基于 Playwright，支持可选的 [CloakBrowser](https://github.com/CloakHQ/CloakBrowser) 反检测引擎。

## 核心理念

**AI 不是逐个调用工具，而是编写 Python 脚本。** 用得越多，系统越聪明。

```
用户意图 → AI 查找技能 → 参考范例生成脚本 → 脚本引擎执行 → 浏览器操作
   ↳ 若未命中 → 查经验库 → 生成临时脚本 → 沙箱执行 → 保存经验
   ↳ 若失败 → 自愈机制 → 视觉 fallback → 记录新知识
```

## 三层进化架构

```
Layer 3: Domains (站点经验)     ← domains/*.yaml + workspace/knowledge/
Layer 2: Skills  (肌肉记忆)     ← controls.py + skill_library/
Layer 1: Helpers (原语)          ← actions.py: goto/click/fill/screenshot
```

| 层级 | 职责 | 进化方式 |
|------|------|---------|
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

## 使用方式

### Web GUI

```bash
browser-agent gui --port 8081
```

### CLI

```bash
browser-agent serve                                    # MCP 服务
browser-agent run "帮我在百度搜索 Python 教程"          # 单次执行
browser-agent doctor                                   # 检查环境
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

## MCP 工具列表（8 个）

| 工具 | 说明 |
|------|------|
| `run_task` | 自然语言驱动的自主 Agent 循环 |
| `browse_skills` | 按关键词或 URL 查找技能库 |
| `get_skill` | 获取技能源码和说明文档 |
| `run_script` | 在受限沙箱中执行 Python 脚本 |
| `analyze_page` | 截图 + 多模态 LLM 分析页面 |
| `browser_launch` | 启动 Chromium 浏览器 |
| `screenshot` | 截取当前页面截图 |
| `ping` | 健康检查 |

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
smart_login("github", "user", "pass")
smart_search("baidu", "Python 教程")
smart_fill_form("example", {"name": "张三", "email": "test@test.com"})

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

## 项目结构

```
agentic-playwright-mcp/
├── src/
│   ├── server.py                  # MCP 入口（8 个工具）
│   ├── cli.py                     # CLI (serve/run/doctor/gui)
│   ├── sdk.py                     # Python SDK
│   ├── core/
│   │   ├── agent_loop.py          # Agent 循环引擎
│   │   ├── script_engine.py       # 脚本执行引擎
│   │   ├── script_generator.py    # 任务意图解析
│   │   ├── experience.py          # 经验进化系统
│   │   ├── browser_manager.py     # 双引擎浏览器管理
│   │   ├── event_bus.py           # 事件钩子系统
│   │   ├── recovery.py            # 错误恢复
│   │   └── vision.py              # 视觉模块
│   ├── gui/app.py                 # Web GUI
│   ├── layer_1/actions.py         # 原子操作
│   ├── layer_2/controls.py        # 高级控件函数
│   ├── layer_3/                   # 域配置 + 自愈
│   └── skill_library/             # 标准脚本库
├── domains/                       # 站点选择器配置（19 个）
├── workspace/                     # 经验存储
├── tests/                         # 570 个测试
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

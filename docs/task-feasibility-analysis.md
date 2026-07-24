# 任务可行性分析报告

> 目标命令：**"在BOSS直聘搜索深圳地区的AI产品经理岗位，分析前5页的内容进行总结，导出一份PDF报告"**
>
> 分析日期：2026-07-23

---

## 任务拆解

该命令可拆分为三个子任务：

| 序号 | 子任务 | 描述 |
|------|--------|------|
| 1 | 搜索数据 | 访问 BOSS 直聘，搜索"深圳 + AI产品经理"，翻阅前 5 页 |
| 2 | 导出数据 | 提取 5 页职位列表的结构化数据（职位名、公司、薪资、要求等） |
| 3 | 处理数据 | 分析总结数据，生成 PDF 报告 |

---

## 命令解析能力分析

### 解析链路

```
用户指令 → TaskSplitter（拆分子任务）→ IntentParser（解析意图）→ ScriptGenerator（生成脚本）/ Explore 模式
```

### TaskSplitter 拆分能力

`src/core/task_splitter.py` 支持的分隔符：

| 分隔符 | 模式 | 结果 |
|--------|------|------|
| `。` / `.` | 句号 | 独立任务组（每组开新标签页） |
| `;` / `；` | 分号 | 连续任务组（同标签页顺序执行） |
| `然后`、`接着`、`并且` 等 | 连接词 | 独立任务组 |
| `，` / `,` | **逗号** | **❌ 不支持** |

**问题**：目标命令使用逗号分隔子任务，TaskSplitter 不会触发拆分，整条指令被当作单任务处理。

```
"在BOSS直聘搜索深圳地区的AI产品经理岗位，分析前5页的内容进行总结，导出一份PDF报告"
                                 ↑ 逗号                                    ↑ 逗号
```

TaskSplitter 有 LLM 兜底拆分（`_llm_split`），当规则拆不出多个子任务时会调用 LLM。但：
- LLM 拆分器的 prompt 只要求拆分为"独立的可执行操作步骤"
- 不理解"搜索→导出→处理"之间的数据依赖关系
- 拆出的子任务之间 **没有数据传递机制**

### IntentParser 意图解析

`src/core/intent_parser.py` 支持的 action 类型：

```python
_ACTIONS = [
    "search",       # 搜索
    "navigate",     # 导航到 URL
    "screenshot",   # 截图
    "extract",      # 提取页面文本
    "fill",         # 填写表单
    "paginate",     # 翻页遍历
    "login",        # 登录
    "click",        # 点击元素
    "scroll",       # 滚动页面
    "wait",         # 等待
    "hot_search",   # 查看热搜
]
```

已知网站列表：

```python
_KNOWN_SITES = {
    "baidu", "google", "bing", "sogou", "so",
    "dangdang", "csdn", "gitee", "baike", "toutiao",
    "zhihu", "douban", "bilibili", "weibo", "wenku",
    "taobao", "jd", "pdd", "weather", "amazon",
    "youtube", "github", "gmail", "outlook",
}
```

**问题**：BOSS 直聘不在已知网站列表中，`boss` 也不是已知的 engine 标识。

### ScriptGenerator 脚本生成

`src/core/script_generator.py` 支持的任务类型：

| 类型 | 说明 | BOSS 直聘适用？ |
|------|------|----------------|
| search | 提取关键词 + 选择搜索引擎 | ❌ 不支持 BOSS 直聘 |
| navigate | 提取 URL 直接导航 | ⚠️ 可以但无后续操作 |
| screenshot | 截图 | ✅ |
| extract | 提取页面文本 | ✅ 但无结构化 |
| paginate | 翻页遍历 | ❌ 没有对应的脚本模板 |
| login | 填写用户名密码 | ❌ 不支持 BOSS 直聘 |
| **analyze** | **不存在** | ❌ |
| **export** | **不存在** | ❌ |

### 命令解析逐环节评估

| 解析环节 | 能否处理该命令 | 原因 |
|----------|---------------|------|
| TaskSplitter 拆分 | ❌ | 逗号分隔不支持，LLM 兜底拆出的子任务无数据传递 |
| IntentParser 意图 | ❌ | 不支持"分析"和"导出"这两个 action |
| ScriptGenerator 脚本 | ❌ | 无 BOSS 直聘模板、无翻页模板、无分析/导出模板 |
| Explore 模式 | ⚠️ 部分 | 能导航和搜索，但无法表达"提取5页数据→分析→导出"的流程 |

### 命令解析层缺失的关键 action

| 缺失 action | 说明 | 影响 |
|-------------|------|------|
| `paginate_extract` | 多页数据采集（翻页 + 逐页提取 + 累积） | 无法完成 5 页数据采集 |
| `analyze` | 数据分析（结构化、统计、总结） | 无法完成数据分析 |
| `export` | 报告导出（PDF/Word 生成） | 无法完成报告导出 |
| `composite` | 多步骤组合任务（搜索→分析→导出） | 无法表达复合流程 |

---

## 子任务 1：搜索数据

### ✅ 已具备的能力

| 能力 | 实现方式 | 代码位置 |
|------|---------|---------|
| 导航到 BOSS 直聘 | Explore agent 通过 Bing 搜索 + LLM 解析入口 URL | `src/core/explore/agent.py` `_resolve_entry_url_via_search()` |
| 填写搜索关键词 | ARIA 快照找到搜索框 → `fill` + `keyboard(Enter)` | `src/core/explore/agent.py` `plan_actions()` |
| 选择城市"深圳" | Explore planner 识别城市选择器并点击 | Explore executor 的 `click` action |
| 翻页（5 页） | Explore executor 支持 click 翻页 | `src/core/explore/executor.py` |
| 登录检测与人工介入 | `pause_for_input` 暂停等用户手动登录 | `src/core/explore/agent.py` `plan_actions()` 规则 13 |
| 循环/熔断检测 | 页面签名比对 + 连续失败计数 | `src/core/explore/agent.py` `_check_loop_detection()` |

### ❌ 缺失或存在风险

| 问题 | 严重度 | 说明 |
|------|--------|------|
| **反爬机制** | 🔴 高 | BOSS 直聘有严格的反爬策略（验证码、指纹检测、请求频率限制）。项目无验证码解决、无代理轮换、无指纹伪装 |
| **入口表缺失** | 🟡 中 | `_ENTRYPOINTS` 硬编码表不包含 `boss.zhipin.com`，需走 Bing 搜索解析间接定位，存在失败风险 |
| **登录墙** | 🔴 高 | BOSS 直聘大部分搜索功能需要登录。`LoginGuard` 能检测并暂停，但完全无人值守不可能 |
| **步数预算紧张** | 🟡 中 | 搜索 + 选城市 ≈ 4 步，5 页翻页 + 等待 ≈ 10 步，剩余 6 步容错，合计约 20 步（`max_steps` 默认上限） |

### 建议

1. 用户预先手动登录 BOSS 直聘，通过 `auth_save` 保存 cookies
2. 后续使用 `browser_launch_with_domain` 加载已认证会话
3. 将 `max_steps` 提升至 30+ 以预留容错空间

---

## 子任务 2：导出数据

### ✅ 已具备的能力

| 能力 | 实现方式 | 代码位置 |
|------|---------|---------|
| 提取页面文本 | `get_page_text()` → `document.body.innerText` | `src/layer_2/controls.py:633` |
| 执行 JS 提取结构化数据 | `run_js(code)` 在页面上下文执行自定义 JS | `src/layer_2/controls.py:550` |
| LLM 解析非结构化文本 | `llm_generate_text()` 在脚本内调用 LLM | `src/core/script_engine.py:350` |

### ❌ 缺失

| 问题 | 严重度 | 说明 |
|------|--------|------|
| **无结构化数据提取函数** | 🔴 高 | 没有内置的"从列表页提取表格"通用函数。需要为 BOSS 直聘编写专用 JS 提取脚本 |
| **跨页数据无法累积** | 🔴 高 | 脚本沙箱每次执行独立，无共享状态。翻页后前一页的数据丢失 |
| **脚本沙箱禁止文件操作** | 🟡 中 | 无法将中间数据写入磁盘，只能通过 `print()` 输出或 `panel_log()` 中转 |
| **无数据持久化机制** | 🟡 中 | 没有 JSON/CSV 等格式的数据导出工具 |

### 建议

1. 新增 `data_collector` 工具，支持跨步累积 JSON 数据到内存
2. 新增 BOSS 直聘专用 skill（JS 脚本提取职位列表：职位名、公司名、薪资、地点、经验要求）
3. 在脚本引擎中开放有限的文件写入能力（如只允许写入 `out/` 目录）

---

## 子任务 3：处理数据

### ✅ 已具备的能力

| 能力 | 实现方式 | 代码位置 |
|------|---------|---------|
| LLM 文本总结 | `llm_generate_text()` 可做摘要分析 | `src/core/script_engine.py:350` |
| 生成 PDF | `wps_writer_export()` 支持 Markdown → PDF | `src/layer_2/controls.py:712` |
| 表格插入 PDF | `table_json` 参数支持最多 5 张表、每表 100 行 | `src/layer_1/wps_writer.py` |
| 自定义字体/样式 | 支持字体、字号、颜色、标题格式等 | `wps_writer_export()` 参数 |

### ❌ 缺失

| 问题 | 严重度 | 说明 |
|------|--------|------|
| **无统计分析能力** | 🟡 中 | 无 pandas/numpy，无法做薪资分布统计、岗位数量趋势等量化分析 |
| **无可视化图表** | 🟡 中 | 无 matplotlib/plotly，无法生成图表嵌入报告 |
| **WPS Office 依赖** | 🟡 中 | `wps_writer_export` 依赖 Windows 上安装 WPS Office（COM 自动化），未安装则无法生成 PDF |
| **分析完全依赖 LLM** | 🟢 低 | "分析"只能是 LLM 文本总结，无法做精确的数据统计 |

### 建议

1. 引入 pandas 做基础数据统计（薪资分布、经验要求分布等）
2. 确认目标环境已安装 WPS Office + pywin32
3. 考虑增加 `reportlab` 或 `weasyprint` 作为不依赖 WPS 的 PDF 备选方案

---

## 跨任务架构缺口

三个任务串起来暴露的是 **架构层面** 的缺失，不仅仅是单个功能的缺失：

### 1. 无任务编排层

当前项目是 **单任务浏览器自动化引擎**，`run_task()` 接收一个自然语言指令，执行到完成或失败。

```
当前架构:  用户指令 → AgentLoop(OBSERVE→PLAN→ACT) → 结果

需要的架构: 用户指令 → 任务编排器
                        ├── 子任务1: 搜索数据 → AgentLoop → 中间结果1
                        ├── 子任务2: 导出数据 → AgentLoop → 中间结果2（依赖结果1）
                        └── 子任务3: 处理数据 → AgentLoop → 最终报告（依赖结果1+2）
```

**缺口**：
- 子任务之间无法传递数据（搜索结果无法交给导出任务）
- 无法表达任务依赖关系
- 步数预算在任务间不共享也不重置

### 2. 无中间数据存储

浏览器操作产生的数据（职位列表）需要在多个步骤间持久化：

```
当前:  Step1(提取) → print() → 丢失
需要:  Step1(提取) → DataStore → Step2(翻页) → DataStore → Step3(分析) → 读取 DataStore
```

**缺口**：
- 脚本沙箱禁止 `import`、文件操作、网络请求
- 没有内存级的数据共享机制
- `panel_log` 只能显示文本，不能结构化存储

### 3. 无数据分析 pipeline

从"提取原始数据"到"生成报告"缺少中间处理环节：

```
当前:  原始文本 → LLM 总结 → PDF
需要:  原始文本 → 结构化提取 → 数据清洗 → 统计分析 → 可视化 → LLM 总结 → PDF
```

**缺口**：
- 无结构化数据提取管道
- 无数据清洗/转换工具
- 无统计分析和可视化能力

---

## 总结

### 可行性评估

| 子任务 | 可行性 | 前提条件 |
|--------|--------|---------|
| 搜索数据 | ⚠️ 有条件可行 | 用户预登录 + cookies 保存 + max_steps 提升 |
| 导出数据 | ❌ 当前不可行 | 需新增数据提取 skill + 跨页累积机制 |
| 处理数据 | ⚠️ 部分可行 | LLM 总结 + PDF 导出可行，统计分析不可行 |

### 需要新增的能力（按优先级）

| 优先级 | 能力 | 类型 | 工作量 |
|--------|------|------|--------|
| P0 | 跨页数据累积机制 | 架构改动 | 中 |
| P0 | BOSS 直聘数据提取 skill | 新增 skill | 中 |
| P1 | 任务编排层（子任务依赖 + 数据传递） | 架构新增 | 大 |
| P1 | 步数预算管理（任务间重置/共享） | 代码改动 | 小 |
| P2 | pandas 数据分析支持 | 新增依赖 | 小 |
| P2 | 不依赖 WPS 的 PDF 备选方案 | 新增依赖 | 小 |
| P3 | 可视化图表生成 | 新增依赖 | 中 |
| P3 | 验证码处理/反爬绕过 | 新增能力 | 大 |

### 最现实的落地路径

1. **短期**（可跑通）：用户手动登录 → 单页搜索 → `get_page_text` 提取 → LLM 总结 → `wps_writer_export` 导出 PDF（仅 1 页数据）
2. **中期**（多页支持）：新增 data_collector + BOSS 直聘提取 skill → 5 页数据累积 → LLM 分析 → PDF
3. **长期**（全自动）：任务编排层 + 反爬策略 + 数据分析 pipeline → 完整的无人值守数据采集分析流程

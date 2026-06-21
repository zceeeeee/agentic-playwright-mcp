# 站点目录 — 20 个国内可访问网站

本文档列出 20 个适合自动化的国内网站，包含目标 URL、关键选择器、自动化流程和注意事项。

---

## 目录

| # | 网站 | 类型 | 难度 | 自动化场景 |
|---|------|------|------|-----------|
| 1 | 百度搜索 | 搜索引擎 | ⭐ | 搜索、提取结果 |
| 2 | 必应中国 | 搜索引擎 | ⭐ | 搜索、提取结果 |
| 3 | 搜狗搜索 | 搜索引擎 | ⭐ | 搜索、提取结果 |
| 4 | 360 搜索 | 搜索引擎 | ⭐ | 搜索、提取结果 |
| 5 | 淘宝 | 电商 | ⭐⭐ | 搜索商品、提取价格 |
| 6 | 京东 | 电商 | ⭐⭐ | 搜索商品、提取价格 |
| 7 | 拼多多 | 电商 | ⭐⭐ | 搜索商品 |
| 8 | 当当网 | 电商 | ⭐ | 搜索书籍、提取信息 |
| 9 | 微博 | 社交 | ⭐⭐ | 搜索、提取热搜 |
| 10 | 知乎 | 社交 | ⭐⭐ | 搜索、提取回答 |
| 11 | 豆瓣 | 社交 | ⭐⭐ | 搜索电影/书籍、提取评分 |
| 12 | B站 | 视频 | ⭐⭐ | 搜索视频、提取信息 |
| 13 | 今日头条 | 资讯 | ⭐ | 搜索、提取新闻 |
| 14 | CSDN | 技术 | ⭐ | 搜索技术文章 |
| 15 | Gitee | 代码托管 | ⭐ | 搜索仓库、提取信息 |
| 16 | 百度百科 | 知识 | ⭐ | 搜索词条、提取简介 |
| 17 | 百度文库 | 文档 | ⭐⭐ | 搜索文档 |
| 18 | QQ邮箱 | 邮箱 | ⭐⭐⭐ | 登录、查看收件箱 |
| 19 | 163邮箱 | 邮箱 | ⭐⭐⭐ | 登录、查看收件箱 |
| 20 | 天气网 | 工具 | ⭐ | 查询天气 |

---

## 1. 百度搜索

| 属性 | 值 |
|------|-----|
| URL | https://www.baidu.com |
| 类型 | 搜索引擎 |
| 难度 | ⭐ |
| 反爬 | headless 检测（需 CloakBrowser） |

### 选择器

| 元素 | CSS | XPath | 备选 |
|------|-----|-------|------|
| 搜索框 | `#kw` | `//input[@id='kw']` | `input[name='wd']` |
| 搜索按钮 | `#su` | `//input[@id='su']` | `input[type='submit']` |

### 自动化流程

```python
def run(keyword: str):
    goto("https://www.baidu.com")
    fill("#kw", keyword)
    click("#su")
    wait_for_navigation()
    log(f"百度搜索: {keyword}")
```

### 注意事项
- headless 模式会被检测，需使用 CloakBrowser
- 搜索结果页面 URL 格式: `https://www.baidu.com/s?wd=关键词`

---

## 2. 必应中国

| 属性 | 值 |
|------|-----|
| URL | https://cn.bing.com |
| 类型 | 搜索引擎 |
| 难度 | ⭐ |
| 反爬 | 较弱 |

### 选择器

| 元素 | CSS | XPath | 备选 |
|------|-----|-------|------|
| 搜索框 | `#sb_form_q` | `//input[@id='sb_form_q']` | `textarea[name='q']` |
| 搜索按钮 | `#sb_form_go` | `//input[@id='sb_form_go']` | `button[type='submit']` |

### 自动化流程

```python
def run(keyword: str):
    goto("https://cn.bing.com")
    fill("#sb_form_q", keyword)
    click("#sb_form_go")
    wait_for_navigation()
    log(f"必应搜索: {keyword}")
```

### 注意事项
- 国内版可直接访问，无需代理
- 搜索结果页面较干净，容易提取

---

## 3. 搜狗搜索

| 属性 | 值 |
|------|-----|
| URL | https://www.sogou.com |
| 类型 | 搜索引擎 |
| 难度 | ⭐ |
| 反爬 | 较弱 |

### 选择器

| 元素 | CSS | XPath | 备选 |
|------|-----|-------|------|
| 搜索框 | `#query` | `//input[@id='query']` | `input[name='query']` |
| 搜索按钮 | `#stb` | `//input[@id='stb']` | `input[type='submit']` |

### 自动化流程

```python
def run(keyword: str):
    goto("https://www.sogou.com")
    fill("#query", keyword)
    click("#stb")
    wait_for_navigation()
    log(f"搜狗搜索: {keyword}")
```

### 注意事项
- 搜狗搜索比较容易自动化
- 支持微信文章搜索

---

## 4. 360 搜索

| 属性 | 值 |
|------|-----|
| URL | https://www.so.com |
| 类型 | 搜索引擎 |
| 难度 | ⭐ |
| 反爬 | 较弱 |

### 选择器

| 元素 | CSS | XPath | 备选 |
|------|-----|-------|------|
| 搜索框 | `#input` | `//input[@id='input']` | `input[name='q']` |
| 搜索按钮 | `#search-button` | `//button[@id='search-button']` | `button[type='submit']` |

### 自动化流程

```python
def run(keyword: str):
    goto("https://www.so.com")
    fill("#input", keyword)
    click("#search-button")
    wait_for_navigation()
    log(f"360搜索: {keyword}")
```

### 注意事项
- 域名是 so.com，不是 360.com
- 搜索结果页面结构清晰

---

## 5. 淘宝

| 属性 | 值 |
|------|-----|
| URL | https://www.taobao.com |
| 类型 | 电商 |
| 难度 | ⭐⭐ |
| 反爬 | 强（需登录、滑块验证） |

### 选择器

| 元素 | CSS | XPath | 备选 |
|------|-----|-------|------|
| 搜索框 | `#q` | `//input[@id='q']` | `input[name='q']` |
| 搜索按钮 | `.btn-search` | `//button[contains(@class,'btn-search')]` | `button[type='submit']` |

### 自动化流程

```python
def run(keyword: str):
    goto("https://www.taobao.com")
    wait_for_navigation()
    fill("#q", keyword)
    click(".btn-search")
    wait_for_navigation()
    log(f"淘宝搜索: {keyword}")
```

### 注意事项
- 需要登录才能搜索
- 有滑块验证码保护
- 建议使用 CloakBrowser + 有头模式
- 搜索结果页面动态加载，需要等待

---

## 6. 京东

| 属性 | 值 |
|------|-----|
| URL | https://www.jd.com |
| 类型 | 电商 |
| 难度 | ⭐⭐ |
| 反爬 | 中等 |

### 选择器

| 元素 | CSS | XPath | 备选 |
|------|-----|-------|------|
| 搜索框 | `#key` | `//input[@id='key']` | `input[name='keyword']` |
| 搜索按钮 | `.button` | `//button[contains(@class,'button')]` | `button[type='submit']` |

### 自动化流程

```python
def run(keyword: str):
    goto("https://www.jd.com")
    wait_for_navigation()
    fill("#key", keyword)
    click(".button")
    wait_for_navigation()
    log(f"京东搜索: {keyword}")
```

### 注意事项
- 无需登录即可搜索
- 搜索结果页面结构清晰
- 价格信息容易提取

---

## 7. 拼多多

| 属性 | 值 |
|------|-----|
| URL | https://www.pinduoduo.com |
| 类型 | 电商 |
| 难度 | ⭐⭐ |
| 反爬 | 中等 |

### 选择器

| 元素 | CSS | XPath | 备选 |
|------|-----|-------|------|
| 搜索框 | `input[placeholder*='搜索']` | `//input[contains(@placeholder,'搜索')]` | `.search-input` |
| 搜索按钮 | `.search-btn` | `//button[contains(@class,'search')]` | `button[type='submit']` |

### 自动化流程

```python
def run(keyword: str):
    goto("https://www.pinduoduo.com")
    wait_for_navigation()
    fill("input[placeholder*='搜索']", keyword)
    click(".search-btn")
    wait_for_navigation()
    log(f"拼多多搜索: {keyword}")
```

### 注意事项
- 页面动态加载较多
- 需要等待搜索结果渲染

---

## 8. 当当网

| 属性 | 值 |
|------|-----|
| URL | https://www.dangdang.com |
| 类型 | 电商（书籍） |
| 难度 | ⭐ |
| 反爬 | 弱 |

### 选择器

| 元素 | CSS | XPath | 备选 |
|------|-----|-------|------|
| 搜索框 | `#key_S` | `//input[@id='key_S']` | `input[name='key']` |
| 搜索按钮 | `.button` | `//button[contains(@class,'button')]` | `input[type='submit']` |

### 自动化流程

```python
def run(keyword: str):
    goto("https://www.dangdang.com")
    wait_for_navigation()
    fill("#key_S", keyword)
    click(".button")
    wait_for_navigation()
    log(f"当当搜索: {keyword}")
```

### 注意事项
- 书籍信息丰富，适合爬取
- 页面结构较简单

---

## 9. 微博

| 属性 | 值 |
|------|-----|
| URL | https://weibo.com |
| 类型 | 社交媒体 |
| 难度 | ⭐⭐ |
| 反爬 | 中等（需登录） |

### 选择器

| 元素 | CSS | XPath | 备选 |
|------|-----|-------|------|
| 搜索框 | `#search-input` | `//input[@id='search-input']` | `input[name='q']` |
| 搜索按钮 | `[node-type='searchbtn']` | `//a[@node-type='searchbtn']` | `.search-btn` |
| 热搜列表 | `.hot-list li` | `//li[contains(@class,'hot')]` | `.rank-list li` |

### 自动化流程

```python
def run(keyword: str):
    goto("https://s.weibo.com")
    wait_for_navigation()
    fill("#search-input", keyword)
    click("[node-type='searchbtn']")
    wait_for_navigation()
    log(f"微博搜索: {keyword}")
```

### 注意事项
- 需要登录才能搜索
- 热搜页面: https://s.weibo.com/top/summary
- 搜索结果动态加载

---

## 10. 知乎

| 属性 | 值 |
|------|-----|
| URL | https://www.zhihu.com |
| 类型 | 问答社区 |
| 难度 | ⭐⭐ |
| 反爬 | 中等 |

### 选择器

| 元素 | CSS | XPath | 备选 |
|------|-----|-------|------|
| 搜索框 | `.Input-wrapper input` | `//div[contains(@class,'Input-wrapper')]//input` | `input[name='q']` |
| 搜索按钮 | `.SearchBar-searchButton` | `//button[contains(@class,'SearchBar')]` | `button[type='submit']` |

### 自动化流程

```python
def run(keyword: str):
    goto("https://www.zhihu.com/search")
    wait_for_navigation()
    fill(".Input-wrapper input", keyword)
    click(".SearchBar-searchButton")
    wait_for_navigation()
    log(f"知乎搜索: {keyword}")
```

### 注意事项
- 搜索页面直接访问: https://www.zhihu.com/search?type=content&q=关键词
- 回答内容需要展开阅读

---

## 11. 豆瓣

| 属性 | 值 |
|------|-----|
| URL | https://www.douban.com |
| 类型 | 社交/评分 |
| 难度 | ⭐⭐ |
| 反爬 | 中等 |

### 选择器

| 元素 | CSS | XPath | 备选 |
|------|-----|-------|------|
| 搜索框 | `#inp-query` | `//input[@id='inp-query']` | `input[name='q']` |
| 搜索按钮 | `.bn` | `//input[contains(@class,'bn')]` | `input[type='submit']` |

### 自动化流程

```python
def run(keyword: str):
    goto("https://www.douban.com")
    wait_for_navigation()
    fill("#inp-query", keyword)
    click(".bn")
    wait_for_navigation()
    log(f"豆瓣搜索: {keyword}")
```

### 注意事项
- 电影/书籍评分信息丰富
- 搜索结果页面: https://search.douban.com/movie/搜索?q=关键词
- 需要处理翻页

---

## 12. B站 (Bilibili)

| 属性 | 值 |
|------|-----|
| URL | https://www.bilibili.com |
| 类型 | 视频平台 |
| 难度 | ⭐⭐ |
| 反爬 | 中等 |

### 选择器

| 元素 | CSS | XPath | 备选 |
|------|-----|-------|------|
| 搜索框 | `.nav-search-input` | `//input[contains(@class,'nav-search-input')]` | `input[placeholder*='搜索']` |
| 搜索按钮 | `.nav-search-btn` | `//button[contains(@class,'nav-search-btn')]` | `.search-btn` |

### 自动化流程

```python
def run(keyword: str):
    goto("https://search.bilibili.com/all?keyword=" + keyword)
    wait_for_navigation()
    log(f"B站搜索: {keyword}")
```

### 注意事项
- 可以直接通过 URL 搜索: https://search.bilibili.com/all?keyword=关键词
- 视频信息包括标题、播放量、时长
- 需要处理动态加载

---

## 13. 今日头条

| 属性 | 值 |
|------|-----|
| URL | https://www.toutiao.com |
| 类型 | 资讯平台 |
| 难度 | ⭐ |
| 反爬 | 弱 |

### 选择器

| 元素 | CSS | XPath | 备选 |
|------|-----|-------|------|
| 搜索框 | `input[placeholder*='搜索']` | `//input[contains(@placeholder,'搜索')]` | `.search-input` |
| 搜索按钮 | `.search-btn` | `//button[contains(@class,'search')]` | `button[type='submit']` |

### 自动化流程

```python
def run(keyword: str):
    goto("https://so.toutiao.com/search?keyword=" + keyword)
    wait_for_navigation()
    log(f"头条搜索: {keyword}")
```

### 注意事项
- 可以直接通过 URL 搜索
- 新闻信息包括标题、来源、时间
- 页面结构较简单

---

## 14. CSDN

| 属性 | 值 |
|------|-----|
| URL | https://www.csdn.net |
| 类型 | 技术社区 |
| 难度 | ⭐ |
| 反爬 | 弱 |

### 选择器

| 元素 | CSS | XPath | 备选 |
|------|-----|-------|------|
| 搜索框 | `#toolbar-search-input` | `//input[@id='toolbar-search-input']` | `input[name='q']` |
| 搜索按钮 | `.toolbar-search-btn` | `//button[contains(@class,'toolbar-search')]` | `button[type='submit']` |

### 自动化流程

```python
def run(keyword: str):
    goto("https://so.csdn.net/so/search?q=" + keyword)
    wait_for_navigation()
    log(f"CSDN搜索: {keyword}")
```

### 注意事项
- 可以直接通过 URL 搜索
- 技术文章信息丰富
- 需要处理登录弹窗

---

## 15. Gitee

| 属性 | 值 |
|------|-----|
| URL | https://gitee.com |
| 类型 | 代码托管 |
| 难度 | ⭐ |
| 反爬 | 弱 |

### 选择器

| 元素 | CSS | XPath | 备选 |
|------|-----|-------|------|
| 搜索框 | `#search-input` | `//input[@id='search-input']` | `input[name='q']` |
| 搜索按钮 | `.search-btn` | `//button[contains(@class,'search')]` | `button[type='submit']` |

### 自动化流程

```python
def run(keyword: str):
    goto("https://search.gitee.com/?type=repository&q=" + keyword)
    wait_for_navigation()
    log(f"Gitee搜索: {keyword}")
```

### 注意事项
- 国内版 GitHub，访问速度快
- 仓库信息包括 Stars、Forks、语言
- 搜索结果页面结构清晰

---

## 16. 百度百科

| 属性 | 值 |
|------|-----|
| URL | https://baike.baidu.com |
| 类型 | 知识百科 |
| 难度 | ⭐ |
| 反爬 | 弱 |

### 选择器

| 元素 | CSS | XPath | 备选 |
|------|-----|-------|------|
| 搜索框 | `#query` | `//input[@id='query']` | `input[name='word']` |
| 搜索按钮 | `.search-btn` | `//button[contains(@class,'search')]` | `input[type='submit']` |

### 自动化流程

```python
def run(keyword: str):
    goto("https://baike.baidu.com")
    wait_for_navigation()
    fill("#query", keyword)
    click(".search-btn")
    wait_for_navigation()
    log(f"百度百科搜索: {keyword}")
```

### 注意事项
- 百科内容结构化，容易提取
- 页面加载较快
- 可以直接通过 URL 访问: https://baike.baidu.com/item/关键词

---

## 17. 百度文库

| 属性 | 值 |
|------|-----|
| URL | https://wenku.baidu.com |
| 类型 | 文档平台 |
| 难度 | ⭐⭐ |
| 反爬 | 中等 |

### 选择器

| 元素 | CSS | XPath | 备选 |
|------|-----|-------|------|
| 搜索框 | `#search-input` | `//input[@id='search-input']` | `input[name='q']` |
| 搜索按钮 | `.search-btn` | `//button[contains(@class,'search')]` | `button[type='submit']` |

### 自动化流程

```python
def run(keyword: str):
    goto("https://wenku.baidu.com")
    wait_for_navigation()
    fill("#search-input", keyword)
    click(".search-btn")
    wait_for_navigation()
    log(f"百度文库搜索: {keyword}")
```

### 注意事项
- 文档预览需要登录
- 搜索结果包括文档类型、页数、评分
- 需要处理翻页

---

## 18. QQ邮箱

| 属性 | 值 |
|------|-----|
| URL | https://mail.qq.com |
| 类型 | 邮箱 |
| 难度 | ⭐⭐⭐ |
| 反爬 | 强（需登录） |

### 选择器

| 元素 | CSS | XPath | 备选 |
|------|-----|-------|------|
| QQ号输入 | `#u` | `//input[@id='u']` | `input[name='u']` |
| 密码输入 | `#p` | `//input[@id='p']` | `input[name='p']` |
| 登录按钮 | `#login_button` | `//input[@id='login_button']` | `button[type='submit']` |

### 自动化流程

```python
def run():
    goto("https://mail.qq.com")
    wait_for_navigation()
    fill("#u", "your_qq_number")
    fill("#p", "your_password")
    click("#login_button")
    wait_for_navigation()
    log("QQ邮箱登录完成")
```

### 注意事项
- 需要 QQ 号和密码
- 有验证码保护
- 登录后需要等待页面加载
- 收件箱页面动态加载

---

## 19. 163邮箱

| 属性 | 值 |
|------|-----|
| URL | https://mail.163.com |
| 类型 | 邮箱 |
| 难度 | ⭐⭐⭐ |
| 反爬 | 强（需登录） |

### 选择器

| 元素 | CSS | XPath | 备选 |
|------|-----|-------|------|
| 邮箱输入 | `#idInput` | `//input[@id='idInput']` | `input[name='email']` |
| 密码输入 | `#pwdInput` | `//input[@id='pwdInput']` | `input[name='password']` |
| 登录按钮 | `#loginBtn` | `//button[@id='loginBtn']` | `button[type='submit']` |

### 自动化流程

```python
def run():
    goto("https://mail.163.com")
    wait_for_navigation()
    fill("#idInput", "your_email@163.com")
    fill("#pwdInput", "your_password")
    click("#loginBtn")
    wait_for_navigation()
    log("163邮箱登录完成")
```

### 注意事项
- 需要邮箱地址和密码
- 有验证码保护
- 登录后需要等待页面加载
- 收件箱页面动态加载

---

## 20. 天气网

| 属性 | 值 |
|------|-----|
| URL | https://www.weather.com.cn |
| 类型 | 工具 |
| 难度 | ⭐ |
| 反爬 | 弱 |

### 选择器

| 元素 | CSS | XPath | 备选 |
|------|-----|-------|------|
| 搜索框 | `#search_input` | `//input[@id='search_input']` | `input[name='q']` |
| 搜索按钮 | `.search-btn` | `//button[contains(@class,'search')]` | `button[type='submit']` |

### 自动化流程

```python
def run(city: str):
    goto("https://www.weather.com.cn")
    wait_for_navigation()
    fill("#search_input", city)
    click(".search-btn")
    wait_for_navigation()
    log(f"天气查询: {city}")
```

### 注意事项
- 天气信息结构化，容易提取
- 可以直接通过 URL 访问: https://www.weather.com.cn/weather/城市代码.shtml
- 页面加载较快

---

## 优先级建议

### 第一批（简单，反爬弱）
1. 百度搜索 ✅ 已完成
2. 必应中国
3. 搜狗搜索
4. 360 搜索
5. 当当网
6. CSDN
7. Gitee
8. 百度百科
9. 天气网
10. 今日头条

### 第二批（中等，需登录或反爬中等）
11. 京东
12. 知乎
13. 豆瓣
14. B站
15. 微博
16. 百度文库
17. 拼多多
18. 淘宝

### 第三批（困难，强反爬或复杂登录）
19. QQ邮箱
20. 163邮箱

---

## 技能开发模板

每个网站的技能文件结构：

```
src/skill_library/
├── domains/
│   ├── baidu_search.py        # ✅ 已完成
│   ├── bing_search.py         # ✅ 已完成
│   ├── sogou_search.py        # 新增
│   ├── so_search.py           # 新增
│   ├── taobao_search.py       # 新增
│   ├── jd_search.py           # 新增
│   ├── pdd_search.py          # 新增
│   ├── dangdang_search.py     # 新增
│   ├── weibo_search.py        # ✅ 已完成
│   ├── zhihu_search.py        # ✅ 已完成
│   ├── douban_search.py       # 新增
│   ├── bilibili_search.py     # 新增
│   ├── toutiao_search.py      # 新增
│   ├── csdn_search.py         # 新增
│   ├── gitee_search.py        # 新增
│   ├── baike_search.py        # 新增
│   ├── wenku_search.py        # 新增
│   ├── qqmail_inbox.py        # 新增
│   ├── mail163_inbox.py       # 新增
│   └── weather_query.py       # 新增
└── skills.yaml                # 更新注册
```

每个技能需要的文件：
1. `domains/{site}.yaml` — 域配置（选择器）
2. `src/skill_library/domains/{site}.py` — 技能脚本
3. `src/skill_library/skills.yaml` — 技能注册
4. `tests/test_skill_{site}.py` — 单元测试

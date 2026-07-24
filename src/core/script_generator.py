"""
脚本生成器 —— 根据任务描述生成 Python 脚本。

支持多种任务类型：
- 搜索任务：提取关键词，选择搜索引擎
- 导航任务：提取 URL，直接导航
- 截图任务：保存当前页面
- 提取任务：提取页面文本/链接
- 表单任务：填写表单字段
- 翻页任务：遍历多页内容
- 登录任务：填写用户名密码
- 复合任务：组合多个操作
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class TaskIntent:
    """解析后的任务意图。"""

    action: (
        str  # search, navigate, screenshot, extract, fill, paginate, login, composite
    )
    target: str = ""  # 目标 URL 或搜索关键词
    parameters: dict = None  # 额外参数

    def __post_init__(self):
        if self.parameters is None:
            self.parameters = {}


class ScriptGenerator:
    """根据任务描述生成 Python 脚本。

    选择器从 domains/*.yaml 加载，不在代码中硬编码。
    """

    # 网站元数据（URL 和名称，选择器从 YAML 加载）
    SITE_META = {
        "baidu": {"url": "https://www.baidu.com", "name": "百度"},
        "google": {"url": "https://www.google.com", "name": "Google"},
        "bing": {"url": "https://cn.bing.com", "name": "必应"},
        "sogou": {"url": "https://www.sogou.com", "name": "搜狗"},
        "so": {"url": "https://www.so.com", "name": "360搜索"},
        "dangdang": {"url": "https://www.dangdang.com", "name": "当当"},
        "csdn": {"url": "https://so.csdn.net", "name": "CSDN"},
        "gitee": {"url": "https://search.gitee.com", "name": "Gitee"},
        "baike": {"url": "https://baike.baidu.com", "name": "百度百科"},
        "toutiao": {"url": "https://so.toutiao.com", "name": "今日头条"},
        "zhihu": {"url": "https://www.zhihu.com", "name": "知乎"},
        "douban": {"url": "https://www.douban.com", "name": "豆瓣"},
        "bilibili": {"url": "https://www.bilibili.com", "name": "B站"},
        "weibo": {"url": "https://s.weibo.com", "name": "微博"},
        "wenku": {"url": "https://wenku.baidu.com", "name": "百度文库"},
        "taobao": {"url": "https://www.taobao.com", "name": "淘宝"},
        "jd": {"url": "https://www.jd.com", "name": "京东"},
        "pdd": {"url": "https://www.pinduoduo.com", "name": "拼多多"},
        "weather": {"url": "https://www.weather.com.cn", "name": "天气网"},
        "boss": {"url": "https://www.zhipin.com", "name": "BOSS直聘"},
    }

    # URL 直接搜索的网站（不需要填写表单）
    URL_SEARCH_ENGINES = ["csdn", "gitee", "bilibili", "toutiao"]

    # JS 方式的网站（headless 模式下元素被隐藏）
    JS_ENGINES = [
        "baidu",
        "dangdang",
        "douban",
        "wenku",
        "taobao",
        "jd",
        "pdd",
        "weibo",
    ]

    # URL 直接搜索（不需要填写表单）
    URL_DIRECT_ENGINES = ["zhihu", "baike", "weather"]

    def __init__(self) -> None:
        self._selector_cache: dict[str, dict] = {}

    def _load_selectors(self, engine: str) -> dict:
        """从 domains/*.yaml 加载选择器。"""
        if engine in self._selector_cache:
            return self._selector_cache[engine]

        yaml_path = Path(__file__).parent.parent.parent / "domains" / f"{engine}.yaml"
        if not yaml_path.exists():
            return {}

        try:
            import yaml

            with open(yaml_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)

            locators = data.get("locators", {})
            result = {}
            if "search_input" in locators:
                css_list = locators["search_input"].get("css", [])
                if css_list:
                    result["input"] = css_list[0]
            if "search_button" in locators:
                css_list = locators["search_button"].get("css", [])
                if css_list:
                    result["submit"] = css_list[0]

            self._selector_cache[engine] = result
            return result
        except Exception:
            return {}

    def generate(self, task: str, page_summary: str = "") -> str | None:
        """根据任务描述生成脚本。

        Args:
            task: 用户的任务描述。
            page_summary: 当前页面摘要。

        Returns:
            生成的 Python 脚本，或 None（无法生成）。
        """
        intent = self.parse_intent(task)
        if intent is None:
            return None

        return self._intent_to_script(intent)

    def parse_intent(self, task: str) -> TaskIntent | None:
        """解析任务描述为结构化意图。"""
        task_lower = task.lower().strip()

        # 截图任务（最简单，优先检测）
        if any(kw in task_lower for kw in ["截图", "screenshot", "截屏", "保存页面"]):
            return TaskIntent(action="screenshot")

        # 导航任务
        url = self._extract_url(task)
        if url and any(
            kw in task_lower for kw in ["打开", "导航", "goto", "open", "访问", "去"]
        ):
            return TaskIntent(action="navigate", target=url)

        # 纯 URL 也视为导航
        if url and len(task.strip()) < len(url) + 10:
            return TaskIntent(action="navigate", target=url)

        # 搜索任务
        if any(
            kw in task_lower
            for kw in ["搜索", "search", "查找", "找", "查", "搜", "查询", "lookup"]
        ):
            keyword = self._extract_keyword(task)
            engine = self._detect_search_engine(task)
            if keyword:
                return TaskIntent(
                    action="search",
                    target=keyword,
                    parameters={"engine": engine},
                )

        # 热搜任务
        if any(kw in task_lower for kw in ["热搜", "hot", "trending"]):
            return TaskIntent(action="hot_search")

        # 提取任务
        if any(
            kw in task_lower for kw in ["提取", "extract", "获取文本", "抓取", "爬取"]
        ):
            return TaskIntent(action="extract")

        # 翻页任务
        if any(
            kw in task_lower for kw in ["翻页", "下一页", "next page", "分页", "遍历"]
        ):
            pages = self._extract_number(task, default=5)
            return TaskIntent(action="paginate", parameters={"max_pages": pages})

        # 表单任务
        if any(kw in task_lower for kw in ["填写", "填入", "输入", "fill", "表单"]):
            return TaskIntent(action="fill")

        # 登录任务
        if any(kw in task_lower for kw in ["登录", "login", "sign in", "登陆"]):
            return TaskIntent(action="login")

        # 点击任务
        if any(kw in task_lower for kw in ["点击", "click", "按", "按钮"]):
            target = self._extract_click_target(task)
            if target:
                return TaskIntent(action="click", target=target)

        # 滚动任务
        if any(kw in task_lower for kw in ["滚动", "scroll", "下滑", "上滑"]):
            direction = (
                "down" if any(kw in task_lower for kw in ["下", "down"]) else "up"
            )
            return TaskIntent(action="scroll", parameters={"direction": direction})

        # 等待任务
        if any(kw in task_lower for kw in ["等待", "wait", "暂停"]):
            seconds = self._extract_number(task, default=3)
            return TaskIntent(action="wait", parameters={"seconds": seconds})

        return None

    def _intent_to_script(self, intent: TaskIntent) -> str:
        """将意图转换为 Python 脚本。"""
        if intent.action == "screenshot":
            return self._gen_screenshot()

        if intent.action == "navigate":
            return self._gen_navigate(intent.target)

        if intent.action == "search":
            engine = intent.parameters.get("engine", "baidu")
            return self._gen_search(intent.target, engine)

        if intent.action == "hot_search":
            return self._gen_hot_search()

        if intent.action == "extract":
            return self._gen_extract()

        if intent.action == "paginate":
            max_pages = intent.parameters.get("max_pages", 5)
            return self._gen_paginate(max_pages)

        if intent.action == "fill":
            return self._gen_fill()

        if intent.action == "login":
            return self._gen_login()

        if intent.action == "click":
            return self._gen_click(intent.target)

        if intent.action == "scroll":
            direction = intent.parameters.get("direction", "down")
            return self._gen_scroll(direction)

        if intent.action == "wait":
            seconds = intent.parameters.get("seconds", 3)
            return self._gen_wait(seconds)

        return None

    # -------------------------------------------------------------------
    # 脚本模板
    # -------------------------------------------------------------------

    def _gen_screenshot(self) -> str:
        return 'screenshot("task_screenshot.png")\nlog("截图完成")'

    def _gen_navigate(self, url: str) -> str:
        return f'goto("{url}")\nwait_for_navigation()\nlog("导航完成: {url}")'

    def _gen_search(self, keyword: str, engine: str) -> str:
        meta = self.SITE_META.get(engine, self.SITE_META["baidu"])
        url = meta["url"]
        name = meta["name"]

        # 某些网站支持 URL 直接搜索
        if engine in self.URL_SEARCH_ENGINES:
            return f'goto("{url}")\nwait_for_navigation()\nlog("{name}搜索完成: {keyword}")'

        # 某些网站需要用 URL 直接搜索（不需要填写表单）
        if engine in self.URL_DIRECT_ENGINES:
            if engine == "zhihu":
                return f'goto("https://www.zhihu.com/search?type=content&q={keyword}")\nwait_for_navigation()\nwait(3)\nlog("知乎搜索完成: {keyword}")'
            elif engine == "baike":
                return f'goto("https://baike.baidu.com/item/{keyword}")\nwait_for_navigation()\nwait(3)\nlog("百度百科查询完成: {keyword}")'
            elif engine == "weather":
                return 'goto("https://www.weather.com.cn/weather1d/101010100.shtml")\nwait_for_navigation()\nwait(3)\nlog("天气查询完成")'

        # 从 YAML 加载选择器
        selectors = self._load_selectors(engine)
        inp = selectors.get("input", "input[type='text']")
        btn = selectors.get("submit", "button[type='submit']")

        # 某些网站需要用 JS 操作（headless 模式下元素可能被隐藏）
        if engine in self.JS_ENGINES:
            return (
                f'goto("{url}")\n'
                f"wait_for_navigation()\n"
                f'run_js(\'document.querySelector(\\"{inp}\\").value = \\"{keyword}\\"\')\n'
                f"run_js('document.querySelector(\\\"{btn}\\\").click()')\n"
                f"wait(3)\n"
                f'log("{name}搜索完成: {keyword}")'
            )

        # 表单搜索（默认）
        return (
            f'goto("{url}")\n'
            f"wait_for_navigation()\n"
            f'fill("{inp}", "{keyword}")\n'
            f'click("{btn}")\n'
            f"wait_for_navigation()\n"
            f'log("{name}搜索完成: {keyword}")'
        )

    def _gen_hot_search(self) -> str:
        return 'goto("https://s.weibo.com/top/summary")\nwait_for_navigation()\nwait(3)\ntext = get_text()\nlog("微博热搜加载完成")\nprint(text[:2000])'

    def _gen_extract(self) -> str:
        return """text = get_text()
log(f"提取文本长度: {len(text)}")
print(text[:2000])"""

    def _gen_paginate(self, max_pages: int) -> str:
        return f"""for page_num in range(1, {max_pages + 1}):
    log(f"正在处理第 {{page_num}} 页")
    text = get_text()
    print(f"--- 第 {{page_num}} 页 ---")
    print(text[:500])
    result = click("text=下一页", "a.next", "text=Next", "text=»")
    if not result.get("success"):
        log("没有更多页面")
        break
    wait_for_navigation()
    wait(1.0)
log("翻页完成")"""

    def _gen_fill(self) -> str:
        return """# 请根据实际页面修改选择器和值
# fill("#name", "张三")
# fill("#email", "test@example.com")
# click("#submit")
log("表单填写模板 - 请根据实际页面修改")"""

    def _gen_login(self) -> str:
        return """# 请根据实际网站修改选择器
# goto("https://example.com/login")
# fill("#username", "your_username")
# fill("#password", "your_password")
# click("#login-btn")
# wait_for_navigation()
log("登录模板 - 请根据实际网站修改")"""

    def _gen_click(self, target: str) -> str:
        return f'''result = click("{target}")
if result.get("success"):
    log("点击成功: {target}")
    wait_for_navigation()
else:
    log("点击失败: {target}")'''

    def _gen_scroll(self, direction: str) -> str:
        if direction == "down":
            return """page.evaluate("window.scrollBy(0, 500)")
wait(0.5)
log("向下滚动")"""
        else:
            return """page.evaluate("window.scrollBy(0, -500)")
wait(0.5)
log("向上滚动")"""

    def _gen_wait(self, seconds: int) -> str:
        return f'wait({seconds})\nlog("等待 {seconds} 秒")'

    # -------------------------------------------------------------------
    # 辅助方法
    # -------------------------------------------------------------------

    def _extract_keyword(self, task: str) -> str | None:
        """从任务描述中提取搜索关键词。"""
        # 匹配 "在XXX搜索/查询/查一下YYY" 模式
        patterns = [
            r"(?:在|到)(?:百度|google|bing|谷歌|必应|搜狗|360|当当|CSDN|Gitee|百科|头条|知乎|豆瓣|B站|微博|文库|淘宝|京东|拼多多|天气网)?(?:上)?(?:搜索一下|搜一下|查询一下|查找一下|搜索|查询|查找|查一下|查一查|搜一搜|找一下|找一找)[:\s]*(.+)",
            r"(?:百度|google|bing|搜狗|360|当当|CSDN|Gitee|百科|头条|知乎|豆瓣|B站|微博|文库|淘宝|京东|拼多多)?(?:搜索一下|搜一下|查询一下|查找一下|搜索|查询|查找|查一下|查一查|搜一搜|找一下|找一找)[:\s]*(.+)",
            r"(?:搜索一下|搜一下|查询一下|查找一下|搜索|查询|查找|查一下|查一查|搜一搜|找一下|找一找)[:\s]*(.+)",
            r"search\s+(?:for\s+)?(.+)",
            r"找[:\s]*(.+)",
        ]

        for pattern in patterns:
            match = re.search(pattern, task, re.IGNORECASE)
            if match:
                keyword = match.group(1).strip()
                # 清理尾部：去掉标点和"返回..."部分
                keyword = re.sub(r"[，。,.!?！？]$", "", keyword)
                keyword = re.sub(r"[，,]\s*返回.*$", "", keyword)
                keyword = re.sub(r"[，,]\s*并.*$", "", keyword)
                if keyword:
                    return keyword

        # 降级：去掉常见动词前缀
        prefixes = [
            "帮我在百度搜索",
            "帮我在百度查一下",
            "帮我在百度查一查",
            "帮我在百度搜一下",
            "在百度搜索",
            "在百度查一下",
            "在百度查一查",
            "在百度搜一下",
            "帮我搜索",
            "帮我查一下",
            "帮我搜一下",
            "帮我查找",
            "百度搜索",
            "百度查一下",
            "search for",
            "search",
            "搜索",
            "查找",
            "查一下",
            "搜一下",
            "找一下",
            "找",
            "查",
        ]
        task_lower_stripped = task.lower().strip()
        for prefix in prefixes:
            if task_lower_stripped.startswith(prefix):
                keyword = task[len(prefix) :].strip()
                keyword = re.sub(r"[，。,.!?！？]$", "", keyword)
                keyword = re.sub(r"[，,]\s*返回.*$", "", keyword)
                keyword = re.sub(r"[，,]\s*并.*$", "", keyword)
                if keyword:
                    return keyword

        return None

    def _extract_url(self, task: str) -> str | None:
        """从任务描述中提取 URL。"""
        # 匹配完整 URL
        url_pattern = r"https?://[\w\-./?=&%#+~:@!$&\'()*+,;]+"
        match = re.search(url_pattern, task)
        if match:
            url = match.group(0).rstrip(".,;:!?")
            return url

        # 匹配域名
        domain_pattern = (
            r"(?:^|\s)([\w-]+\.(com|cn|org|net|io|dev|cc))(?:\s|$|[，。,.])"
        )
        match = re.search(domain_pattern, task)
        if match:
            return f"https://{match.group(1)}"

        return None

    def _detect_search_engine(self, task: str) -> str:
        """检测用户想用哪个搜索引擎/网站。"""
        task_lower = task.lower()
        if any(kw in task_lower for kw in ["google", "谷歌"]):
            return "google"
        if any(kw in task_lower for kw in ["bing", "必应"]):
            return "bing"
        if any(kw in task_lower for kw in ["搜狗", "sogou"]):
            return "sogou"
        if any(kw in task_lower for kw in ["360", "so.com"]):
            return "so"
        if any(kw in task_lower for kw in ["当当", "dangdang"]):
            return "dangdang"
        if any(kw in task_lower for kw in ["csdn"]):
            return "csdn"
        if any(kw in task_lower for kw in ["gitee"]):
            return "gitee"
        if any(kw in task_lower for kw in ["百科", "baike"]):
            return "baike"
        if any(kw in task_lower for kw in ["头条", "toutiao"]):
            return "toutiao"
        if any(kw in task_lower for kw in ["知乎", "zhihu"]):
            return "zhihu"
        if any(kw in task_lower for kw in ["豆瓣", "douban"]):
            return "douban"
        if any(kw in task_lower for kw in ["b站", "bilibili", "哔哩"]):
            return "bilibili"
        if any(kw in task_lower for kw in ["微博", "weibo", "热搜"]):
            return "weibo"
        if any(kw in task_lower for kw in ["文库", "wenku"]):
            return "wenku"
        if any(kw in task_lower for kw in ["淘宝", "taobao"]):
            return "taobao"
        if any(kw in task_lower for kw in ["京东", "jd"]):
            return "jd"
        if any(kw in task_lower for kw in ["拼多多", "pdd"]):
            return "pdd"
        if any(kw in task_lower for kw in ["天气", "weather"]):
            return "weather"
        return "baidu"  # 默认百度

    def _extract_number(self, task: str, default: int = 5) -> int:
        """从任务描述中提取数字。"""
        match = re.search(r"(\d+)\s*(?:页|个|次|步|秒)", task)
        if match:
            return int(match.group(1))
        return default

    def _extract_click_target(self, task: str) -> str | None:
        """提取点击目标。"""
        # 匹配引号内的选择器
        match = re.search(r'["\']([^"\']+)["\']', task)
        if match:
            return match.group(1)

        # 匹配 "点击XXX" 模式
        match = re.search(r"点击[:\s]*(.+)", task)
        if match:
            target = match.group(1).strip()
            # 如果是纯文本，用 text= 选择器
            if not target.startswith(("#", ".", "/", "[")):
                return f"text={target}"
            return target

        return None

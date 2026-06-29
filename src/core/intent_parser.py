"""
LLM 意图解析器 —— 当硬编码规则无法解析任务时，用 LLM 兜底。

仅在以下情况调用：
1. ScriptGenerator.parse_intent() 返回 None（规则无匹配）
2. 技能库多个技能评分打平（歧义）

返回结构化 TaskIntent，走现有的脚本模板拼装路径。
"""

from __future__ import annotations

import json
import logging
import os

from src.core.script_generator import TaskIntent

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 可用的 action 和网站列表（与 ScriptGenerator 保持同步）
# ---------------------------------------------------------------------------

_ACTIONS = [
    "search",  # 搜索
    "navigate",  # 导航到 URL
    "screenshot",  # 截图
    "extract",  # 提取页面文本
    "fill",  # 填写表单
    "paginate",  # 翻页遍历
    "login",  # 登录
    "click",  # 点击元素
    "scroll",  # 滚动页面
    "wait",  # 等待
    "hot_search",  # 查看热搜
]

# 从 ScriptGenerator.SITE_META 同步（避免循环导入，这里硬编码一份）
_KNOWN_SITES = {
    "baidu": "百度",
    "google": "Google/谷歌",
    "bing": "Bing/必应",
    "sogou": "搜狗",
    "so": "360搜索",
    "dangdang": "当当",
    "csdn": "CSDN",
    "gitee": "Gitee",
    "baike": "百度百科",
    "toutiao": "今日头条",
    "zhihu": "知乎",
    "douban": "豆瓣",
    "bilibili": "B站/bilibili",
    "weibo": "微博",
    "wenku": "百度文库",
    "taobao": "淘宝",
    "jd": "京东",
    "pdd": "拼多多",
    "weather": "天气网",
    "amazon": "Amazon/亚马逊",
    "youtube": "YouTube/油管",
    "github": "GitHub",
    "gmail": "Gmail/谷歌邮箱",
    "outlook": "Outlook/微软邮箱",
}


def _build_system_prompt() -> str:
    """构造 system prompt，告知 LLM 可用的 action 和网站。"""
    sites_desc = "\n".join(f"  - {key}: {name}" for key, name in _KNOWN_SITES.items())
    actions_desc = ", ".join(_ACTIONS)

    return f"""你是一个自然语言意图解析器。用户会给你一句中文或英文的浏览器操作指令，你需要解析出结构化的意图。

可用的 action 类型: {actions_desc}

已知网站（engine 字段可选值）:
{sites_desc}

请返回严格的 JSON 格式，不要包含其他文字:
{{
  "action": "动作类型",
  "target": "目标值（搜索关键词、URL、点击目标等，视 action 而定）",
  "engine": "网站标识（仅 search action 需要，其他填 null）",
  "confidence": 0.95
}}

字段说明:
- action: 必填，必须是上述列表中的一个
- target: 搜索关键词 / URL / 元素选择器 / 空字符串
- engine: 仅 search 时填网站标识（如 baidu、google），其他 action 填 null
- confidence: 你对解析结果的置信度，0.0~1.0

示例:
用户: "在百度搜索 python教程" → {{"action":"search","target":"python教程","engine":"baidu","confidence":0.99}}
用户: "帮我打开 github.com" → {{"action":"navigate","target":"https://github.com","engine":null,"confidence":0.95}}
用户: "截个图" → {{"action":"screenshot","target":"","engine":null,"confidence":0.99}}
用户: "帮我去百度查一下 python 教程" → {{"action":"search","target":"python 教程","engine":"baidu","confidence":0.90}}
"""


class LLMIntentParser:
    """用 LLM 解析自然语言意图为 TaskIntent。

    仅当硬编码规则失败时调用，作为兜底方案。
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
    ) -> None:
        self._api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        self._base_url = (
            base_url or os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        ).rstrip("/")
        self._model = model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    @property
    def available(self) -> bool:
        """是否有 API Key 可用。"""
        return bool(self._api_key)

    def parse(self, task: str) -> TaskIntent | None:
        """调用 LLM 解析任务意图。

        Args:
            task: 用户的自然语言任务描述。

        Returns:
            TaskIntent 或 None（解析失败 / 置信度过低 / API 不可用）。
        """
        if not self._api_key:
            logger.warning("LLM fallback 不可用: 未设置 OPENAI_API_KEY")
            return None

        try:
            raw = self._call_llm(task)
            return self._parse_response(raw)
        except Exception as exc:
            logger.warning("LLM 意图解析失败: %s", exc)
            return None

    def _call_llm(self, task: str) -> str:
        """调用 OpenAI 兼容 API。"""
        import httpx

        url = f"{self._base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self._model,
            "temperature": 0,
            "max_tokens": 256,
            "messages": [
                {"role": "system", "content": _build_system_prompt()},
                {"role": "user", "content": task},
            ],
        }

        response = httpx.post(url, headers=headers, json=payload, timeout=15.0)
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]

    def _parse_response(self, raw: str) -> TaskIntent | None:
        """解析 LLM 返回的 JSON 为 TaskIntent。"""
        # 提取 JSON 块（LLM 可能包裹在 ```json ``` 中）
        text = raw.strip()
        if "```" in text:
            start = text.find("{")
            end = text.rfind("}") + 1
            if start == -1 or end == 0:
                return None
            text = text[start:end]

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("LLM 返回非 JSON: %s", raw[:200])
            return None

        # 校验必填字段
        action = data.get("action", "")
        if action not in _ACTIONS:
            logger.warning("LLM 返回未知 action: %s", action)
            return None

        # 置信度过滤
        confidence = data.get("confidence", 0)
        if confidence < 0.5:
            logger.info("LLM 置信度过低 (%.2f)，跳过", confidence)
            return None

        # 构造 TaskIntent
        target = data.get("target", "")
        engine = data.get("engine")
        parameters = {}
        if engine:
            parameters["engine"] = engine

        # 特殊 action 的参数补充
        if action == "paginate":
            parameters["max_pages"] = data.get("max_pages", 5)
        elif action == "scroll":
            parameters["direction"] = data.get("direction", "down")
        elif action == "wait":
            parameters["seconds"] = data.get("seconds", 3)

        return TaskIntent(action=action, target=target, parameters=parameters)


# ---------------------------------------------------------------------------
# 全局单例
# ---------------------------------------------------------------------------

_instance: LLMIntentParser | None = None


def get_llm_intent_parser() -> LLMIntentParser:
    """获取全局单例 LLMIntentParser。"""
    global _instance
    if _instance is None:
        _instance = LLMIntentParser()
    return _instance


def reset_llm_intent_parser() -> None:
    """重置全局单例（用于测试）。"""
    global _instance
    _instance = None

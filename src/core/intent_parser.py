"""
LLM 意图解析器 —— 统一封装 LLM 客户端，供技能路由与 Explore 复用。

当前职责：
- 提供 available 门禁（是否配置了 API Key）
- 暴露底层 LLMClient（_client）给 SkillRouter 精排、AgentLoop 选技能、
  Explore 规划等调用，统一走 OpenAI 兼容 API / Anthropic。

parse() 曾用于把自然语言解析为 TaskIntent 走脚本模板拼装，现已被
SkillRouter 的两阶段路由取代；方法保留但主链路不再调用。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from src.core.llm_utils import chat_json_with_retry
from src.core.script_generator import TaskIntent

if TYPE_CHECKING:
    from src.core.llm_client import LLMClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 可用的 action 和网站列表（与 ScriptGenerator 保持同步）
# ---------------------------------------------------------------------------

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

    内部委托给 LLMClient，支持 OpenAI 兼容 API 和 Anthropic。
    """

    def __init__(self, client: LLMClient | None = None) -> None:
        if client is not None:
            self._client = client
        else:
            from src.core.llm_client import get_llm_client
            self._client = get_llm_client()

    @property
    def available(self) -> bool:
        """是否有 API Key 可用。"""
        return self._client.available

    def parse(self, task: str) -> TaskIntent | None:
        """调用 LLM 解析任务意图。

        Args:
            task: 用户的自然语言任务描述。

        Returns:
            TaskIntent 或 None（解析失败 / 置信度过低 / API 不可用）。
        """
        if not self.available:
            logger.warning("LLM fallback 不可用: 未配置 API Key")
            return None

        schema = {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": _ACTIONS},
                "target": {"type": "string"},
                "engine": {"type": ["string", "null"]},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "max_pages": {"type": "integer", "minimum": 1},
                "direction": {"type": "string"},
                "seconds": {"type": "number", "minimum": 0},
            },
            "required": ["action", "target", "confidence"],
        }

        try:
            data = chat_json_with_retry(
                self._client,
                task,
                system_prompt=_build_system_prompt(),
                schema=schema,
                temperature=0,
                max_tokens=256,
            )
        except Exception as exc:
            logger.warning("LLM 意图解析失败: %s", exc)
            return None

        action = data.get("action", "")
        if action not in _ACTIONS:
            logger.warning("LLM 返回未知 action: %s", action)
            return None

        try:
            confidence = float(data.get("confidence", 0) or 0)
        except (TypeError, ValueError):
            logger.warning("LLM 返回非法 confidence: %s", data.get("confidence"))
            return None
        if confidence < 0.5:
            logger.info("LLM 置信度过低 (%.2f)，跳过", confidence)
            return None

        target = data.get("target", "")
        engine = data.get("engine")
        parameters = {}
        if engine:
            parameters["engine"] = engine

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

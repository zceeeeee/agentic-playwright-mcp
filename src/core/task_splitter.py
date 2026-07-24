"""
任务拆分器 —— 将用户的一句复合指令拆分为多个子任务组。

拆分策略（三级）：
0. 分号拆分：按 `;` 拆分为"连续任务"（同一标签页顺序执行）
1. 规则拆分：按中文句号 `。` / 英文句号 `.` 拆分（零成本）
2. 连接词拆分：处理 "然后"、"接着"、"并且" 等连接词
3. LLM 拆分：兜底（可选）

两种任务模式：
- 独立任务（`。`/连接词分隔）→ 每个任务开新标签页
- 连续任务（`;` 分隔）→ 同一标签页下快速顺序执行
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class TaskGroup:
    """一组子任务。

    Attributes:
        tasks: 该组内的子任务列表。
        sequential: True 表示同一标签页顺序执行（; 分隔），
                    False 表示每个任务应开独立标签页。
    """

    tasks: list[str]
    sequential: bool = False


class TaskSplitter:
    """将用户输入拆分为多个 TaskGroup。"""

    # 连接词模式（中文 + 英文）
    _CONNECTOR_PATTERN = re.compile(
        r"(?:然后|接着|随后|再|接下来|之后|并且|同时|另外|"
        r"and then|then|after that|next|also|meanwhile)",
        re.IGNORECASE,
    )

    _MODIFIER_TASK_PATTERN = re.compile(
        r"^\s*(?:配图|加图|加图片|生成图片|插入图片|AI\s*配图|ai\s*picture|add[-_ ]?picture)\s*$",
        re.IGNORECASE,
    )

    def __init__(self, llm_caller: Any = None) -> None:
        """
        Args:
            llm_caller: 可选的 LLM 调用器，需提供 .call(prompt) -> str 方法。
                        为 None 时禁用 LLM 拆分，仅用规则。
        """
        self._llm_caller = llm_caller

    def split(self, task: str) -> List[TaskGroup]:
        """拆分任务，返回 TaskGroup 列表。

        拆分语义：
        - 句号（。/ .）是顶级分隔符 → 独立任务组（每个开新标签页）
        - 分号（; / ；）是次级分隔符 → 连续任务组（同标签页顺序执行）
        - 连接词（然后、接着 等）等同于句号 → 独立任务组

        示例：
        - "打开百度。搜索Python" → 2个独立组
        - "打开百度;输入Python;点搜索" → 1个连续组(3任务)
        - "打开百度。搜索Python；点第一个结果。打开GitHub" → 3组(独立+连续+独立)

        Args:
            task: 用户的原始输入。

        Returns:
            TaskGroup 列表。
        """
        task = task.strip()
        if not task:
            return [TaskGroup(tasks=[task])]

        # L1: 按句号拆分为顶级段（每段是独立任务组）
        top_segments = self._rule_split(task)

        # 如果句号只拆出1个，尝试连接词拆分
        if len(top_segments) <= 1:
            connector_tasks = self._connector_split(task)
            if len(connector_tasks) > 1:
                top_segments = connector_tasks

        # LLM 兜底
        if len(top_segments) <= 1 and self._llm_caller:
            llm_tasks = self._llm_split(task)
            if llm_tasks and len(llm_tasks) > 1:
                top_segments = self._merge_modifier_tasks(llm_tasks)

        # 无法拆分 → 单任务（但先检查是否有分号）
        if len(top_segments) <= 1:
            # 检查是否纯分号分隔（如 "a;b;c"）
            sub_tasks = self._semicolon_split(task)
            sub_tasks = [t.strip() for t in sub_tasks if t.strip()]
            sub_tasks = self._merge_modifier_tasks(sub_tasks)
            if len(sub_tasks) > 1:
                return [TaskGroup(tasks=sub_tasks, sequential=True)]
            return [TaskGroup(tasks=[task])]

        # 对每个顶级段，检查内部是否有分号 → 拆为连续子任务
        groups: List[TaskGroup] = []
        for segment in top_segments:
            segment = segment.strip()
            if not segment:
                continue

            # 按分号拆分
            sub_tasks = self._semicolon_split(segment)
            sub_tasks = [t.strip() for t in sub_tasks if t.strip()]
            sub_tasks = self._merge_modifier_tasks(sub_tasks)

            if not sub_tasks:
                sub_tasks = [segment]

            if len(sub_tasks) > 1:
                # 有分号 → 连续任务组
                groups.append(TaskGroup(tasks=sub_tasks, sequential=True))
            else:
                # 无分号 → 独立任务组
                groups.append(TaskGroup(tasks=sub_tasks, sequential=False))

        logger.info(
            "Task split: %d groups, tasks=%s",
            len(groups),
            [g.tasks for g in groups],
        )
        return groups

    @classmethod
    def _is_modifier_task(cls, task: str) -> bool:
        return bool(cls._MODIFIER_TASK_PATTERN.fullmatch(task or ""))

    @classmethod
    def _merge_modifier_tasks(cls, tasks: List[str]) -> List[str]:
        """Merge short modifiers like '配图' back into the previous task."""
        merged: List[str] = []
        for task in tasks:
            text = task.strip()
            if not text:
                continue
            if cls._is_modifier_task(text) and merged:
                merged[-1] = f"{merged[-1]} {text}"
                continue
            merged.append(text)
        return merged

    def split_flat(self, task: str) -> List[str]:
        """兼容旧接口：返回扁平的子任务列表（忽略分组信息）。"""
        groups = self.split(task)
        return [t for g in groups for t in g.tasks]

    # -------------------------------------------------------------------
    # L0: 分号拆分
    # -------------------------------------------------------------------

    def _semicolon_split(self, task: str) -> List[str]:
        """按中英文分号拆分。"""
        # 先保护引号内的分号
        protected = self._protect_quoted_semicolon(task)
        parts = re.split(r"[;；]", protected)
        return [self._restore_semicolon(p) for p in parts]

    def _protect_quoted_semicolon(self, text: str) -> str:
        """将引号内的分号替换为占位符。"""
        result = text
        quote_pairs = [
            ("“", "”"),  # ""
            ("‘", "’"),  # ''
            ("「", "」"),  # 「」
            ('"', '"'),
            ("'", "'"),
        ]
        for open_q, close_q in quote_pairs:
            pattern = re.escape(open_q) + r"(.*?)" + re.escape(close_q)

            def protect_inner(
                match: re.Match, _o=open_q, _c=close_q
            ) -> str:
                inner = match.group(1).replace(";", "«SEMI»").replace(
                    "；", "«SEMIC»"
                )
                return _o + inner + _c

            result = re.sub(pattern, protect_inner, result, flags=re.DOTALL)
        return result

    @staticmethod
    def _restore_semicolon(text: str) -> str:
        return text.replace("«SEMI»", ";").replace(
            "«SEMIC»", "；"
        )

    # -------------------------------------------------------------------
    # L1: 规则拆分（按句号）
    # -------------------------------------------------------------------

    def _rule_split(self, task: str) -> List[str]:
        """按中文句号 `。` 和英文句号 `.` 拆分，处理边界情况。"""
        # 先保护 URL 中的点号
        protected = self._protect_urls(task)
        # 保护本地文件路径中的点号，例如 D:\tmp\test.pdf / D:tmptest.pdf
        protected = self._protect_file_paths(protected)
        # 保护引号内的句号
        protected = self._protect_quoted(protected)

        # 按句号拆分
        parts = re.split(r"[。.]", protected)

        # 还原被保护的内容
        restored = [self._restore(p) for p in parts]

        # 清理：去空串、去纯标点
        cleaned = []
        for part in restored:
            part = part.strip()
            part = self._strip_trailing_punctuation(part)
            if part and not self._is_pure_punctuation(part):
                cleaned.append(part)

        return cleaned

    def _protect_urls(self, text: str) -> str:
        """将 URL 中的点号替换为占位符，避免被拆分。"""

        def replace_url_dot(match: re.Match) -> str:
            return match.group(0).replace(".", "«DOT»")

        return re.sub(
            r"https?://[^\s<>\"'“”‘’「」]+",
            replace_url_dot,
            text,
        )

    def _protect_file_paths(self, text: str) -> str:
        """Protect local file paths so extensions like .pdf do not split tasks."""

        def replace_path_dot(match: re.Match) -> str:
            return match.group(0).replace(".", "«DOT»")

        return re.sub(
            r"(?<![A-Za-z0-9_])[A-Za-z]:(?:[\\/])?"
            r"[^<>\"'“”‘’「」,，;；。\r\n]+?\."
            r"(?:pdf|docx?|xlsx?|pptx?|txt|md|jpg|jpeg|png|webp|gif|mp4|mov|avi|mkv)",
            replace_path_dot,
            text,
            flags=re.IGNORECASE,
        )

    def _protect_quoted(self, text: str) -> str:
        """将引号内的句号替换为占位符。"""
        # 用占位符逐步保护引号内容
        result = text

        # 匹配成对引号（贪婪匹配中间内容）
        quote_pairs = [
            ("“", "”"),  # ""
            ("‘", "’"),  # ''
            ("「", "」"),  # 「」
            ('"', '"'),
            ("'", "'"),
        ]

        for open_q, close_q in quote_pairs:
            pattern = re.escape(open_q) + r"(.*?)" + re.escape(close_q)

            def protect_inner(
                match: re.Match, _o=open_q, _c=close_q
            ) -> str:
                inner = match.group(1).replace(".", "«DOT»").replace(
                    "。", "«CDOT»"
                )
                return _o + inner + _c

            result = re.sub(pattern, protect_inner, result, flags=re.DOTALL)

        return result

    @staticmethod
    def _restore(text: str) -> str:
        """还原被保护的点号。"""
        return text.replace("«DOT»", ".").replace(
            "«CDOT»", "。"
        )

    @staticmethod
    def _strip_trailing_punctuation(text: str) -> str:
        """去除末尾的标点符号（但保留引号内的内容）。"""
        return re.sub(r"[，,；;、：:！!？?·\s]+$", "", text)

    @staticmethod
    def _is_pure_punctuation(text: str) -> bool:
        """判断文本是否全是标点或空白。"""
        return bool(
            re.fullmatch(
                r"[\s，,。.；;、：:！!？?·\-—…·''\"\"''「」\(\)（）\[\]【】]+",
                text,
            )
        )

    # -------------------------------------------------------------------
    # L2: 连接词拆分
    # -------------------------------------------------------------------

    def _connector_split(self, task: str) -> List[str]:
        """按连接词（然后、接着、并且 等）拆分。"""
        protected, spans = self._protect_connector_spans(task)
        parts = self._CONNECTOR_PATTERN.split(protected)
        cleaned = []
        for part in parts:
            for placeholder, original in spans.items():
                part = part.replace(placeholder, original)
            part = part.strip()
            part = self._strip_trailing_punctuation(part)
            if part and not self._is_pure_punctuation(part):
                cleaned.append(part)
        return cleaned

    @staticmethod
    def _protect_connector_spans(text: str) -> tuple[str, dict[str, str]]:
        """Hide URLs, paths, and quoted content from connector matching."""
        spans: dict[str, str] = {}

        def protect(match: re.Match) -> str:
            placeholder = f"\ue000{len(spans)}\ue001"
            spans[placeholder] = match.group(0)
            return placeholder

        protected = text
        patterns = (
            r'"[^"]*"|“[^”]*”|\'[^\']*\'|‘[^’]*’|「[^」]*」',
            r"https?://[^\s<>\"'“”‘’「」]+",
            r"(?<![A-Za-z0-9_])[A-Za-z]:(?:[\\/])?[^\s,，;；。\r\n]+",
        )
        for pattern in patterns:
            protected = re.sub(pattern, protect, protected)
        return protected, spans

    # -------------------------------------------------------------------
    # L3: LLM 拆分
    # -------------------------------------------------------------------

    def _llm_split(self, task: str) -> Optional[List[str]]:
        """用 LLM 判断是否包含多个意图，返回拆分后的子任务列表。"""
        if not self._llm_caller:
            return None

        prompt = (
            f"用户输入了一句浏览器操作指令。请判断这句指令是否包含多个独立的操作步骤。\n\n"
            f"用户指令: {task}\n\n"
            f"规则:\n"
            f"1. 如果只有一个操作，返回 [原始指令]\n"
            f"2. 如果有多个操作，按顺序拆分为多个子任务\n"
            f"3. 每个子任务应该是完整的、可独立执行的指令\n"
            f"4. 去掉连接词（然后、接着、并且等），只保留操作本身\n"
            f"5. 重要：如果指令是「在XX搜索Y，分析/总结/导出」这种模式，"
            f"这是一个完整的复合任务，不应拆分。搜索+分析+导出是一个技能的完整流程。\n"
            f"6. 重要：只有当两个操作之间没有数据依赖关系时才拆分。"
            f"比如「打开百度。打开GitHub」可以拆分，但「搜索X，分析结果」不应拆分。\n\n"
            f'返回 JSON 格式: {{"tasks": ["子任务1", "子任务2", ...]}}'
        )

        schema = {
            "type": "object",
            "properties": {
                "tasks": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                },
            },
            "required": ["tasks"],
        }

        try:
            from src.core.llm_utils import chat_json_with_retry

            data = chat_json_with_retry(
                self._llm_caller._client
                if hasattr(self._llm_caller, "_client")
                else self._llm_caller,
                prompt,
                system_prompt="你是一个任务拆分器。将用户的复合指令拆分为独立的子任务。",
                schema=schema,
            )
            tasks = data.get("tasks", [])
            if isinstance(tasks, list) and len(tasks) >= 1:
                return [t.strip() for t in tasks if isinstance(t, str) and t.strip()]
        except Exception as exc:
            logger.warning("LLM task split failed: %s", exc)

        return None


# ---------------------------------------------------------------------------
# 全局单例
# ---------------------------------------------------------------------------

_instance: TaskSplitter | None = None


def get_task_splitter(llm_caller: Any = None) -> TaskSplitter:
    """获取全局单例 TaskSplitter。"""
    global _instance
    if _instance is None:
        _instance = TaskSplitter(llm_caller=llm_caller)
    return _instance


def reset_task_splitter() -> None:
    """重置全局单例（用于测试）。"""
    global _instance
    _instance = None

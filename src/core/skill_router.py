"""
技能路由器 —— 召回+精排架构。

Stage 1: 候选召回（零延迟，零成本）
  用关键词/正则从技能库中召回 top-K 候选（不硬排除任何技能）。

Stage 2: LLM 精排（候选在模糊区时调用）
  将候选列表 + 用户指令发给 LLM，让它选出最佳 skill 或判定需要 explore。

Stage 3: 参数化脚本构建
  根据 skill 的 params 声明从任务中提取参数，生成 run() 调用。
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------


@dataclass
class SkillRouterInfo:
    """技能路由信息 —— 扩展元数据，用于路由和脚本生成。"""

    id: str
    name: str
    description: str = ""
    triggers: List[str] = field(default_factory=list)
    trigger_patterns: List[str] = field(default_factory=list)
    platform: str = ""
    action: str = ""
    examples: List[str] = field(default_factory=list)
    params: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    confirm_before_run: bool = False
    source_file: str = ""
    source_entry: str = "run"


@dataclass
class SkillDecision:
    """路由决策结果。"""

    skill: Optional[SkillRouterInfo] = None
    confidence: float = 0.0
    reason: str = ""
    source: str = "none"  # "keyword" | "llm" | "none"
    script: str = ""


# ---------------------------------------------------------------------------
# 技能路由器
# ---------------------------------------------------------------------------


class SkillRouter:
    """两阶段技能路由器。

    用法::

        router = SkillRouter(library_dir="src/skill_library")
        decision = router.route("在百度搜索 Python 教程")

        if decision.skill:
            print(f"命中: {decision.skill.name} (置信度: {decision.confidence})")
            print(f"脚本: {decision.script}")
    """

    def __init__(
        self,
        library_dir: str | Path | None = None,
        llm_caller: Any = None,
    ) -> None:
        """初始化路由器。

        Args:
            library_dir: 技能库目录（包含 skills.yaml 和源码）。
            llm_caller: LLM 调用器，需提供 .call_json(prompt, schema=...) -> dict 方法。
                        若为 None，禁用 LLM 精排。
        """
        self._library_dir = Path(library_dir) if library_dir else None
        self._llm_caller = llm_caller
        self._skills: Dict[str, SkillRouterInfo] = {}
        self._loaded = False

    # -------------------------------------------------------------------
    # 加载
    # -------------------------------------------------------------------

    def load(self) -> None:
        """从 skills.yaml 加载技能路由信息。"""
        if self._loaded:
            return

        if not self._library_dir:
            return

        yaml_path = self._library_dir / "skills.yaml"
        if not yaml_path.exists():
            logger.warning("skills.yaml not found at %s", yaml_path)
            return

        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        # 构建 sources 映射
        sources_map: Dict[str, Dict[str, str]] = {}
        for src in data.get("sources", []):
            sources_map[src["id"]] = {
                "file": src.get("file", ""),
                "entry": src.get("entry", "run"),
            }

        # 加载技能
        for item in data.get("skills", []):
            skill_id = item["id"]
            source = sources_map.get(skill_id, {})

            info = SkillRouterInfo(
                id=skill_id,
                name=item.get("name", ""),
                description=item.get("description", ""),
                triggers=item.get("triggers", []),
                trigger_patterns=item.get("trigger_patterns", []),
                platform=item.get("platform", ""),
                action=item.get("action", ""),
                examples=item.get("examples", []),
                params=item.get("params", {}),
                confirm_before_run=item.get("confirm_before_run", False),
                source_file=source.get("file", ""),
                source_entry=source.get("entry", "run"),
            )
            self._skills[skill_id] = info

        self._loaded = True
        logger.info("SkillRouter loaded %d skills", len(self._skills))

    # -------------------------------------------------------------------
    # 路由
    # -------------------------------------------------------------------

    def route(
        self,
        task: str,
        page_context: Optional[Dict[str, str]] = None,
    ) -> SkillDecision:
        """两阶段路由：关键词快筛 → LLM 精排。

        Args:
            task: 用户的自然语言任务描述。
            page_context: 当前页面上下文 {"url": ..., "title": ...}。

        Returns:
            SkillDecision 包含匹配的技能、置信度和生成的脚本。
        """
        if not self._loaded:
            self.load()

        if not self._skills:
            return SkillDecision(source="none", reason="无可用技能")

        # ── Stage 1: 候选召回 ──
        candidates = self._recall_candidates(task, limit=5)

        if not candidates:
            # 无召回候选 → LLM 从全量技能中选（或 explore）
            if self._llm_caller:
                llm_result = self._llm_rank(
                    task,
                    self._all_skill_candidates(limit=40),
                    page_context,
                    force_pick=True,
                )
                if llm_result and llm_result.source == "llm_explore":
                    return llm_result
                if llm_result and llm_result.skill and llm_result.confidence >= 0.7:
                    script = self.build_script(llm_result.skill, task)
                    return SkillDecision(
                        skill=llm_result.skill,
                        confidence=llm_result.confidence,
                        reason=f"无召回候选，LLM 选择: {llm_result.reason}",
                        source="llm",
                        script=script,
                    )
            return SkillDecision(source="none", reason="无召回候选")

        if self._is_gmail_send_intent(task.lower()):
            gmail_send = next(
                (skill for skill, _ in candidates if skill.id == "domain/gmail_send"),
                None,
            )
            if gmail_send:
                script = self.build_script(gmail_send, task)
                return SkillDecision(
                    skill=gmail_send,
                    confidence=0.95,
                    reason=f"明确 Gmail 发送邮件意图: {gmail_send.name}",
                    source="keyword",
                    script=script,
                )

        top_skill, top_score = candidates[0]

        if top_skill.platform.lower() == "wps" and top_score >= 0.9:
            script = self.build_script(top_skill, task)
            return SkillDecision(
                skill=top_skill,
                confidence=min(top_score, 1.0),
                reason=f"WPS 高置信命中: {top_skill.name}",
                source="keyword",
                script=script,
            )

        # ── Stage 2: 双重阈值判断 ──
        # > 0.8 → 高置信直接通过（跳过 LLM）
        # 0.6 ~ 0.8 → 模糊区，送 LLM 精排
        # < 0.6 → 低置信，丢弃该候选
        if top_score >= 0.8:
            # 唯一高置信 或 第一远超第二（差距 > 0.1）→ 直接命中
            if len(candidates) == 1 or (top_score - candidates[1][1]) > 0.1:
                script = self.build_script(top_skill, task)
                return SkillDecision(
                    skill=top_skill,
                    confidence=min(top_score, 1.0),
                    reason=f"召回高置信命中: {top_skill.name}",
                    source="keyword",
                    script=script,
                )

        # ── Stage 3: LLM 精排（含 explore 选项）──
        # 候选 >= 2 或唯一候选在模糊区 (0.6~0.8) → 送 LLM
        # 唯一候选 < 0.6 → 丢弃，不浪费 LLM 调用
        need_llm = False
        if len(candidates) >= 2:
            need_llm = True
        elif top_score >= 0.6:
            need_llm = True

        if need_llm and self._llm_caller:
            # 过滤掉 < 0.4 的噪声候选
            filtered = [(s, sc) for s, sc in candidates if sc >= 0.4]
            if not filtered:
                filtered = candidates[:1]
            llm_result = self._llm_rank(task, filtered, page_context)
            if llm_result:
                if llm_result.source == "llm_explore":
                    return llm_result
                if llm_result.skill and llm_result.confidence >= 0.6:
                    script = self.build_script(llm_result.skill, task)
                    return SkillDecision(
                        skill=llm_result.skill,
                        confidence=llm_result.confidence,
                        reason=llm_result.reason,
                        source="llm",
                        script=script,
                    )

        # 无匹配 → 交给上层处理（通常进入 Explore）
        return SkillDecision(source="none", reason="召回+精排均未命中")

    # -------------------------------------------------------------------
    # Stage 1: 关键词快筛
    # -------------------------------------------------------------------

    def _recall_candidates(
        self, query: str, limit: int = 5
    ) -> List[tuple[SkillRouterInfo, float]]:
        """候选召回，返回 (skill, score) 列表，按分数降序。

        不硬排除任何技能——trigger_patterns 未命中时仍通过触发词/描述等信号评分，
        确保有歧义的候选能进入 LLM 精排而不是被静默丢弃。
        """
        scored: List[tuple[SkillRouterInfo, float]] = []
        query_lower = query.lower()

        for skill in self._skills.values():
            score = self._match_score(skill, query_lower)
            if score > 0:
                scored.append((skill, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:limit]

    def _all_skill_candidates(self, limit: int = 40) -> List[tuple[SkillRouterInfo, float]]:
        """给 LLM 使用的全量候选集。"""
        return [
            (skill, 0.0)
            for skill in self._skills.values()
            if skill.source_file
        ][:limit]

    def _build_zhihu_article_param_script(
        self,
        source_code: str,
        skill: SkillRouterInfo,
        extracted: Dict[str, str],
    ) -> str:
        """Build Zhihu article prompts with optional AI generation."""
        pre_auth = self._build_pre_auth_script(skill, wait_for_manual=False)
        auth_wait = self._build_pre_auth_script(skill, wait_for_manual=True)
        title_value = json.dumps(extracted.get("title", "-1"), ensure_ascii=False)
        keyword_value = json.dumps(extracted.get("keyword", "-1"), ensure_ascii=False)
        add_picture_value = json.dumps(extracted.get("add-picture", "no"), ensure_ascii=False)
        title_ai_generate = bool(skill.params.get("title", {}).get("ai_generate", False))
        keyword_ai_generate = bool(
            skill.params.get("keyword", {}).get("ai_generate", False)
        )
        helper = (
            "\n\n# Zhihu article AI/manual parameter confirmation\n"
            "def __agentic_is_missing_param(value):\n"
            "    return value is None or str(value).strip() in {'', '-1', 'None', 'none', 'null'}\n\n"
            "def __agentic_confirm_required_param(name, value, question, required):\n"
            "    attempts = 0\n"
            "    while required:\n"
            "        attempts += 1\n"
            "        answer = panel_prompt(question)\n"
            "        answer = str(answer or '').strip()\n"
            "        if answer:\n"
            "            return answer\n"
            "        if not __agentic_is_missing_param(value):\n"
            "            return value\n"
            "        if attempts >= 3:\n"
            "            raise RuntimeError(f'缺少必填参数：{name}')\n"
            "        question = f'参数「{name}」是必填项，请输入后再继续：'\n"
            "    return value\n\n"
            "def __agentic_required_input(question, name):\n"
            "    attempts = 0\n"
            "    while True:\n"
            "        attempts += 1\n"
            "        answer = panel_prompt(question)\n"
            "        answer = str(answer or '').strip()\n"
            "        if answer:\n"
            "            return answer\n"
            "        if attempts >= 3:\n"
            "            raise RuntimeError(f'缺少必填参数：{name}')\n"
            "        question = f'{name}不能为空，请重新输入：'\n\n"
            "def __agentic_is_ai_mode(answer):\n"
            "    text = str(answer or '').strip().lower()\n"
            "    return text in {'ai', 'ai生成', '生成', '自动生成', 'yes', 'y', '1', 'true', '是'}\n\n"
            "def __agentic_generate_text(prompt, name):\n"
            "    try:\n"
            "        text = llm_generate_text(prompt)\n"
            "    except Exception as exc:\n"
            "        raise RuntimeError(f'AI生成{name}失败：{exc}')\n"
            "    text = str(text or '').strip()\n"
            "    if not text:\n"
            "        raise RuntimeError(f'AI生成{name}失败：返回为空')\n"
            "    return text\n\n"
            "def __agentic_prepare_zhihu_content(current, allow_ai):\n"
            "    if allow_ai:\n"
            "        mode = panel_prompt('知乎文章内容请选择输入方式：[AI生成] [手动输入/确认]')\n"
            "    else:\n"
            "        mode = '手动输入/确认'\n"
            "    if allow_ai and __agentic_is_ai_mode(mode):\n"
            "        topic = __agentic_required_input('请输入文章主题：', '文章主题')\n"
            "        count = __agentic_required_input('请输入正文字数（例如 800）：', '正文字数')\n"
            "        prompt = (\n"
            "            f'请围绕主题“{topic}”生成一篇适合发布在知乎的中文文章正文，'\n"
            "            f'字数约{count}字。要求结构清晰、表达自然、有观点和细节。'\n"
            "            '只输出正文，不要输出标题、说明、Markdown代码块。'\n"
            "        )\n"
            "        try:\n"
            "            return __agentic_generate_text(prompt, '文章内容')\n"
            "        except Exception as exc:\n"
            "            fallback = panel_prompt(f'AI生成文章内容失败：{exc}。请手动输入文章内容后继续：')\n"
            "            fallback = str(fallback or '').strip()\n"
            "            if fallback:\n"
            "                return fallback\n"
            "            return __agentic_required_input('请手动输入文章内容：', '文章内容')\n"
            "    return __agentic_confirm_required_param(\n"
            "        'keyword',\n"
            "        current,\n"
            "        f'请确认技能「知乎发布」的参数「文章内容」。当前值：{current}。如需修改请输入新值，直接回车则沿用当前值：',\n"
            "        True,\n"
            "    )\n\n"
            "def __agentic_prepare_zhihu_title(current, content, allow_ai):\n"
            "    if allow_ai:\n"
            "        mode = panel_prompt('知乎文章标题请选择输入方式：[AI生成] [手动输入/确认]')\n"
            "    else:\n"
            "        mode = '手动输入/确认'\n"
            "    if allow_ai and __agentic_is_ai_mode(mode):\n"
            "        count = __agentic_required_input('请输入标题字数限制（例如 20）：', '标题字数')\n"
            "        prompt = (\n"
            "            f'请根据下面文章正文生成一个适合知乎发布的中文标题，标题不超过{count}字。'\n"
            "            '要求准确、有吸引力，不要夸张营销。只输出标题。\\n\\n正文：\\n'\n"
            "            f'{content}'\n"
            "        )\n"
            "        try:\n"
            "            return __agentic_generate_text(prompt, '文章标题')\n"
            "        except Exception as exc:\n"
            "            fallback = panel_prompt(f'AI生成文章标题失败：{exc}。请手动输入文章标题后继续：')\n"
            "            fallback = str(fallback or '').strip()\n"
            "            if fallback:\n"
            "                return fallback\n"
            "            return __agentic_required_input('请手动输入文章标题：', '文章标题')\n"
            "    return __agentic_confirm_required_param(\n"
            "        'title',\n"
            "        current,\n"
            "        f'请确认技能「知乎发布」的参数「文章标题」。当前值：{current}。如需修改请输入新值，直接回车则沿用当前值：',\n"
            "        True,\n"
            "    )\n"
            "\n"
            "def __agentic_prepare_zhihu_add_picture(current):\n"
            "    text = str(current or '').strip().lower()\n"
            "    true_values = {'1', 'true', 'yes', 'y', 'on', 'ai', 'add-picture', 'add_picture', '配图', '加图', '加图片', '生成图片', '插入图片'}\n"
            "    false_values = {'', '-1', '0', 'false', 'no', 'n', 'off', 'none', 'null', '不配图', '不要配图'}\n"
            "    default = 'yes' if text in true_values else 'no'\n"
            "    answer = panel_prompt(f'是否为知乎文章添加 AI 配图？当前默认：{default}。[yes] [no]')\n"
            "    answer = str(answer or '').strip().lower()\n"
            "    if not answer:\n"
            "        answer = default\n"
            "    if answer in true_values:\n"
            "        return True\n"
            "    if answer in false_values:\n"
            "        return False\n"
            "    return False\n"
        )
        return (
            f"{source_code}"
            f"{helper}"
            f"{pre_auth}"
            f"__param_keyword = __agentic_prepare_zhihu_content({keyword_value}, {keyword_ai_generate!r})\n"
            f"__param_title = __agentic_prepare_zhihu_title({title_value}, __param_keyword, {title_ai_generate!r})\n\n"
            f"__param_add_picture = __agentic_prepare_zhihu_add_picture({add_picture_value})\n\n"
            f"{auth_wait}"
            f"# 自动调用\nrun(title=__param_title, keyword=__param_keyword, add_picture=__param_add_picture)"
        )

    def _build_wps_writer_param_script(
        self,
        source_code: str,
        skill: SkillRouterInfo,
        extracted: Dict[str, str],
    ) -> str:
        """Build WPS Writer prompts before opening the desktop app."""
        title_value = json.dumps(extracted.get("title", "-1"), ensure_ascii=False)
        body_value = json.dumps(extracted.get("body", "-1"), ensure_ascii=False)
        markdown_path_value = json.dumps(
            extracted.get("markdown_path", "-1"), ensure_ascii=False
        )
        body_format_value = json.dumps(
            extracted.get("body_format", "-1"), ensure_ascii=False
        )
        output_dir_value = json.dumps(extracted.get("output_dir", "-1"), ensure_ascii=False)
        docx_path_value = json.dumps(extracted.get("docx_path", "-1"), ensure_ascii=False)
        pdf_path_value = json.dumps(extracted.get("pdf_path", "-1"), ensure_ascii=False)
        output_format_value = json.dumps(
            extracted.get("output_format", "-1"), ensure_ascii=False
        )
        file_name_value = json.dumps(extracted.get("file_name", "-1"), ensure_ascii=False)
        font_name_value = json.dumps(extracted.get("font_name", "-1"), ensure_ascii=False)
        font_size_value = json.dumps(extracted.get("font_size", "-1"), ensure_ascii=False)
        title_font_name_value = json.dumps(
            extracted.get("title_font_name", "-1"), ensure_ascii=False
        )
        title_font_size_value = json.dumps(
            extracted.get("title_font_size", "-1"), ensure_ascii=False
        )
        body_font_name_value = json.dumps(
            extracted.get("body_font_name", "-1"), ensure_ascii=False
        )
        body_font_size_value = json.dumps(
            extracted.get("body_font_size", "-1"), ensure_ascii=False
        )
        title_font_name_default = json.dumps(
            skill.params.get("title_font_name", {}).get("default", "方正小标宋简体"),
            ensure_ascii=False,
        )
        title_font_size_default = json.dumps(
            skill.params.get("title_font_size", {}).get("default", "22"),
            ensure_ascii=False,
        )
        body_font_name_default = json.dumps(
            skill.params.get("body_font_name", {}).get("default", "仿宋_GB2312"),
            ensure_ascii=False,
        )
        body_font_size_default = json.dumps(
            skill.params.get("body_font_size", {}).get("default", "16"),
            ensure_ascii=False,
        )
        font_color_value = json.dumps(extracted.get("font_color", "-1"), ensure_ascii=False)
        italic_value = json.dumps(extracted.get("italic", "-1"), ensure_ascii=False)
        insert_image_value = json.dumps(
            extracted.get("insert_image", "-1"), ensure_ascii=False
        )
        image_path_value = json.dumps(extracted.get("image_path", "-1"), ensure_ascii=False)
        default_output_dir_value = json.dumps(
            str(Path(__file__).resolve().parents[2] / "out"), ensure_ascii=False
        )
        title_ai_generate = bool(skill.params.get("title", {}).get("ai_generate", False))
        body_ai_generate = bool(skill.params.get("body", {}).get("ai_generate", False))

        helper = (
            "\n\n# WPS Writer AI/manual parameter confirmation\n"
            "def __agentic_is_missing_param(value):\n"
            "    return value is None or str(value).strip() in {'', '-1', 'None', 'none', 'null'}\n\n"
            "def __agentic_is_ai_mode(answer):\n"
            "    text = str(answer or '').strip().lower()\n"
            "    return text in {'ai', 'ai生成', '生成', '自动生成', 'yes', 'y', '1', 'true', '是'}\n\n"
            "def __agentic_wps_requests_table(value):\n"
            "    text = str(value or '')\n"
            "    markers = ('表格', '数据表', '统计表', '对比表', '对照表', '一览表', '清单')\n"
            "    for marker in markers:\n"
            "        if marker in text:\n"
            "            return True\n"
            "    return False\n\n"
            "def __agentic_wps_requests_color(value):\n"
            "    text = str(value or '')\n"
            "    markers = ('不同颜色', '多种颜色', '彩色文字', '彩色字体', '颜色的字')\n"
            "    for marker in markers:\n"
            "        if marker in text:\n"
            "            return True\n"
            "    return False\n\n"
            "def __agentic_required_input(question, name):\n"
            "    attempts = 0\n"
            "    while True:\n"
            "        attempts += 1\n"
            "        answer = panel_prompt(question)\n"
            "        answer = str(answer or '').strip()\n"
            "        if answer:\n"
            "            return answer\n"
            "        if attempts >= 3:\n"
            "            raise RuntimeError(f'缺少必填参数：{name}')\n"
            "        question = f'{name}不能为空，请重新输入：'\n\n"
            "def __agentic_wps_topic_input(current):\n"
            "    current_value = None if __agentic_is_missing_param(current) else str(current)\n"
            "    panel_set_fields([\n"
            "        {\n"
            "            'name': 'wps_topic',\n"
            "            'label': 'WPS 文章主题或内容要求',\n"
            "            'type': 'textarea',\n"
            "            'required': True,\n"
            "            'default_value': current_value,\n"
            "        },\n"
            "        {\n"
            "            'name': 'wps_content_options',\n"
            "            'label': '可选的格式与内容要求',\n"
            "            'type': 'checkbox_group',\n"
            "            'required': False,\n"
            "            'options': [\n"
            "                {'label': '部分字体加粗', 'value': '部分字体加粗'},\n"
            "                {'label': '部分字体下划线', 'value': '部分字体下划线'},\n"
            "                {'label': '应用不同颜色的字', 'value': '应用不同颜色的字'},\n"
            "                {'label': '多级标题', 'value': '使用多级标题'},\n"
            "                {'label': '插入表格', 'value': '需要插入表格'},\n"
            "                {'label': '部分字体斜体', 'value': '部分字体斜体'},\n"
            "            ],\n"
            "        },\n"
            "    ])\n"
            "    try:\n"
            "        answer = panel_prompt(\n"
            "            '请输入 WPS 文章主题或内容要求，并按需勾选附加要求：'\n"
            "        )\n"
            "    finally:\n"
            "        panel_set_fields([])\n"
            "    answer = str(answer or '').strip()\n"
            "    if answer:\n"
            "        return answer\n"
            "    if current_value:\n"
            "        return current_value\n"
            "    return __agentic_required_input('请输入 WPS 文章主题或内容要求：', '文章主题')\n\n"
            "def __agentic_confirm_required(name, current, label):\n"
            "    attempts = 0\n"
            "    while True:\n"
            "        attempts += 1\n"
            "        answer = panel_prompt(\n"
            "            f'请确认 WPS 的「{label}」。当前值：{current}。如需修改请输入新值，直接回车则沿用当前值：'\n"
            "        )\n"
            "        answer = str(answer or '').strip()\n"
            "        if answer:\n"
            "            return answer\n"
            "        if not __agentic_is_missing_param(current):\n"
            "            return current\n"
            "        if attempts >= 3:\n"
            "            raise RuntimeError(f'缺少必填参数：{name}')\n"
            "        current = '-1'\n\n"
            "def __agentic_optional_input(label, current, default, default_label=''):\n"
            "    shown = current if not __agentic_is_missing_param(current) else default\n"
            "    panel_set_fields([{\n"
            "        'name': label,\n"
            "        'label': label,\n"
            "        'required': False,\n"
            "        'default_value': default,\n"
            "        'default_label': default_label,\n"
            "    }])\n"
            "    try:\n"
            "        answer = panel_prompt(\n"
            "            f'请输入 WPS 的「{label}」。已识别值：{shown}。也可以点击“使用默认值 {default}”。'\n"
            "        )\n"
            "    finally:\n"
            "        panel_set_fields([])\n"
            "    answer = str(answer or '').strip()\n"
            "    if answer:\n"
            "        return answer\n"
            "    return default\n\n"
            "def __agentic_generate_text(prompt, label):\n"
            "    try:\n"
            "        text = llm_generate_text(prompt)\n"
            "    except Exception as exc:\n"
            "        raise RuntimeError(f'AI生成{label}失败：{exc}')\n"
            "    text = str(text or '').strip()\n"
            "    if not text:\n"
            "        raise RuntimeError(f'AI生成{label}失败：返回为空')\n"
            "    return text\n\n"
            "def __agentic_strip_generated_body_title(text, title):\n"
            "    lines = str(text or '').splitlines()\n"
            "    while lines and not lines[0].strip():\n"
            "        lines.pop(0)\n"
            "    if not lines:\n"
            "        return ''\n"
            "    first = lines[0].strip()\n"
            "    clean_first = first.lstrip('#').strip()\n"
            "    clean_title = str(title or '').strip()\n"
            "    if first.startswith('#') or (clean_title and clean_first == clean_title):\n"
            "        lines.pop(0)\n"
            "        while lines and not lines[0].strip():\n"
            "            lines.pop(0)\n"
            "    return '\\n'.join(lines).strip()\n\n"
            "def __agentic_ensure_generated_body_colors(text, requirement):\n"
            "    value = str(text or '')\n"
            "    if not __agentic_wps_requests_color(requirement):\n"
            "        return value\n"
            "    lowered = value.lower()\n"
            "    if 'color:' in lowered or '<font' in lowered:\n"
            "        return value\n"
            "    colors = ('#C00000', '#1F4E79', '#548235')\n"
            "    color_index = 0\n"
            "    result = []\n"
            "    for line in value.splitlines():\n"
            "        stripped = line.strip()\n"
            "        can_color = (\n"
            "            stripped\n"
            "            and not stripped.startswith('#')\n"
            "            and not stripped.startswith('[[')\n"
            "            and color_index < len(colors)\n"
            "        )\n"
            "        if can_color:\n"
            "            result.append(\n"
            "                f'<span style=\"color:{colors[color_index]}\">{stripped}</span>'\n"
            "            )\n"
            "            color_index += 1\n"
            "        else:\n"
            "            result.append(line)\n"
            "    return '\\n'.join(result).strip()\n\n"
            "def __agentic_prepare_wps_body(current, current_title, allow_ai, markdown_path):\n"
            "    global __agentic_wps_body_format, __agentic_wps_table_requested, __agentic_wps_table_requirement\n"
            "    if not __agentic_is_missing_param(markdown_path):\n"
            "        return current\n"
            "    if allow_ai:\n"
            "        mode = panel_prompt('WPS 正文请选择输入方式：[AI生成] [手动输入/确认]')\n"
            "    else:\n"
            "        mode = '手动输入/确认'\n"
            "    if allow_ai and __agentic_is_ai_mode(mode):\n"
            "        __agentic_wps_body_format = 'markdown'\n"
            "        topic = __agentic_wps_topic_input(current)\n"
            "        count = __agentic_optional_input('正文字数', '-1', '800', '默认800')\n"
            "        table_instruction = ''\n"
            "        if __agentic_wps_requests_table(topic):\n"
            "            __agentic_wps_table_requested = True\n"
            "            table_answer = panel_prompt(\n"
            "                '检测到文章要求包含表格。请输入表格内容、列名、数据或样式要求；如无额外要求请输入“无”，由 AI 根据文章自由设计：'\n"
            "            )\n"
            "            table_answer = str(table_answer or '').strip()\n"
            "            if table_answer.lower() in {'无', '无要求', '没有', 'none', 'no'}:\n"
            "                table_answer = ''\n"
            "            __agentic_wps_table_requirement = table_answer or '请根据文章主题和正文自行设计最有帮助的表格'\n"
            "            table_instruction = (\n"
            "                '\\n文章需要插入一个表格。请根据内容结构自行决定最合适的位置，'\n"
            "                '并在该位置单独输出一行 [[WPS_TABLE_1]]。'\n"
            "                '不要直接输出 Markdown 表格，也不要解释占位符。\\n'\n"
            "                f'表格要求：{__agentic_wps_table_requirement}\\n'\n"
            "            )\n"
            "        prompt = (\n"
            "            '请严格按照下面的用户原始要求生成 WPS 文章正文，不要擅自添加用户未要求的格式。\\n'\n"
            "            f'用户原始要求：\\n{topic}\\n\\n'\n"
            "            f'参考标题：{current_title}\\n目标字数：约{count}字。\\n'\n"
            "            '仅当用户原始要求明确提出对应格式时，才使用以下兼容标记：'\n"
            "            '不同颜色使用 <span style=\"color:#RRGGBB\">文字</span>，'\n"
            "            '下划线使用 <u>文字</u>，加粗使用 **文字**，斜体使用 *文字*；'\n"
            "            '用户未要求的格式不得添加。\\n'\n"
            "            '如果用户要求应用不同颜色的字，必须至少选择三处正文重点，分别使用 '\n"
            "            '<span style=\"color:#C00000\">文字</span>、'\n"
            "            '<span style=\"color:#1F4E79\">文字</span> 和 '\n"
            "            '<span style=\"color:#548235\">文字</span>。\\n'\n"
            "            '当前模型不支持生成图片。不得输出图片、配图建议或任何图片占位符，'\n"
            "            '包括 [图片：说明]、[配图：说明]、[插图：说明] 等形式。\\n'\n"
            "            '只生成文章正文，不要输出文章标题，也不要在开头使用一级标题。\\n'\n"
            "            f'{table_instruction}'\n"
            "            '只输出最终正文，不要附加解释或 Markdown 代码块。'\n"
            "        )\n"
            "        try:\n"
            "            generated = __agentic_generate_text(prompt, 'WPS正文')\n"
            "            generated = __agentic_strip_generated_body_title(generated, current_title)\n"
            "            generated = __agentic_ensure_generated_body_colors(generated, topic)\n"
            "            if __agentic_wps_table_requested and '[[WPS_TABLE_1]]' not in generated:\n"
            "                generated = generated.rstrip() + '\\n\\n[[WPS_TABLE_1]]'\n"
            "            return generated\n"
            "        except Exception as exc:\n"
            "            __agentic_wps_body_format = 'plain'\n"
            "            fallback = panel_prompt(f'AI生成 WPS 正文失败：{exc}。请手动输入正文后继续：')\n"
            "            fallback = str(fallback or '').strip()\n"
            "            if fallback:\n"
            "                return fallback\n"
            "            return __agentic_required_input('请手动输入 WPS 正文：', '正文')\n"
            "    return __agentic_confirm_required('body', current, '正文内容')\n\n"
            "def __agentic_prepare_wps_tables(body):\n"
            "    if not __agentic_wps_table_requested:\n"
            "        return '-1'\n"
            "    prompt = (\n"
            "        '请为下面的 WPS 文章生成表格数据。只返回严格 JSON，不要使用 Markdown 代码块，不要解释。\\n'\n"
            "        'JSON 必须使用这个结构：'\n"
            "        '{\"tables\":[{\"placeholder\":\"[[WPS_TABLE_1]]\",'\n"
            "        '\"title\":\"表格标题\",\"columns\":[\"列1\",\"列2\"],'\n"
            "        '\"rows\":[[\"值1\",\"值2\"]],'\n"
            "        '\"style\":{\"header_bold\":true,\"border\":\"grid\",\"auto_fit\":true}}]}。\\n'\n"
            "        '要求：只生成一个表格；列数 2 到 8；数据行不超过 20；每行列数必须与 columns 一致；'\n"
            "        '不能确定的内容用合理概括，不要伪造精确实时数据。\\n'\n"
            "        f'用户表格要求：{__agentic_wps_table_requirement}\\n\\n'\n"
            "        f'文章正文：\\n{body}'\n"
            "    )\n"
            "    return __agentic_generate_text(prompt, 'WPS表格数据')\n\n"
            "def __agentic_prepare_wps_title(current, body, allow_ai, markdown_path):\n"
            "    if not __agentic_is_missing_param(markdown_path) and not __agentic_is_missing_param(current):\n"
            "        return current\n"
            "    if allow_ai:\n"
            "        mode = panel_prompt('WPS 标题请选择输入方式：[AI生成] [手动输入/确认]')\n"
            "    else:\n"
            "        mode = '手动输入/确认'\n"
            "    if allow_ai and __agentic_is_ai_mode(mode):\n"
            "        count = __agentic_optional_input('标题字数限制', '-1', '20', '默认20')\n"
            "        prompt = (\n"
            "            f'请根据下面正文生成一个适合 WPS 文档的中文标题，不超过{count}字。'\n"
            "            '要求准确、自然。只输出标题。\\n\\n正文：\\n'\n"
            "            f'{body}'\n"
            "        )\n"
            "        try:\n"
            "            return __agentic_generate_text(prompt, 'WPS标题')\n"
            "        except Exception as exc:\n"
            "            fallback = panel_prompt(f'AI生成 WPS 标题失败：{exc}。请手动输入标题后继续：')\n"
            "            fallback = str(fallback or '').strip()\n"
            "            if fallback:\n"
            "                return fallback\n"
            "            return __agentic_required_input('请手动输入 WPS 标题：', '标题')\n"
            "    return __agentic_confirm_required('title', current, '文档标题')\n\n"
            "def __agentic_prepare_wps_save_path(output_dir, docx_path, pdf_path, default_output_dir):\n"
            "    current = default_output_dir\n"
            "    for candidate in (pdf_path, docx_path, output_dir):\n"
            "        if not __agentic_is_missing_param(candidate):\n"
            "            current = candidate\n"
            "            break\n"
            "    answer = panel_prompt(\n"
            "        f'请输入或确认 WPS 保存地址（可填目录、.docx 或 .pdf；直接回车使用默认/当前值）。当前值：{current}'\n"
            "    )\n"
            "    answer = str(answer or '').strip()\n"
            "    if not answer:\n"
            "        answer = current\n"
            "    if __agentic_is_missing_param(answer):\n"
            "        return output_dir, docx_path, pdf_path\n"
            "    lowered = answer.lower()\n"
            "    if lowered.endswith('.pdf'):\n"
            "        return '-1', '-1', answer\n"
            "    if lowered.endswith('.docx') or lowered.endswith('.doc'):\n"
            "        return '-1', answer, '-1'\n"
            "    return answer, '-1', '-1'\n"
            "\n"
            "def __agentic_prepare_wps_output_format(current):\n"
            "    aliases = {\n"
            "        'pdf': 'pdf',\n"
            "        'word': 'word', 'doc': 'word', 'docx': 'word',\n"
            "        'both': 'both', 'all': 'both',\n"
            "        '两种': 'both', '两种形式': 'both',\n"
            "        'pdf和word': 'both', 'pdf 和 word': 'both',\n"
            "    }\n"
            "    current_text = str(current or '').strip().lower()\n"
            "    default_value = aliases.get(current_text, 'both')\n"
            "    answer = panel_prompt(\n"
            "        '请选择 WPS 输出格式：[PDF] [Word] [PDF 和 Word]（默认同时输出 PDF 和 Word）'\n"
            "    )\n"
            "    answer_text = str(answer or '').strip().lower()\n"
            "    if not answer_text:\n"
            "        return default_value\n"
            "    return aliases.get(answer_text, default_value)\n"
            "\n"
            "def __agentic_prepare_wps_image(insert_image, image_path):\n"
            "    true_values = {'true', '1', 'yes', 'y', '是', '需要', '插入', '添加', '加入', '放入'}\n"
            "    false_values = {'false', '0', 'no', 'n', '否', '不需要', '不要', '无需', '取消'}\n"
            "    image_text = str(image_path or '').strip()\n"
            "    choice_text = str(insert_image or '').strip().lower()\n"
            "    if choice_text in false_values:\n"
            "        default_choice = 'no'\n"
            "    elif not __agentic_is_missing_param(image_text) or choice_text in true_values:\n"
            "        default_choice = 'yes'\n"
            "    else:\n"
            "        default_choice = 'no'\n"
            "    answer = panel_prompt(\n"
            "        f'是否在 WPS 文档末尾插入图片？当前默认：{default_choice}。[yes] [no]'\n"
            "    )\n"
            "    answer_text = str(answer or '').strip().lower() or default_choice\n"
            "    if answer_text in false_values or answer_text == 'no':\n"
            "        return '-1'\n"
            "    if answer_text not in true_values and answer_text != 'yes':\n"
            "        return '-1'\n"
            "    current = image_text if not __agentic_is_missing_param(image_text) else '-1'\n"
            "    attempts = 0\n"
            "    while True:\n"
            "        attempts += 1\n"
            "        answer = panel_prompt(\n"
            "            f'请输入或确认要插入的本地图片完整路径。当前值：{current}'\n"
            "        )\n"
            "        answer = str(answer or '').strip().strip('\\\"').strip(\"'\")\n"
            "        if answer:\n"
            "            return answer\n"
            "        if not __agentic_is_missing_param(current):\n"
            "            return current\n"
            "        if attempts >= 3:\n"
            "            raise RuntimeError('选择插入图片后必须提供本地图片完整路径')\n"
            "\n"
            "def __agentic_prepare_wps_file_name(current, title):\n"
            "    title_text = str(title or '').strip()\n"
            "    default_name = title_text if not __agentic_is_missing_param(title_text) else '新建文档'\n"
            "    current_text = str(current or '').strip()\n"
            "    if not __agentic_is_missing_param(current_text):\n"
            "        default_name = current_text\n"
            "    panel_set_fields([{\n"
            "        'name': 'file_name',\n"
            "        'label': '文档名称',\n"
            "        'required': False,\n"
            "        'default_value': default_name,\n"
            "    }])\n"
            "    try:\n"
            "        answer = panel_prompt(\n"
            "            f'请输入 WPS 文档名称（不含扩展名），或点击“使用默认值 {default_name}”。'\n"
            "        )\n"
            "    finally:\n"
            "        panel_set_fields([])\n"
            "    answer = str(answer or '').strip().strip('\\\"').strip(\"'\")\n"
            "    return answer or default_name\n"
        )

        return (
            f"{source_code}"
            f"{helper}"
            f"__agentic_wps_body_format = {body_format_value}\n"
            "__agentic_wps_table_requested = False\n"
            "__agentic_wps_table_requirement = '-1'\n"
            "if __agentic_is_missing_param(__agentic_wps_body_format):\n"
            "    __agentic_wps_body_format = 'plain'\n"
            f"__wps_markdown_path = {markdown_path_value}\n"
            f"__param_body = __agentic_prepare_wps_body({body_value}, {title_value}, {body_ai_generate!r}, __wps_markdown_path)\n"
            "__param_table_json = __agentic_prepare_wps_tables(__param_body)\n"
            f"__param_title = __agentic_prepare_wps_title({title_value}, __param_body, {title_ai_generate!r}, __wps_markdown_path)\n"
            f"__legacy_font_name = {font_name_value}\n"
            f"__legacy_font_size = {font_size_value}\n"
            f"__param_title_font_name = __agentic_optional_input('标题字体', {title_font_name_value} if not __agentic_is_missing_param({title_font_name_value}) else __legacy_font_name, {title_font_name_default})\n"
            f"__param_title_font_size = __agentic_optional_input('标题字号', {title_font_size_value}, {title_font_size_default})\n"
            f"__param_body_font_name = __agentic_optional_input('正文字体', {body_font_name_value} if not __agentic_is_missing_param({body_font_name_value}) else __legacy_font_name, {body_font_name_default})\n"
            f"__param_body_font_size = __agentic_optional_input('正文字号', {body_font_size_value} if not __agentic_is_missing_param({body_font_size_value}) else __legacy_font_size, {body_font_size_default})\n"
            f"__param_image_path = __agentic_prepare_wps_image({insert_image_value}, {image_path_value})\n\n"
            f"__param_output_dir, __param_docx_path, __param_pdf_path = __agentic_prepare_wps_save_path({output_dir_value}, {docx_path_value}, {pdf_path_value}, {default_output_dir_value})\n\n"
            f"__param_output_format = __agentic_prepare_wps_output_format({output_format_value})\n\n"
            f"__param_file_name = __agentic_prepare_wps_file_name({file_name_value}, __param_title)\n\n"
            "# 自动调用\n"
            "run(\n"
            "    title=__param_title,\n"
            "    body=__param_body,\n"
            "    output_dir=__param_output_dir,\n"
            "    docx_path=__param_docx_path,\n"
            "    pdf_path=__param_pdf_path,\n"
            "    output_format=__param_output_format,\n"
            "    file_name=__param_file_name,\n"
            "    markdown_path=__wps_markdown_path,\n"
            "    body_format=__agentic_wps_body_format,\n"
            "    font_name=__legacy_font_name,\n"
            "    font_size=__legacy_font_size,\n"
            "    title_font_name=__param_title_font_name,\n"
            "    title_font_size=__param_title_font_size,\n"
            "    body_font_name=__param_body_font_name,\n"
            "    body_font_size=__param_body_font_size,\n"
            f"    font_color={font_color_value},\n"
            f"    italic={italic_value},\n"
            "    image_path=__param_image_path,\n"
            "    table_json=__param_table_json,\n"
            ")"
        )

    @staticmethod
    def _is_gmail_send_intent(query_lower: str) -> bool:
        if "gmail" not in query_lower:
            return False
        send_markers = (
            "gmail发送邮件",
            "gmail发邮件",
            "gmail寄邮件",
            "发送邮件",
            "发邮件",
            "寄邮件",
            "邮件发送",
            "send email",
            "compose email",
        )
        return any(marker in query_lower for marker in send_markers)

    def _match_score(self, skill: SkillRouterInfo, query_lower: str) -> float:
        """计算技能与查询的匹配分数 (0.0 ~ 1.0)。"""
        score = 0.0

        # trigger_patterns：命中 → 高分直接返回；未命中 → 不加分，继续算其他信号
        if skill.trigger_patterns:
            for pattern in skill.trigger_patterns:
                if re.search(pattern, query_lower, re.IGNORECASE | re.DOTALL):
                    return 0.95
            # 未命中正则，但不 return 0 — 让下面的触发词/描述信号继续评分

        # 触发词匹配（核心信号，权重最高）
        matched_triggers = 0
        for trigger in skill.triggers:
            if trigger.lower() in query_lower:
                matched_triggers += 1
        if matched_triggers > 0:
            score += 0.4 + 0.15 * min(matched_triggers, 3)

        # 示例匹配（token 级重叠，避免 CJK 字符级假阳性）
        query_tokens = self._tokenize(query_lower)
        best_example_overlap = 0.0
        for example in skill.examples:
            ex_tokens = self._tokenize(example.lower())
            if query_tokens and ex_tokens:
                overlap = len(query_tokens & ex_tokens) / len(query_tokens)
                best_example_overlap = max(best_example_overlap, overlap)
        if best_example_overlap > 0.3:
            score += 0.15 * best_example_overlap

        # 描述匹配（辅助信号）
        desc_lower = skill.description.lower()
        desc_keywords = [w for w in query_lower.split() if len(w) > 1]
        desc_hits = sum(1 for w in desc_keywords if w in desc_lower)
        if desc_hits > 0 and desc_keywords:
            score += 0.1 * (desc_hits / len(desc_keywords))

        return min(score, 1.0)

    @staticmethod
    def _tokenize(text: str) -> set:
        """将文本分词为 token 集合（空格分词 + CJK 二元组）。"""
        tokens = set()
        # 空格分词
        for word in text.split():
            if len(word) >= 2:
                tokens.add(word)
        # CJK 二元组（连续中文字符）
        cjk_run = []
        for ch in text:
            if "一" <= ch <= "鿿":
                cjk_run.append(ch)
            else:
                if len(cjk_run) >= 2:
                    for i in range(len(cjk_run) - 1):
                        tokens.add("".join(cjk_run[i : i + 2]))
                cjk_run = []
        if len(cjk_run) >= 2:
            for i in range(len(cjk_run) - 1):
                tokens.add("".join(cjk_run[i : i + 2]))
        return tokens

    # -------------------------------------------------------------------
    # Stage 3: LLM 精排（含 explore 选项）
    # -------------------------------------------------------------------

    def _llm_rank(
        self,
        task: str,
        candidates: List[tuple[SkillRouterInfo, float]],
        page_context: Optional[Dict[str, str]] = None,
        force_pick: bool = False,
    ) -> Optional[SkillDecision]:
        """用 LLM 从候选技能中选出最佳匹配，或判定需要 explore。

        LLM 可以返回:
        - 技能 id → 匹配该技能
        - "explore" → 没有合适技能，需要探索式操作
        - "None" → 无法匹配（闲聊/询问等）
        """
        if not self._llm_caller:
            return None

        # 构建候选列表（只发必要信息，省 token）
        candidate_list = []
        for skill, kw_score in candidates:
            entry = {
                "id": skill.id,
                "name": skill.name,
                "description": skill.description,
                "platform": skill.platform,
                "action": skill.action,
            }
            if skill.examples:
                entry["examples"] = skill.examples[:3]
            candidate_list.append(entry)

        prompt = self._build_rank_prompt(task, candidate_list, page_context, force_pick)
        candidate_ids = [skill.id for skill, _ in candidates]
        # skill_id 可以是候选 id、"explore" 或 "None"
        valid_ids = candidate_ids + ["explore", "None"]
        schema = {
            "type": "object",
            "properties": {
                "skill_id": {"type": "string", "enum": valid_ids},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "reason": {"type": "string"},
            },
            "required": ["skill_id", "confidence"],
        }

        try:
            data = self._llm_caller.call_json(
                prompt,
                schema=schema,
                system_prompt="你是任务路由器。根据用户输入，从候选 skill 中选最匹配的一个，或判定需要探索式操作。",
                max_tokens=2048,
            )
        except Exception as exc:
            logger.warning("LLM 精排失败: %s", exc)
            return None

        chosen_id = data.get("skill_id", "")
        try:
            confidence = float(data.get("confidence", 0) or 0)
        except (TypeError, ValueError):
            logger.warning("LLM 精排返回非法 confidence: %s", data.get("confidence"))
            return None
        reason = data.get("reason", "")

        # LLM 选择 explore
        if chosen_id == "explore":
            logger.info("LLM 精排选择 explore (confidence=%.2f, reason=%s)", confidence, reason)
            return SkillDecision(
                confidence=confidence,
                reason=reason,
                source="llm_explore",
            )

        # LLM 选择 None（无法匹配）
        if chosen_id == "None":
            logger.info("LLM 精排返回 None (reason=%s)", reason)
            return None

        if confidence < 0.5 and not force_pick:
            logger.info("LLM 精排置信度过低 (%.2f)，忽略", confidence)
            return None

        candidate_map = {s.id: s for s, _ in candidates}
        chosen_skill = candidate_map.get(chosen_id)
        if not chosen_skill:
            logger.warning("LLM 精排返回未知技能 ID: %s", chosen_id)
            return None

        logger.info(
            "LLM 精排选择: %s (confidence=%.2f, reason=%s)",
            chosen_id,
            confidence,
            reason,
        )

        return SkillDecision(
            skill=chosen_skill,
            confidence=max(confidence, 0.65) if force_pick else confidence,
            reason=reason,
            source="llm",
        )

    def _build_rank_prompt(
        self,
        task: str,
        candidates: List[Dict],
        page_context: Optional[Dict[str, str]] = None,
        force_pick: bool = False,
    ) -> str:
        """构造 LLM 精排 prompt（含 explore 选项）。"""
        candidates_json = json.dumps(candidates, ensure_ascii=False, indent=2)

        context_line = ""
        if page_context:
            context_line = (
                "\n当前页面: " + page_context.get("url", "")
                + " — " + page_context.get("title", "") + "\n"
            )

        if force_pick:
            force_rules = (
                "\n4. 当前必须从候选 skill_id 中选择一个最符合用户意图的技能。"
                "\n5. 如果用户说'在A搜索B'，通常 A 是平台，B 是关键词。"
                "\n6. 如果用户说'用A搜索B'，通常 A 是搜索引擎/平台，B 是关键词。"
            )
        else:
            force_rules = '\n4. 如果候选技能只是沾边但意图不对，输出 "None"。'

        return (
            "你是意图匹配专家。根据用户指令，从候选技能中选出最匹配的一个，或判定需要探索式操作。\n\n"
            "用户指令: " + task + context_line + "\n"
            "候选技能:\n" + candidates_json + "\n\n"
            "特殊选项:\n"
            "- \"explore\": 用户指令需要在网页上进行探索式操作（点击、填写表单、浏览、查找页面元素等），没有现成技能可直接完成。\n"
            "- \"None\": 用户指令是询问、闲聊、评价，或不属于任何候选技能。\n\n"
            "匹配规则:\n"
            "1. 只选择指令明确要求【执行】的技能，询问/评价/闲聊返回 \"None\"\n"
            "2. 指令为'在XX搜索YY'类，XX 是平台，YY 是关键词\n"
            "3. 需要多步网页操作且无匹配技能 → \"explore\"" + force_rules + "\n\n"
            "请直接输出 skill_id（候选 id / \"explore\" / \"None\"）和 confidence。"
        )

    # -------------------------------------------------------------------
    # 脚本构建
    # -------------------------------------------------------------------

    def build_script(self, skill: SkillRouterInfo, task: str) -> str:
        """根据技能定义和任务描述生成可执行脚本。

        流程:
        1. 读取技能源码
        2. 如果有 params 声明 → 用 regex 从任务中提取参数 → 拼 run() 调用
        3. 如果没有 params → 委托给旧的关键词提取逻辑
        """
        if not skill.source_file or not self._library_dir:
            return ""

        source_path = self._library_dir / skill.source_file
        if not source_path.exists():
            logger.warning("技能源码不存在: %s", source_path)
            return ""

        source_code = source_path.read_text(encoding="utf-8")

        if skill.id == "domain/wps_writer_export" and skill.params:
            return self._build_parametrized_script(source_code, skill, task)

        # 检查源码是否已经自带 run() 调用
        code_without_defs = re.sub(r"def\s+\w+\s*\([^)]*\)\s*:", "", source_code)
        if "run(" in code_without_defs:
            return source_code

        # 有参数声明 → 通用参数提取
        if skill.params:
            return self._build_parametrized_script(source_code, skill, task)

        # 无参数声明 → 使用通用关键词提取，避免 AgentLoop 再拼特化脚本。
        return self._build_keyword_script(source_code, task)

    def _build_parametrized_script(
        self,
        source_code: str,
        skill: SkillRouterInfo,
        task: str,
    ) -> str:
        """根据 params 声明从任务中提取参数，生成 run() 调用。"""
        extracted: Dict[str, str] = {param_name: "-1" for param_name in skill.params}

        for param_name, param_def in skill.params.items():
            value = self._extract_param(task, param_name, param_def)
            if value:
                extracted[param_name] = value

        # 构造 run() 调用
        llm_values = self._extract_params_with_llm(skill, task, extracted)
        for param_name, value in llm_values.items():
            if extracted.get(param_name, "-1") == "-1" and value and value != "-1":
                extracted[param_name] = value

        if skill.id == "domain/zhihu_send":
            return self._build_zhihu_article_param_script(source_code, skill, extracted)

        if skill.id == "domain/wps_writer_export":
            return self._build_wps_writer_param_script(source_code, skill, extracted)

        param_lines = []
        args_parts = []
        for param_name in skill.params:
            param_def = skill.params[param_name]
            raw_value = extracted.get(param_name, "-1")
            required = bool(param_def.get("required", False))
            if raw_value == "-1" and not required:
                continue
            if param_def.get("type") == "boolean" and str(raw_value).lower() in {"true", "false"}:
                value = "True" if str(raw_value).lower() == "true" else "False"
            else:
                value = json.dumps(raw_value, ensure_ascii=False)
            safe_param_name = re.sub(r"\W", "_", param_name)
            var_name = f"__param_{safe_param_name}"
            prompt_label = param_def.get("description") or param_name
            prompt_text = f"请确认技能「{skill.name}」的参数「{prompt_label}」。当前值：{raw_value}。如需修改请输入新值，直接回车则沿用当前值："
            ai_generate = bool(param_def.get("ai_generate", False))
            should_confirm_param = self._should_confirm_param(
                skill,
                param_def=param_def,
                raw_value=raw_value,
                required=required,
            )
            if should_confirm_param:
                param_lines.append(
                    f"{var_name} = __agentic_prepare_param("
                    f"{json.dumps(skill.name, ensure_ascii=False)}, "
                    f"{json.dumps(param_name, ensure_ascii=False)}, "
                    f"{json.dumps(prompt_label, ensure_ascii=False)}, "
                    f"{value}, "
                    f"{json.dumps(prompt_text, ensure_ascii=False)}, "
                    f"{required!r}, "
                    f"{ai_generate!r})"
                )
            else:
                param_lines.append(f"{var_name} = {value}")
            if param_def.get("positional", False):
                args_parts.append(var_name)
            else:
                args_parts.append(f"{param_name}={var_name}")

        args_str = ", ".join(args_parts)
        needs_param_helper = any("__agentic_prepare_param(" in line for line in param_lines)
        generic_ai_helper = (
            "\n\n# Generic AI parameter generation\n"
            "def __agentic_is_ai_mode(answer):\n"
            "    text = str(answer or '').strip().lower()\n"
            "    return text in {'ai', 'ai生成', '生成', '自动生成', 'yes', 'y', '1', 'true', '是'}\n\n"
            "def __agentic_generate_text(prompt, label):\n"
            "    try:\n"
            "        text = llm_generate_text(prompt)\n"
            "    except Exception as exc:\n"
            "        raise RuntimeError(f'AI生成{label}失败：{exc}')\n"
            "    text = str(text or '').strip()\n"
            "    if not text:\n"
            "        raise RuntimeError(f'AI生成{label}失败：返回为空')\n"
            "    return text\n\n"
            "def __agentic_prepare_param(skill_name, name, label, value, question, required, allow_ai):\n"
            "    if allow_ai:\n"
            "        mode = panel_prompt(f'参数「{label}」请选择输入方式：[AI生成] [手动输入/确认]')\n"
            "        if __agentic_is_ai_mode(mode):\n"
            "            requirement = panel_prompt(f'请描述要生成的「{label}」要求。当前值：{value}。可以写主题、字数、风格等：')\n"
            "            requirement = str(requirement or '').strip()\n"
            "            if not requirement and not __agentic_is_missing_param(value):\n"
            "                requirement = str(value)\n"
            "            if not requirement:\n"
            "                requirement = f'生成适合参数「{label}」的内容'\n"
            "            prompt = (\n"
            "                f'你正在为自动化技能「{skill_name}」生成参数「{label}」（内部名：{name}）。'\n"
            "                f'用户要求：{requirement}。'\n"
            "                '请只输出最终要填入该参数的内容，不要解释，不要 Markdown 代码块。'\n"
            "            )\n"
            "            try:\n"
            "                return __agentic_generate_text(prompt, label)\n"
            "            except Exception as exc:\n"
            "                fallback = panel_prompt(f'AI生成「{label}」失败：{exc}。请手动输入该参数后继续：')\n"
            "                fallback = str(fallback or '').strip()\n"
            "                if fallback:\n"
            "                    return fallback\n"
            "    return __agentic_confirm_required_param(name, value, question, required)\n"
        )
        pre_auth = self._build_pre_auth_script(skill, wait_for_manual=False)
        auth_wait = self._build_pre_auth_script(skill, wait_for_manual=True)
        helper = (
            "\n\n# 自动补全缺失参数\n"
            "def __agentic_is_missing_param(value):\n"
            "    return value is None or str(value).strip() in {'', '-1', 'None', 'none', 'null'}\n\n"
            "def __agentic_confirm_required_param(name, value, question, required):\n"
            "    attempts = 0\n"
            "    while required:\n"
            "        attempts += 1\n"
            "        answer = panel_prompt(question)\n"
            "        answer = str(answer or '').strip()\n"
            "        if answer:\n"
            "            return answer\n"
            "        if not __agentic_is_missing_param(value):\n"
            "            return value\n"
            "        if attempts >= 3:\n"
            "            raise RuntimeError(f'缺少必填参数：{name}')\n"
            "        question = f'参数「{name}」是必填项，请输入后再继续：'\n"
            "    return value\n"
        )
        return (
            f"{source_code}"
            f"{helper if needs_param_helper else ''}"
            f"{generic_ai_helper if needs_param_helper else ''}"
            f"{pre_auth}"
            f"{chr(10).join(param_lines)}\n\n"
            f"{auth_wait}"
            f"# 自动调用\n"
            f"{('__result__ = ' if skill.id == 'domain/taobao_search' else '')}run({args_str})"
        )

    @staticmethod
    def _should_confirm_param(
        skill: SkillRouterInfo,
        *,
        param_def: Dict[str, Any],
        raw_value: str,
        required: bool,
    ) -> bool:
        if raw_value == "-1":
            return required
        if param_def.get("confirm", True) is False:
            return False
        if skill.platform.lower() == "wechat":
            return False
        return True

    @staticmethod
    def _build_pre_auth_script(
        skill: SkillRouterInfo,
        *,
        wait_for_manual: bool,
    ) -> str:
        """Build auth preparation or the final manual-login wait."""
        marker = " ".join(
            [
                skill.id,
                skill.platform,
                skill.source_file,
            ]
        ).lower()

        domain = ""
        sign_url = ""
        if "xiaohongshu" in marker or "xhs" in marker:
            domain = "xiaohongshu"
            sign_url = "https://www.xiaohongshu.com/login"
        elif "zhihu" in marker or "zhuanlan.zhihu" in marker:
            domain = "zhihu"
            sign_url = "https://www.zhihu.com/signin"

        if not domain:
            return ""

        return (
            "\n\n# Two-stage authentication\n"
            f"__agentic_sign_url = {json.dumps(sign_url, ensure_ascii=False)}\n"
            "try:\n"
            "    __agentic_sign_url = SIGN_URL\n"
            "except Exception:\n"
            "    pass\n"
            f"ensure_auth({json.dumps(domain, ensure_ascii=False)}, "
            f"__agentic_sign_url, {wait_for_manual!r})\n"
        )

    def _extract_params_with_llm(
        self,
        skill: SkillRouterInfo,
        task: str,
        rule_values: Dict[str, str],
    ) -> Dict[str, str]:
        """Extract declared skill params with LLM. Missing values are "-1"."""
        if not self._llm_caller:
            return {}

        params_meta: Dict[str, Dict[str, Any]] = {}
        for name, meta in skill.params.items():
            params_meta[name] = {
                "type": meta.get("type", "string"),
                "required": bool(meta.get("required", False)),
                "description": meta.get("description", ""),
            }

        skill_meta = {
            "id": skill.id,
            "name": skill.name,
            "description": skill.description,
            "examples": skill.examples[:5],
        }

        prompt = (
            "You are a strict parameter extractor for browser automation.\n"
            "The skill has already been selected. Extract values from the user task "
            "for every declared parameter.\n\n"
            f"User task:\n{task}\n\n"
            f"Selected skill:\n{json.dumps(skill_meta, ensure_ascii=False, indent=2)}\n\n"
            f"Declared parameters:\n{json.dumps(params_meta, ensure_ascii=False, indent=2)}\n\n"
            f"Values already found by rules:\n{json.dumps(rule_values, ensure_ascii=False, indent=2)}\n\n"
            "Rules:\n"
            "- If a value is clearly present in the user task, return that value as a string.\n"
            "- If a value cannot be found, return \"-1\" for that key.\n"
            "- Do not invent titles, comments, article bodies, phone numbers, or URLs.\n"
        )

        schema = {
            "type": "object",
            "properties": {
                param_name: {"type": ["string", "number", "boolean", "null"]}
                for param_name in skill.params
            },
            "required": list(skill.params),
        }

        try:
            data = self._llm_caller.call_json(
                prompt,
                schema=schema,
                system_prompt="You extract declared browser automation parameters and return only structured values.",
                max_tokens=2048,
            )
        except Exception as exc:
            logger.warning("LLM param extraction failed: %s", exc)
            return {}

        if not isinstance(data, dict):
            logger.warning("LLM param extraction returned non-object")
            return {}

        extracted: Dict[str, str] = {}
        for param_name in skill.params:
            value = data.get(param_name, "-1")
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False)
            if value is None:
                value = "-1"
            value = str(value).strip()
            if not value or value.lower() in {"none", "null", "unknown", "n/a"}:
                value = "-1"
            extracted[param_name] = value
        return extracted

    @staticmethod
    def _extract_param(
        task: str, param_name: str, param_def: Dict[str, Any]
    ) -> Optional[str]:
        """从任务文本中提取单个参数值。"""
        # 1. 优先用自定义 regex patterns
        patterns = param_def.get("extract_patterns", [])
        for pattern in patterns:
            match = re.search(pattern, task, re.IGNORECASE | re.DOTALL)
            if match:
                value = match.group(1).strip()
                quote_chars = "'\"`“”‘’「」"
                value = value.strip(quote_chars)
                value = re.sub(r"[，,。.;；!！?？)）]+$", "", value).strip()
                value = value.strip(quote_chars).strip()
                if value:
                    return value

        # 2. 通用提取：按参数类型
        ptype = param_def.get("type", "string")

        if ptype == "phone":
            candidates = re.findall(r"(?:\+?86[-\s]*)?1[3-9](?:[-\s]*\d){9}", task)
            for candidate in candidates:
                digits = re.sub(r"\D", "", candidate)
                if digits.startswith("86") and len(digits) == 13:
                    digits = digits[2:]
                if re.fullmatch(r"1[3-9]\d{9}", digits):
                    return digits

        if ptype == "email":
            if param_name in {"sender_email", "from_email"}:
                return None
            match = re.search(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", task, re.I)
            if match:
                return match.group(0)

        if ptype == "url":
            match = re.search(r"https?://[A-Za-z0-9:/?#@!$&()*+,;=%._~%-]+", task)
            if match:
                url = match.group(0)
                url = re.split(
                    r"(?=下?(?:发布|发表|发送|发)?(?:评论|留言|回复))",
                    url,
                    maxsplit=1,
                )[0]
                return re.sub(r"[.,;:。，；：!?！?）)>]+$", "", url)

        if ptype == "quoted":
            match = re.search(r"['\"“‘「](.+?)['\"”’」]", task)
            if match:
                return match.group(1).strip()

        if ptype == "content":
            quoted = re.search(r"['\"“‘「](.+?)['\"”’」]", task, re.DOTALL)
            if quoted:
                return quoted.group(1).strip()
            match = re.search(
                r"(?:内容|正文|文案|文章内容|发布内容|content)\s*(?:是|为|:|：|=)?\s*(.+)$",
                task,
                re.IGNORECASE | re.DOTALL,
            )
            if match:
                return match.group(1).strip().strip("'\"`“”‘’「」")

        if ptype == "title":
            quoted = re.search(
                r"(?:标题|题目|title)\s*(?:是|为|:|：|=)?\s*['\"“‘](.+?)['\"”’]",
                task,
                re.IGNORECASE | re.DOTALL,
            )
            if quoted:
                return quoted.group(1).strip()
            match = re.search(
                r"(?:标题|题目|title)\s*(?:是|为|:|：|=)?\s*(.+?)(?=\s*(?:正文|内容|文章内容|body|content)\s*(?:是|为|:|：|=)?|$)",
                task,
                re.IGNORECASE | re.DOTALL,
            )
            if match:
                return re.sub(r"[，,。.;；!！?？)）]+$", "", match.group(1).strip().strip("'\"`“”‘’「」")).strip()

        if ptype == "body":
            quoted = re.search(
                r"(?:正文|正文内容|内容|文章内容|body|content)\s*(?:是|为|:|：|=)?\s*['\"“‘](.+?)['\"”’]",
                task,
                re.IGNORECASE | re.DOTALL,
            )
            if quoted:
                return quoted.group(1).strip()
            match = re.search(
                r"(?:正文|正文内容|内容|文章内容|body|content)\s*(?:是|为|:|：|=)?\s*(.+)$",
                task,
                re.IGNORECASE | re.DOTALL,
            )
            if match:
                return re.sub(r"[，,。.;；!！?？)）]+$", "", match.group(1).strip().strip("'\"`“”‘’「」")).strip()

        if ptype == "comment_text":
            quoted = re.search(r"['\"“‘](.+?)['\"”’]", task, re.DOTALL)
            if quoted:
                return quoted.group(1).strip()
            match = re.search(
                r"(?:评论内容|留言内容|回复内容|评论|留言|回复)\s*(?:是|为|:|：|=)?\s*(.+?)(?=\s*(?:在|然后|并且|接着)|$)",
                task,
                re.IGNORECASE | re.DOTALL,
            )
            if match:
                return re.sub(r"[，,。.;；!！?？)）]+$", "", match.group(1).strip().strip("'\"`“”‘’「」")).strip()

        if ptype in {"image_path", "video_path"}:
            if ptype == "video_path":
                extensions = r"mp4|mov|avi|mkv|webm|m4v"
                labels = r"视频地址|视频路径|视频|video_path|video|地址|path"
            else:
                extensions = r"jpg|jpeg|png|webp|bmp|gif"
                labels = r"图片地址|图片路径|图片|图像|image_path|image|地址|path"

            quoted = re.search(
                rf"(?:{labels})\s*(?:是|为|时|位于|:|：|=)?\s*['\"“‘]([^'\"“”‘’]+?\.(?:{extensions}))['\"”’]",
                task,
                re.IGNORECASE,
            )
            if quoted:
                return quoted.group(1).strip()

            labeled = re.search(
                rf"(?:{labels})\s*(?:是|为|时|位于|:|：|=)?\s*['\"“”‘’]?([A-Za-z]:[\\/][^'\"“”‘’\s，,。；;]+?\.(?:{extensions}))",
                task,
                re.IGNORECASE,
            )
            if labeled:
                return labeled.group(1).strip()

            bare = re.search(
                rf"([A-Za-z]:[\\/][^'\"“”‘’\s，,。；;]+?\.(?:{extensions}))",
                task,
                re.IGNORECASE,
            )
            if bare:
                return bare.group(1).strip()

        if ptype == "publish_mode":
            if re.search(r"(文章|长文|小说|article|novel)", task, re.IGNORECASE):
                return "article"
            if re.search(r"(上传视频|视频地址|视频路径|video)", task, re.IGNORECASE):
                return "video"
            if re.search(r"(上传图片|图片地址|图片路径|image|upload)", task, re.IGNORECASE):
                return "image_upload"
            return "text_to_image"

        if ptype == "style":
            styles = ["基础", "弥散", "涂写", "光影", "手写", "备忘", "边框", "便签", "涂鸦", "简约"]
            for style in styles:
                if style in task:
                    return style

        if ptype == "boolean":
            if param_name == "insert_image":
                if re.search(
                    r"(?:不要|不需要|无需|取消)(?:插入|添加|加入|放入)?(?:一张|本地)?图片",
                    task,
                    re.IGNORECASE,
                ):
                    return "false"
                if re.search(
                    r"(?:插入|添加|加入|放入)(?:一张|本地)?图片|(?:需要|要)(?:一张|本地)?图片",
                    task,
                    re.IGNORECASE,
                ):
                    return "true"
                return None
            if param_name in {"add-picture", "add_picture"}:
                if re.search(
                    r"(配图|加图|加图片|生成图片|插入图片|AI\s*配图|ai\s*picture|add[-_ ]?picture)",
                    task,
                    re.IGNORECASE,
                ):
                    return "true"
                return "false"
            if re.search(r"(定时发布|定时|预约发布|scheduled)", task, re.IGNORECASE):
                return "true"
            return "false"

        if ptype == "datetime":
            match = re.search(
                r"(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})(?:日)?\s+(\d{1,2})[:：点](\d{1,2})",
                task,
            )
            if match:
                year, month, day, hour, minute = match.groups()
                return (
                    f"{int(year):04d}-{int(month):02d}-{int(day):02d} "
                    f"{int(hour):02d}:{int(minute):02d}"
                )
            match = re.search(r"(\d{1,2})月(\d{1,2})日?\s*(\d{1,2})[:：点](\d{1,2})", task)
            if match:
                from datetime import datetime

                month, day, hour, minute = match.groups()
                return (
                    f"{datetime.now().year:04d}-{int(month):02d}-{int(day):02d} "
                    f"{int(hour):02d}:{int(minute):02d}"
                )

        if ptype == "keyword":
            direct_patterns = [
                r"(?:在|用|打开)?\s*(?:百度|baidu|google|谷歌|bing|必应|小红书|xiaohongshu|xhs|rednote|知乎|zhihu|github|amazon|亚马逊|youtube|油管|bilibili|B站|b站|哔哩哔哩|哔哩|微博|weibo|淘宝|taobao|豆包|doubao|csdn|csnd)(?:上)?\s*(?:搜索|搜|查找|查询|查|找|问|问答|search)\s*(.+)$",
                r"(?:搜索|搜|查找|查询|查|找|问|问答|search)\s*(.+?)\s*(?:用|在|到)\s*(?:百度|baidu|google|谷歌|bing|必应|小红书|xiaohongshu|xhs|rednote|知乎|zhihu|github|amazon|亚马逊|youtube|油管|bilibili|B站|b站|哔哩哔哩|哔哩|微博|weibo|淘宝|taobao|豆包|doubao|csdn|csnd)(?:上)?[。.!！?？\s]*$",
            ]
            for pattern in direct_patterns:
                match = re.search(pattern, task, re.IGNORECASE | re.DOTALL)
                if match:
                    keyword = match.group(1).strip().strip("'\"`“”‘’「」")
                    keyword = re.sub(r"[，,。.;；!！?？)）]+$", "", keyword).strip()
                    if keyword:
                        return keyword

            # 提取搜索关键词（去掉动作词和站点名）
            # 注意：长词必须排在短词前面，否则 "搜索" 中的 "搜" 会先被匹配
            keyword = re.sub(
                r"(?:帮我看|帮我查|帮我搜|查查|搜索|查找|看看|一下|search|在|去|到|用|帮|我|搜|查)",
                "",
                task,
                flags=re.IGNORECASE,
            )
            # 去掉已知站点名（包含大小写和常见变体）
            site_names = [
                "哔哩哔哩", "xiaohongshu", "小红书", "bilibili", "youtube",
                "amazon", "google", "doubao", "douyin", "outlook", "douban",
                "taobao", "csnd", "csdn", "github", "gmail", "zhihu",
                "weibo", "pdd", "百度", "谷歌", "必应", "油管", "知乎",
                "微博", "淘宝", "豆包", "抖音", "b站", "B站", "京东",
                "豆瓣", "bing", "Google", "Gmail", "YouTube", "GitHub",
                "Amazon", "Bilibili",
            ]
            for site in site_names:
                keyword = keyword.replace(site, "")
            keyword = keyword.strip()
            if keyword:
                return keyword

        return None

    @staticmethod
    def _build_keyword_script(source_code: str, task: str) -> str:
        """无 params 声明时，用通用关键词提取拼 run() 调用。"""
        run_match = re.search(r"def\s+run\s*\(([^)]*)\)", source_code)
        if run_match:
            params_text = run_match.group(1).strip()
            if not params_text:
                return f"{source_code}\n\n# 自动调用\nrun()"

            required_parts = []
            for part in params_text.split(","):
                part = part.strip()
                if not part or part in {"*", "/"} or part.startswith("*"):
                    continue
                if "=" not in part:
                    required_parts.append(part)
            if not required_parts:
                return f"{source_code}\n\n# 自动调用\nrun()"

        # 提取关键词（去掉常见的动作词和站点名）
        # 注意：长词必须排在短词前面，否则 "搜索" 中的 "搜" 会先被匹配
        direct_patterns = [
            r"(?:在|用|打开)?\s*(?:百度|baidu|google|谷歌|bing|必应|小红书|xiaohongshu|xhs|rednote|知乎|zhihu|github|amazon|亚马逊|youtube|油管|bilibili|B站|b站|哔哩哔哩|哔哩|微博|weibo|淘宝|taobao|豆包|doubao|csdn|csnd)(?:上)?\s*(?:搜索|搜|查找|查询|查|找|问|问答|search)\s*(.+)$",
            r"(?:搜索|搜|查找|查询|查|找|问|问答|search)\s*(.+?)\s*(?:用|在|到)\s*(?:百度|baidu|google|谷歌|bing|必应|小红书|xiaohongshu|xhs|rednote|知乎|zhihu|github|amazon|亚马逊|youtube|油管|bilibili|B站|b站|哔哩哔哩|哔哩|微博|weibo|淘宝|taobao|豆包|doubao|csdn|csnd)(?:上)?[。.!！?？\s]*$",
        ]
        for pattern in direct_patterns:
            match = re.search(pattern, task, re.IGNORECASE | re.DOTALL)
            if match:
                keyword = match.group(1).strip().strip("'\"`“”‘’「」")
                keyword = re.sub(r"[，,。.;；!！?？)）]+$", "", keyword).strip()
                if keyword:
                    return (
                        f"{source_code}\n\n# 自动调用\n"
                        f"run({json.dumps(keyword, ensure_ascii=False)})"
                    )

        keyword = re.sub(
            r"(?:帮我看|帮我查|帮我搜|查查|搜索|查找|看看|一下|search|在|去|到|用|帮|我|搜|查)",
            "",
            task,
            flags=re.IGNORECASE,
        )
        site_names = [
            "哔哩哔哩", "xiaohongshu", "小红书", "bilibili", "youtube",
            "amazon", "google", "doubao", "douyin", "outlook", "douban",
            "taobao", "csnd", "csdn", "github", "gmail", "zhihu",
            "weibo", "pdd", "百度", "谷歌", "必应", "油管", "知乎",
            "微博", "淘宝", "豆包", "抖音", "b站", "B站", "京东",
            "豆瓣", "bing", "Google", "Gmail", "YouTube", "GitHub",
            "Amazon", "Bilibili",
        ]
        for site in site_names:
            keyword = keyword.replace(site, "")
        keyword = keyword.strip()

        if not keyword:
            keyword = "-1"
            return (
                f"{source_code}\n\n# 自动补全缺失关键词\n"
                f"__param_keyword = {json.dumps(keyword, ensure_ascii=False)}\n"
                "if __param_keyword is None or str(__param_keyword).strip() in {'', '-1', 'None', 'none', 'null'}:\n"
                "    __answer = panel_prompt('没有提取到关键词，请输入要使用的关键词：')\n"
                "    __answer = str(__answer or '').strip()\n"
                "    if __answer:\n"
                "        __param_keyword = __answer\n\n"
                "# 自动调用\n"
                "run(__param_keyword)"
            )

        return (
            f"{source_code}\n\n# 自动调用\n"
            f"run({json.dumps(keyword, ensure_ascii=False)})"
        )

    # -------------------------------------------------------------------
    # 查询接口
    # -------------------------------------------------------------------

    def get_skill(self, skill_id: str) -> Optional[SkillRouterInfo]:
        """按 ID 获取技能路由信息。"""
        if not self._loaded:
            self.load()
        return self._skills.get(skill_id)

    def list_skills(self) -> List[SkillRouterInfo]:
        """列出所有已加载的技能。"""
        if not self._loaded:
            self.load()
        return list(self._skills.values())

    def search(self, query: str, limit: int = 10) -> List[SkillRouterInfo]:
        """按关键词搜索技能（返回匹配的技能列表）。"""
        if not self._loaded:
            self.load()
        return [skill for skill, _ in self._recall_candidates(query, limit)]


# ---------------------------------------------------------------------------
# 全局单例
# ---------------------------------------------------------------------------

_instance: SkillRouter | None = None


def get_skill_router(
    library_dir: str | Path | None = None,
    llm_caller: Any = None,
) -> SkillRouter:
    """获取全局单例 SkillRouter。"""
    global _instance
    if _instance is None:
        if library_dir is None:
            library_dir = Path(__file__).parent.parent / "skill_library"
        _instance = SkillRouter(library_dir=library_dir, llm_caller=llm_caller)
    elif llm_caller is not None:
        _instance._llm_caller = llm_caller
    return _instance


def reset_skill_router() -> None:
    """重置全局单例（用于测试）。"""
    global _instance
    _instance = None

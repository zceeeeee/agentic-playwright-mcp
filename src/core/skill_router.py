"""
技能路由器 —— 两阶段路由：关键词快筛 + LLM 精排。

Stage 1: 关键词快筛（零延迟，零成本）
  从 SkillRegistry 中匹配触发词，返回 Top-K 候选。

Stage 2: LLM 精排（仅在歧义时调用）
  将候选列表 + 用户指令发给 LLM，让它选出最佳 skill。

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

        # ── Stage 1: 关键词快筛 ──
        candidates = self._keyword_filter(task, limit=5)

        if not candidates:
            # 严格 trigger 未命中时，让 AI 从技能库中选择，而不是直接放弃。
            if self._llm_caller:
                llm_result = self._llm_rank(
                    task,
                    self._all_skill_candidates(limit=40),
                    page_context,
                )
                if llm_result and llm_result.confidence >= 0.7:
                    script = self.build_script(llm_result.skill, task)
                    return SkillDecision(
                        skill=llm_result.skill,
                        confidence=llm_result.confidence,
                        reason=f"trigger 未命中，由 LLM 选择: {llm_result.reason}",
                        source="llm",
                        script=script,
                    )
                return SkillDecision(source="none", reason="trigger 未命中，LLM 未返回高置信技能")
            return SkillDecision(source="none", reason="trigger 未命中且 LLM 不可用")

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

        if (
            top_skill.id == "domain/xiaohongshu_publish"
            and top_score >= 0.65
            and re.search(r"(发布内容|发布|发表|发帖).+['\"“‘].+['\"”’]", task, re.DOTALL)
        ):
            script = self.build_script(top_skill, task)
            return SkillDecision(
                skill=top_skill,
                confidence=0.85,
                reason=f"默认发布内容匹配: {top_skill.name}",
                source="keyword",
                script=script,
            )

        # 高分 → 直接命中（严格：必须达到阈值，不论候选数量）
        if top_score >= 0.8:
            script = self.build_script(top_skill, task)
            return SkillDecision(
                skill=top_skill,
                confidence=min(top_score, 1.0),
                reason=f"关键词匹配: {top_skill.name}",
                source="keyword",
                script=script,
            )

        # ── Stage 2: LLM 精排 ──
        if self._llm_caller:
            llm_result = self._llm_rank(task, candidates, page_context)
            if llm_result and llm_result.confidence >= 0.6:
                script = self.build_script(llm_result.skill, task)
                return SkillDecision(
                    skill=llm_result.skill,
                    confidence=llm_result.confidence,
                    reason=llm_result.reason,
                    source="llm",
                    script=script,
                )

        # 未达到确定匹配阈值 → 交给上层 LLM 意图解析
        return SkillDecision(source="none", reason="关键词未确定匹配")

    # -------------------------------------------------------------------
    # Stage 1: 关键词快筛
    # -------------------------------------------------------------------

    def _keyword_filter(
        self, query: str, limit: int = 5
    ) -> List[tuple[SkillRouterInfo, float]]:
        """关键词快筛，返回 (skill, score) 列表，按分数降序。"""
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

        # 严格 trigger：有 trigger_patterns 时，只认可完整语义正则。
        if skill.trigger_patterns:
            for pattern in skill.trigger_patterns:
                if re.search(pattern, query_lower, re.IGNORECASE | re.DOTALL):
                    return 0.95
            return 0.0

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
    # Stage 2: LLM 精排
    # -------------------------------------------------------------------

    def _llm_rank(
        self,
        task: str,
        candidates: List[tuple[SkillRouterInfo, float]],
        page_context: Optional[Dict[str, str]] = None,
        force_pick: bool = False,
    ) -> Optional[SkillDecision]:
        """用 LLM 从候选技能中选出最佳匹配。"""
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
        schema = {
            "type": "object",
            "properties": {
                "skill_id": {"type": "string", "enum": candidate_ids},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "reason": {"type": "string"},
            },
            "required": ["skill_id", "confidence"],
        }

        try:
            data = self._llm_caller.call_json(
                prompt,
                schema=schema,
                system_prompt="你是任务路由器。根据用户输入，从候选 skill 中选最匹配的一个。",
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
        """构造 LLM 精排 prompt。"""
        candidates_json = json.dumps(candidates, ensure_ascii=False, indent=2)

        context_line = ""
        if page_context:
            context_line = (
                f"\n当前页面: {page_context.get('url', '')} "
                f"— {page_context.get('title', '')}\n"
            )

        force_rules = (
            "\n3. 当前必须从候选 skill_id 中选择一个最符合用户意图的技能。"
            "\n4. 如果用户说“在A搜索B”，通常 A 是平台，B 是关键词。"
            "\n5. 如果用户说“用A搜索B”，通常 A 是搜索引擎/平台，B 是关键词。"
            if force_pick
            else "\n3. 如果没有明确匹配，confidence 设为 0.3 以下。"
        )

        return f"""你是任务路由器。根据用户输入，从候选 skill 中选最匹配的一个。

用户输入: {task}{context_line}
候选 skills:
{candidates_json}

规则:
1. 优先匹配用户明确提到的站点和操作
2. skill_id 必须是候选 skills 中的 id{force_rules}"""

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
            param_lines.append(
                f"{var_name} = __agentic_confirm_required_param("
                f"{json.dumps(param_name, ensure_ascii=False)}, "
                f"{value}, "
                f"{json.dumps(prompt_text, ensure_ascii=False)}, "
                f"{required!r})"
            )
            if param_def.get("positional", False):
                args_parts.append(var_name)
            else:
                args_parts.append(f"{param_name}={var_name}")

        args_str = ", ".join(args_parts)
        pre_auth = self._build_pre_auth_script(skill)
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
            f"{helper}"
            f"{pre_auth}"
            f"{chr(10).join(param_lines)}\n\n"
            f"# 自动调用\nrun({args_str})"
        )

    @staticmethod
    def _build_pre_auth_script(skill: SkillRouterInfo) -> str:
        """Build an optional auth prompt that runs before parameter prompts."""
        marker = " ".join(
            [
                skill.id,
                skill.platform,
                skill.source_file,
            ]
        ).lower()

        domain = ""
        if "xiaohongshu" in marker or "xhs" in marker:
            domain = "xiaohongshu"
        elif "zhihu" in marker or "zhuanlan.zhihu" in marker:
            domain = "zhihu"

        if not domain:
            return ""

        return (
            "\n\n# 自动登录确认先于参数确认\n"
            "__agentic_sign_url = None\n"
            "try:\n"
            "    __agentic_sign_url = SIGN_URL\n"
            "except Exception:\n"
            "    pass\n"
            f"ensure_auth({json.dumps(domain, ensure_ascii=False)}, __agentic_sign_url)\n"
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
                rf"(?:{labels})\s*(?:是|为|:|：|=)?\s*['\"“‘]([^'\"“”‘’]+?\.(?:{extensions}))['\"”’]",
                task,
                re.IGNORECASE,
            )
            if quoted:
                return quoted.group(1).strip()

            labeled = re.search(
                rf"(?:{labels})\s*(?:是|为|:|：|=)?\s*['\"“”‘’]?([A-Za-z]:[\\/][^'\"“”‘’\s，,。；;]+?\.(?:{extensions}))",
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
        return [skill for skill, _ in self._keyword_filter(query, limit)]


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

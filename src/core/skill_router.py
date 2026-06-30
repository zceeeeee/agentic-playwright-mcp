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
            llm_caller: LLM 调用器，需提供 .call(prompt) -> str 方法。
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
            return SkillDecision(source="none", reason="关键词无匹配")

        top_skill, top_score = candidates[0]

        # 单候选且高分 → 直接命中
        if len(candidates) == 1 or top_score >= 0.8:
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

        # 兜底：取关键词得分最高的
        script = self.build_script(top_skill, task)
        return SkillDecision(
            skill=top_skill,
            confidence=top_score,
            reason=f"关键词兜底: {top_skill.name}",
            source="keyword",
            script=script,
        )

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

    def _match_score(self, skill: SkillRouterInfo, query_lower: str) -> float:
        """计算技能与查询的匹配分数 (0.0 ~ 1.0)。"""
        score = 0.0

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
            }
            if skill.examples:
                entry["examples"] = skill.examples[:3]
            candidate_list.append(entry)

        prompt = self._build_rank_prompt(task, candidate_list, page_context)

        try:
            raw = self._llm_caller.call(prompt)
            return self._parse_rank_response(raw, candidates)
        except Exception as exc:
            logger.warning("LLM 精排失败: %s", exc)
            return None

    def _build_rank_prompt(
        self,
        task: str,
        candidates: List[Dict],
        page_context: Optional[Dict[str, str]] = None,
    ) -> str:
        """构造 LLM 精排 prompt。"""
        candidates_json = json.dumps(candidates, ensure_ascii=False, indent=2)

        context_line = ""
        if page_context:
            context_line = (
                f"\n当前页面: {page_context.get('url', '')} "
                f"— {page_context.get('title', '')}\n"
            )

        return f"""你是任务路由器。根据用户输入，从候选 skill 中选最匹配的一个。

用户输入: {task}{context_line}
候选 skills:
{candidates_json}

返回 JSON:
{{"skill_id": "选中的技能id", "confidence": 0.0-1.0, "reason": "选择原因"}}

规则:
1. 优先匹配用户明确提到的站点和操作
2. 如果没有明确匹配，confidence 设为 0.3 以下
3. 只返回 JSON，不要其他文字"""

    def _parse_rank_response(
        self,
        raw: str,
        candidates: List[tuple[SkillRouterInfo, float]],
    ) -> Optional[SkillDecision]:
        """解析 LLM 精排响应。"""
        text = raw.strip()

        # 提取 JSON 块
        if "```" in text:
            start = text.find("{")
            end = text.rfind("}") + 1
            if start != -1 and end > 0:
                text = text[start:end]

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("LLM 精排返回非 JSON: %s", raw[:200])
            return None

        chosen_id = data.get("skill_id", "")
        confidence = float(data.get("confidence", 0))
        reason = data.get("reason", "")

        if confidence < 0.5:
            logger.info("LLM 精排置信度过低 (%.2f)，忽略", confidence)
            return None

        # 查找对应的候选
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
            confidence=confidence,
            reason=reason,
            source="llm",
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

        if skill.id == "domain/xiaohongshu_publish":
            return ""

        # 检查源码是否已经自带 run() 调用
        code_without_defs = re.sub(r"def\s+\w+\s*\([^)]*\)\s*:", "", source_code)
        if "run(" in code_without_defs:
            return source_code

        # 有参数声明 → 通用参数提取
        if skill.params:
            return self._build_parametrized_script(source_code, skill, task)

        # 无参数声明 → 返回空，让 agent_loop 的旧路径处理（它有更好的关键词提取）
        return ""

    def _build_parametrized_script(
        self,
        source_code: str,
        skill: SkillRouterInfo,
        task: str,
    ) -> str:
        """根据 params 声明从任务中提取参数，生成 run() 调用。"""
        extracted: Dict[str, str] = {}
        missing: List[str] = []

        for param_name, param_def in skill.params.items():
            value = self._extract_param(task, param_name, param_def)
            if value:
                extracted[param_name] = value
            elif param_def.get("required", False):
                missing.append(param_name)

        if missing:
            # 缺少必填参数 → 生成报错脚本，让 agent loop 知道需要追问
            missing_str = ", ".join(missing)
            return (
                f"{source_code}\n\n"
                f"raise ValueError('{skill.id} 缺少必填参数: {missing_str}')"
            )

        # 构造 run() 调用
        args_parts = []
        for param_name in skill.params:
            if param_name in extracted:
                args_parts.append(
                    f"{param_name}={json.dumps(extracted[param_name], ensure_ascii=False)}"
                )

        args_str = ", ".join(args_parts)
        return f"{source_code}\n\n# 自动调用\nrun({args_str})"

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
                value = value.strip("'\"`“”‘’")
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
            match = re.search(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", task, re.I)
            if match:
                return match.group(0)

        if ptype == "url":
            match = re.search(r"https?://[^\s<>\"'“”‘’]+", task)
            if match:
                return re.sub(r"[.,;:。，；：!?！?）)>]+$", "", match.group(0))

        if ptype == "quoted":
            match = re.search(r"['\"“‘](.+?)['\"”’]", task)
            if match:
                return match.group(1).strip()

        if ptype == "keyword":
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
        # 提取关键词（去掉常见的动作词和站点名）
        # 注意：长词必须排在短词前面，否则 "搜索" 中的 "搜" 会先被匹配
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
            return ""

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
    return _instance


def reset_skill_router() -> None:
    """重置全局单例（用于测试）。"""
    global _instance
    _instance = None

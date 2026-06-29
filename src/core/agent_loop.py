"""
Agent 循环引擎 —— 自然语言驱动的自主浏览器操作。

核心逻辑：OBSERVE → PLAN → ACT → OBSERVE ... 循环，
直到任务完成或达到最大步数。

每一步：
1. OBSERVE: 截图 + 分析当前页面状态
2. PLAN:   决定下一步行动（查技能库 or 生成脚本）
3. ACT:    执行脚本，观察结果

失败恢复：
- 脚本执行失败 → 自愈机制（选择器降级）
- 选择器全部失败 → 视觉 fallback（用坐标点击）
- 视觉 fallback 失败 → 记录经验，尝试其他方案

集成:
- 结构化日志: 通过 src.logging 的 get_logger / bind_context / log_timing
- 事件钩子:   通过 src.core.event_bus 的 EventBus 在各生命周期阶段发射事件
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from src.core.browser_manager import get_browser_manager
from src.core.event_bus import (
    EVENT_AGENT_ACT,
    EVENT_AGENT_HEAL,
    EVENT_AGENT_OBSERVE,
    EVENT_AGENT_PLAN,
    EVENT_AGENT_STEP,
    EVENT_AGENT_TASK,
    Event,
    EventBus,
    Phase,
    get_event_bus,
)
from src.core.experience import ExperienceManager, get_experience_manager
from src.core.intent_parser import LLMIntentParser, get_llm_intent_parser
from src.core.script_engine import get_script_engine
from src.core.script_generator import ScriptGenerator
from src.core.vision import VisionModule, get_vision_module
from src.layer_2.controls import get_controls_exports
from src.logging import bind_context, get_logger, log_timing
from src.skill_library.registry import SkillRegistry, get_skill_registry

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# 状态机
# ---------------------------------------------------------------------------


class AgentState(str, Enum):
    """Agent 循环状态。"""

    OBSERVE = "observe"  # 截图 + 分析页面
    PLAN = "plan"  # 决定下一步
    ACT = "act"  # 执行脚本
    DONE = "done"  # 任务完成
    FAILED = "failed"  # 任务失败


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------


@dataclass
class AgentStep:
    """单步执行记录。"""

    step_number: int
    state: AgentState
    action: str = ""
    script: str = ""
    result: str = ""
    success: bool = True
    page_summary: str = ""
    error: str = ""
    timestamp: float = 0.0


@dataclass
class AgentTaskResult:
    """Agent 任务执行结果。"""

    success: bool
    task: str
    steps: list[AgentStep] = field(default_factory=list)
    final_url: str = ""
    output: str = ""
    error: str = ""


# ---------------------------------------------------------------------------
# Agent 循环引擎
# ---------------------------------------------------------------------------


class AgentLoop:
    """自然语言驱动的自主浏览器操作引擎。"""

    def __init__(
        self,
        max_steps: int = 10,
        library_dir: str | None = None,
        on_step: Callable[[AgentStep], None] | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        """初始化 Agent 循环。

        Args:
            max_steps: 最大执行步数。
            library_dir: 技能库目录。
            on_step: 每步回调函数（已废弃，保留向后兼容）。
                     建议使用 event_bus 注册 EVENT_AGENT_STEP 钩子。
            event_bus: EventBus 实例。为 None 时使用全局单例。
        """
        self._max_steps = max_steps
        self._library_dir = library_dir
        self._on_step = on_step
        self._bus = event_bus if event_bus is not None else get_event_bus()

        # 延迟初始化的模块
        self._vision: VisionModule | None = None
        self._registry: SkillRegistry | None = None
        self._script_engine = None
        self._script_generator = ScriptGenerator()
        self._experience: ExperienceManager | None = None
        self._llm_parser: LLMIntentParser | None = None

    def run(self, task: str) -> AgentTaskResult:
        """执行一个自然语言任务。

        Args:
            task: 用户的任务描述，如"帮我在百度搜索 Python 教程"。

        Returns:
            AgentTaskResult 包含执行步骤、结果和输出。
        """
        result = AgentTaskResult(success=False, task=task)
        state = AgentState.OBSERVE
        step_number = 0
        pending_script: str | None = None  # PLAN 阶段生成的脚本，传递给 ACT
        task_id = f"task_{int(time.time() * 1000)}"

        # 绑定任务级上下文，所有后续日志自动携带 task_id / task
        with bind_context(task_id=task_id, task=task):
            logger.info("Agent task started: %s", task)

            # 发射任务开始事件
            self._bus.emit(
                Event(
                    name=EVENT_AGENT_TASK,
                    phase=Phase.BEFORE,
                    data={
                        "task": task,
                        "task_id": task_id,
                        "max_steps": self._max_steps,
                    },
                )
            )

            # 确保浏览器已启动
            bm = get_browser_manager()
            if not bm.is_alive():
                result.error = "浏览器未启动，请先调用 browser_launch"
                logger.error("Agent task aborted: browser not launched")
                self._emit_task_after(result, task_id)
                return result

            # 初始化模块
            self._init_modules()

            with log_timing("agent_task", task=task) as task_meta:
                while state not in (AgentState.DONE, AgentState.FAILED):
                    step_number += 1
                    if step_number > self._max_steps:
                        result.error = f"超过最大步数 ({self._max_steps})"
                        state = AgentState.FAILED
                        logger.warning(
                            "Agent task exceeded max steps (%d)",
                            self._max_steps,
                        )
                        break

                    step = AgentStep(
                        step_number=step_number,
                        state=state,
                        timestamp=time.time(),
                    )

                    try:
                        if state == AgentState.OBSERVE:
                            state = self._do_observe(step)
                        elif state == AgentState.PLAN:
                            state = self._do_plan(step, task)
                            # 将 PLAN 阶段生成的脚本传递给 ACT
                            if step.script:
                                pending_script = step.script
                        elif state == AgentState.ACT:
                            # 使用 PLAN 阶段生成的脚本
                            if pending_script:
                                step.script = pending_script
                                pending_script = None
                            state = self._do_act(step)
                    except Exception as exc:
                        step.success = False
                        step.error = f"{type(exc).__name__}: {exc}"
                        state = AgentState.FAILED
                        logger.error(
                            "Agent step %d unhandled exception: %s",
                            step_number,
                            exc,
                            exc_info=True,
                        )

                    result.steps.append(step)

                    # 发射步事件
                    self._emit_step_event(step, task, task_id)

                    # 向后兼容: 调用 on_step 回调
                    if self._on_step:
                        self._on_step(step)

                task_meta["steps_taken"] = step_number
                task_meta["final_state"] = state.value

            # 汇总结果
            result.success = state == AgentState.DONE
            result.final_url = bm.get_page().url if bm.is_alive() else ""

            if result.steps:
                result.output = "\n".join(
                    f"Step {s.step_number} [{s.state}]: {s.result}"
                    for s in result.steps
                    if s.result
                )

            if not result.success and not result.error:
                result.error = "任务未完成"

            # 发射任务结束事件
            self._emit_task_after(result, task_id)

            logger.info(
                "Agent task finished: success=%s steps=%d",
                result.success,
                len(result.steps),
            )

            return result

    def _init_modules(self) -> None:
        """延迟初始化各模块。"""
        if self._vision is None:
            try:
                self._vision = get_vision_module()
            except (ValueError, ImportError):
                self._vision = None  # 视觉模块不可用时降级

        if self._registry is None:
            self._registry = get_skill_registry(library_dir=self._library_dir)

        if self._script_engine is None:
            self._script_engine = get_script_engine()
            self._script_engine.register_functions(get_controls_exports())

        if self._experience is None:
            self._experience = get_experience_manager()

        if self._llm_parser is None:
            self._llm_parser = get_llm_intent_parser()

    # -------------------------------------------------------------------
    # Event emission helpers
    # -------------------------------------------------------------------

    def _emit_step_event(self, step: AgentStep, task: str, task_id: str) -> None:
        """发射单步事件（EVENT_AGENT_STEP after + 阶段事件）。"""
        self._bus.emit(
            Event(
                name=EVENT_AGENT_STEP,
                phase=Phase.AFTER,
                data={
                    "task": task,
                    "task_id": task_id,
                    "step_number": step.step_number,
                    "state": step.state.value,
                    "action": step.action,
                    "result": step.result,
                    "success": step.success,
                    "error": step.error,
                },
            )
        )

    def _emit_task_after(self, result: AgentTaskResult, task_id: str) -> None:
        """发射任务结束事件。"""
        self._bus.emit(
            Event(
                name=EVENT_AGENT_TASK,
                phase=Phase.AFTER,
                data={
                    "task": result.task,
                    "task_id": task_id,
                    "success": result.success,
                    "steps_count": len(result.steps),
                    "final_url": result.final_url,
                    "error": result.error,
                },
            )
        )

    # -------------------------------------------------------------------
    # OBSERVE: 截图 + 分析页面
    # -------------------------------------------------------------------

    def _do_observe(self, step: AgentStep) -> AgentState:
        """观察当前页面状态。"""
        logger.debug("OBSERVE: observing page state (step %d)", step.step_number)

        before_event = self._bus.emit(
            Event(
                name=EVENT_AGENT_OBSERVE,
                phase=Phase.BEFORE,
                data={"step_number": step.step_number},
            )
        )
        if before_event.cancelled:
            step.result = "observe cancelled by hook"
            logger.info("OBSERVE: cancelled by hook")
            return AgentState.FAILED

        page = get_browser_manager().get_page()

        # 尝试视觉分析
        if self._vision:
            try:
                with log_timing("agent_observe_vision") as meta:
                    analysis = self._vision.analyze_page(
                        question="当前页面是什么？有哪些可操作的元素？"
                    )
                    meta["summary_length"] = len(analysis.summary)
                step.page_summary = analysis.summary
                step.result = f"页面: {analysis.summary[:100]}"
                logger.info(
                    "OBSERVE: vision analysis succeeded (%d chars)",
                    len(analysis.summary),
                )
                self._bus.emit(
                    Event(
                        name=EVENT_AGENT_OBSERVE,
                        phase=Phase.AFTER,
                        data={"step_number": step.step_number, "method": "vision"},
                        result=analysis.summary,
                    )
                )
                return AgentState.PLAN
            except Exception as exc:
                logger.debug(
                    "OBSERVE: vision analysis failed (%s), falling back",
                    exc,
                )

        # 降级：用基础信息
        url = page.url
        title = page.title()
        step.page_summary = f"{title} ({url})"
        step.result = f"页面: {title}"
        logger.info("OBSERVE: fallback to basic info: %s", title)
        self._bus.emit(
            Event(
                name=EVENT_AGENT_OBSERVE,
                phase=Phase.AFTER,
                data={
                    "step_number": step.step_number,
                    "method": "fallback",
                    "url": url,
                    "title": title,
                },
                result=step.page_summary,
            )
        )
        return AgentState.PLAN

    # -------------------------------------------------------------------
    # PLAN: 决定下一步行动
    # -------------------------------------------------------------------

    def _do_plan(self, step: AgentStep, task: str) -> AgentState:
        """根据任务和页面状态，决定下一步。"""
        logger.debug("PLAN: planning action for step %d", step.step_number)

        before_event = self._bus.emit(
            Event(
                name=EVENT_AGENT_PLAN,
                phase=Phase.BEFORE,
                data={
                    "step_number": step.step_number,
                    "task": task,
                    "page_summary": step.page_summary,
                },
            )
        )
        if before_event.cancelled:
            step.result = "plan cancelled by hook"
            logger.info("PLAN: cancelled by hook")
            return AgentState.FAILED

        # 1. 查找匹配的技能
        with log_timing("agent_plan_skill_lookup") as meta:
            skills = self._registry.search(query=task)
            meta["matches"] = len(skills)

        if skills:
            # 检查是否有歧义（多个技能评分打平）
            skill = self._select_best_skill(skills, task)

            # 歧义仲裁：如果 LLM 可用，让它决定用哪个技能
            if (
                self._has_ambiguity(skills, task)
                and self._llm_parser
                and self._llm_parser.available
            ):
                logger.info("PLAN: 技能库歧义 (%d 个候选)，尝试 LLM 仲裁", len(skills))
                resolved = self._resolve_skill_with_llm(task, skills)
                if resolved:
                    skill = resolved

            detail = self._registry.get_detail(skill.id)

            if detail and detail.source_code:
                # 从任务中提取关键词，生成可执行脚本
                script = self._build_skill_script(detail.source_code, task, skill.id)
                if script:
                    step.action = f"使用技能: {skill.name}"
                    step.script = script
                    step.result = f"找到技能: {skill.name}"
                    logger.info("PLAN: matched skill '%s'", skill.name)
                    self._bus.emit(
                        Event(
                            name=EVENT_AGENT_PLAN,
                            phase=Phase.AFTER,
                            data={
                                "step_number": step.step_number,
                                "source": "skill_library",
                                "skill_id": skill.id,
                                "skill_name": skill.name,
                            },
                            result=step.result,
                        )
                    )
                    return AgentState.ACT
                else:
                    logger.info(
                        "PLAN: 技能 '%s' 匹配但关键词提取失败，跳过",
                        skill.name,
                    )

        # 2. 查找已保存的脚本（经验复用）
        saved_script = self._experience.find_script(task)
        if saved_script and saved_script.script:
            step.action = f"复用已保存脚本: {saved_script.id}"
            step.script = saved_script.script
            step.result = f"找到已保存脚本 (成功率: {saved_script.success_rate:.0%})"
            logger.info("PLAN: reusing saved script '%s'", saved_script.id)
            self._bus.emit(
                Event(
                    name=EVENT_AGENT_PLAN,
                    phase=Phase.AFTER,
                    data={
                        "step_number": step.step_number,
                        "source": "experience",
                        "script_id": saved_script.id,
                    },
                    result=step.result,
                )
            )
            return AgentState.ACT

        # 3. 未命中 → 规则生成脚本
        script = self._generate_script(task, step.page_summary)
        if script:
            step.action = "生成临时脚本"
            step.script = script
            step.result = "未命中技能库，生成临时脚本"
            logger.info("PLAN: generated ad-hoc script")
            self._bus.emit(
                Event(
                    name=EVENT_AGENT_PLAN,
                    phase=Phase.AFTER,
                    data={"step_number": step.step_number, "source": "generated"},
                    result=step.result,
                )
            )
            return AgentState.ACT

        # 4. 规则失败 → LLM 兜底
        if self._llm_parser and self._llm_parser.available:
            logger.info("PLAN: 规则未命中，尝试 LLM 意图解析")
            script = self._generate_script_via_llm(task)
            if script:
                step.action = "LLM 意图解析"
                step.script = script
                step.result = "LLM 兜底生成脚本"
                logger.info("PLAN: LLM fallback succeeded")
                self._bus.emit(
                    Event(
                        name=EVENT_AGENT_PLAN,
                        phase=Phase.AFTER,
                        data={
                            "step_number": step.step_number,
                            "source": "llm_fallback",
                        },
                        result=step.result,
                    )
                )
                return AgentState.ACT

        # 5. 无法生成脚本
        step.result = "无法规划行动"
        logger.warning("PLAN: no action could be planned")
        self._bus.emit(
            Event(
                name=EVENT_AGENT_PLAN,
                phase=Phase.AFTER,
                data={"step_number": step.step_number, "source": "none"},
                result=step.result,
            )
        )
        return AgentState.FAILED

    def _generate_script(self, task: str, page_summary: str) -> str | None:
        """根据任务描述生成脚本。

        使用 ScriptGenerator 进行意图解析和脚本生成。
        """
        return self._script_generator.generate(task, page_summary)

    def _build_skill_script(self, source_code: str, task: str, skill_id: str) -> str:
        """将技能源码转换为可执行脚本。

        技能源码通常只定义函数（如 def run(keyword)），需要追加调用语句。
        从任务描述中提取参数，自动调用函数。
        """
        import re

        if skill_id == "domain/gmail_login":
            credentials = self._extract_gmail_credentials(task)
            if not credentials:
                return (
                    f"{source_code}\n\n"
                    "raise ValueError('Gmail login requires email and password')"
                )
            email, password = credentials
            return (
                f"{source_code}\n\n# 自动调用\n"
                f"run({json.dumps(email, ensure_ascii=False)}, "
                f"{json.dumps(password, ensure_ascii=False)})"
            )

        if skill_id == "domain/github_login":
            credentials = self._extract_login_credentials(task)
            if not credentials:
                return (
                    f"{source_code}\n\n"
                    "raise ValueError('GitHub login requires username and password')"
                )
            username, password = credentials
            return (
                f"{source_code}\n\n# 自动调用\n"
                f"run({json.dumps(username, ensure_ascii=False)}, "
                f"{json.dumps(password, ensure_ascii=False)})"
            )

        if skill_id == "domain/bilibili_publish":
            phone_number = self._extract_phone_number(task)
            title, body = self._extract_bilibili_publish_fields(task)
            missing = []
            if not phone_number:
                missing.append("phone number")
            if not title:
                missing.append("title")
            if not body:
                missing.append("body")
            if missing:
                return (
                    f"{source_code}\n\n"
                    f"raise ValueError('Bilibili publish requires {', '.join(missing)}')"
                )
            return (
                f"{source_code}\n\n# 自动调用\n"
                f"run({json.dumps(phone_number, ensure_ascii=False)}, "
                f"{json.dumps(title, ensure_ascii=False)}, "
                f"{json.dumps(body, ensure_ascii=False)})"
            )

        if skill_id == "domain/bilibili_comment":
            phone_number = self._extract_phone_number(task)
            comment_text = self._extract_comment_text(task)
            video_url = self._extract_video_url(task)
            missing = []
            if not phone_number:
                missing.append("phone number")
            if not comment_text:
                missing.append("comment text")
            if missing:
                return (
                    f"{source_code}\n\n"
                    f"raise ValueError('Bilibili comment requires {', '.join(missing)}')"
                )
            if video_url:
                return (
                    f"{source_code}\n\n# 自动调用\n"
                    f"run({json.dumps(phone_number, ensure_ascii=False)}, "
                    f"{json.dumps(comment_text, ensure_ascii=False)}, "
                    f"video_url={json.dumps(video_url, ensure_ascii=False)})"
                )
            return (
                f"{source_code}\n\n# 自动调用\n"
                f"run({json.dumps(phone_number, ensure_ascii=False)}, "
                f"{json.dumps(comment_text, ensure_ascii=False)})"
            )

        phone_login_sites = {
            "domain/xiaohongshu_login": "Xiaohongshu",
            "domain/douyin_login": "Douyin",
            "domain/bilibili_login": "Bilibili",
        }
        if skill_id in phone_login_sites:
            phone_number = self._extract_phone_number(task)
            if not phone_number:
                site_name = phone_login_sites[skill_id]
                return (
                    f"{source_code}\n\n"
                    f"raise ValueError('{site_name} login requires phone number')"
                )
            return (
                f"{source_code}\n\n# 自动调用\n"
                f"run({json.dumps(phone_number, ensure_ascii=False)})"
            )

        # 提取关键词
        keyword = self._script_generator._extract_keyword(task)
        if not keyword:
            # 关键词提取失败，不降级使用整句话（会导致搜索整个指令文本）
            # 返回空字符串让 agent loop 走 LLM 兜底路径
            return ""

        # 检查源码是否已经有独立的 run() 调用（不是 def run 定义）
        # 去掉 def 语句后，检查是否还有 run( 调用
        code_without_defs = re.sub(r"def\s+\w+\s*\([^)]*\)\s*:", "", source_code)
        if "run(" in code_without_defs:
            # 已经有调用语句，直接返回
            return source_code

        # 追加调用语句
        call_script = f"{source_code}\n\n# 自动调用\nrun({json.dumps(keyword, ensure_ascii=False)})"
        return call_script

    @staticmethod
    def _extract_login_credentials(task: str) -> tuple[str, str] | None:
        import re

        def find(patterns: list[str]) -> str | None:
            for pattern in patterns:
                match = re.search(pattern, task, re.IGNORECASE)
                if match:
                    return match.group(1).strip().strip("'\"`")
            return None

        username = find(
            [
                r"(?:用户名|用户|账号|账户|名称|邮箱|username|user|account|email)\s*(?:是|为|:|：|=)?\s*['\"]?([^'\"\s,，;；。]+)",
            ]
        )
        password = find(
            [
                r"(?:密码|口令|password|pass)\s*(?:是|为|:|：|=)?\s*['\"]?([^'\"\s,，;；。]+)",
            ]
        )
        if username and password:
            return username, password
        return None

    @staticmethod
    def _extract_gmail_credentials(task: str) -> tuple[str, str] | None:
        import re

        email_match = re.search(
            r"([A-Z0-9._%+-]+@gmail\.com)",
            task,
            re.IGNORECASE,
        )
        password_match = re.search(
            r"(?:密码|口令|password|pass)[^A-Za-z0-9@]{0,16}([^\s,，;；。)）]+)",
            task,
            re.IGNORECASE,
        )
        if email_match and password_match:
            password = password_match.group(1).strip().strip("'\"`“”‘’()（）")
            return email_match.group(1), password
        return AgentLoop._extract_login_credentials(task)

    @staticmethod
    def _extract_phone_number(task: str) -> str | None:
        import re

        candidates = re.findall(r"(?:\+?86[-\s]*)?1[3-9](?:[-\s]*\d){9}", task)
        for candidate in candidates:
            digits = re.sub(r"\D", "", candidate)
            if digits.startswith("86") and len(digits) == 13:
                digits = digits[2:]
            if re.fullmatch(r"1[3-9]\d{9}", digits):
                return digits
        return None

    @staticmethod
    def _extract_bilibili_publish_fields(task: str) -> tuple[str | None, str | None]:
        import re

        def clean(value: str | None) -> str | None:
            if not value:
                return None
            text = value.strip().strip("'\"`“”‘’").rstrip("，,；;。 \n\r\t")
            return text or None

        title_patterns = [
            r"(?:标题|题目|title)\s*(?:是|为|:|：|=)?\s*['\"“”‘’]?(.*?)(?=(?:正文|内容|文章内容|body|content)\s*(?:是|为|:|：|=)|$)",
        ]
        body_patterns = [
            r"(?:正文|内容|文章内容|body|content)\s*(?:是|为|:|：|=)?\s*['\"“”‘’]?(.+)$",
        ]

        title = None
        for pattern in title_patterns:
            match = re.search(pattern, task, re.IGNORECASE | re.DOTALL)
            if match:
                title = clean(match.group(1))
                break

        body = None
        for pattern in body_patterns:
            match = re.search(pattern, task, re.IGNORECASE | re.DOTALL)
            if match:
                body = clean(match.group(1))
                break

        return title, body

    @staticmethod
    def _extract_comment_text(task: str) -> str | None:
        """从任务描述中提取评论文本。"""
        import re

        def clean(value: str | None) -> str | None:
            if not value:
                return None
            text = value.strip()
            text = text.strip("'\"`“”‘’")
            text = text.rstrip("，,；;。.!！?？ \n\r\t")
            text = text.strip("'\"`“”‘’")
            return text or None

        comment_patterns = [
            r"(?:发布|发表|发送|发)?(?:评论|留言|回复)\s*(?:是|为|:|：|=)?\s*['\"“‘](.+?)['\"”’]",
            r"['\"“‘](.+?)['\"”’]\s*(?:的)?(?:评论|留言|回复)",
            r"(?:评论|留言|回复|说|内容)\s*(?:是|为|:|：|=)?\s*['\"“”‘’]?(.+?)(?=(?:在|然后|并且|接着)|$)",
            r"['\"“”‘’](.+?)['\"“”‘’]\s*(?:的评论|评论|留言)",
            r"发布评论['\"“”‘’]?(.+?)(?:\s|$)",
        ]

        for pattern in comment_patterns:
            match = re.search(pattern, task, re.IGNORECASE | re.DOTALL)
            if match:
                comment = clean(match.group(1))
                if comment and len(comment) >= 1:
                    return comment
        return None

    @staticmethod
    def _extract_video_url(task: str) -> str | None:
        """从任务描述中提取视频URL。"""
        import re

        # 直接匹配 bilibili 视频 URL，保留带点号的查询参数。
        match = re.search(
            r"(https?://(?:www\.)?bilibili\.com/video/[^\s<>\"'“”‘’]+)",
            task,
            re.IGNORECASE,
        )
        if match:
            url = match.group(1)
            return re.sub(r"[.,;:，。；：！!?）)>]+$", "", url)

        # 回退：尝试匹配任何以 BV 开头的视频链接
        match = re.search(r"(https?://[^\s]+/video/BV[A-Za-z0-9]+)", task, re.IGNORECASE)
        if match:
            url = match.group(1)
            # 清理 URL 末尾的标点
            url = re.sub(r"[.,;:，。；：！!?）)>]+$", "", url)
            return url

        return None

    def _select_best_skill(self, skills: list[Any], task: str) -> Any:
        """选择与任务最具体匹配的技能。

        registry 会返回所有触发词命中的技能。这里避免“搜索/search”
        这类宽泛触发词抢走“知乎搜索”“GitHub 搜索”等站点技能。
        """
        task_lower = task.lower()
        broad_triggers = {"搜索", "search", "查找", "find", "找"}

        def score(skill: Any) -> tuple[int, int, int]:
            triggers = getattr(skill, "triggers", []) or []
            matched = [t for t in triggers if t.lower() in task_lower]
            specific = [t for t in matched if t.lower() not in broad_triggers]
            url_patterns = getattr(skill, "url_patterns", []) or []
            return (len(specific), len(matched), len(url_patterns))

        return max(skills, key=score)

    def _skill_score(self, skill: Any, task: str) -> tuple[int, int, int]:
        """计算技能评分（与 _select_best_skill 相同逻辑，供歧义检测复用）。"""
        task_lower = task.lower()
        broad_triggers = {"搜索", "search", "查找", "find", "找"}
        triggers = getattr(skill, "triggers", []) or []
        matched = [t for t in triggers if t.lower() in task_lower]
        specific = [t for t in matched if t.lower() not in broad_triggers]
        url_patterns = getattr(skill, "url_patterns", []) or []
        return (len(specific), len(matched), len(url_patterns))

    def _has_ambiguity(self, skills: list[Any], task: str) -> bool:
        """检查多个候选技能是否评分打平（歧义）。

        当第一名和第二名的专属词数相同时，视为歧义。
        """
        if len(skills) < 2:
            return False
        scored = sorted(skills, key=lambda s: self._skill_score(s, task), reverse=True)
        top1 = self._skill_score(scored[0], task)
        top2 = self._skill_score(scored[1], task)
        # 专属词数相同 → 歧义
        return top1[0] == top2[0]

    def _resolve_skill_with_llm(self, task: str, skills: list[Any]) -> Any | None:
        """用 LLM 仲裁技能歧义。

        让 LLM 从候选技能中选择最匹配的一个，返回选中的技能或 None。
        """
        if not self._llm_parser:
            return None

        candidates = []
        for s in skills:
            name = getattr(s, "name", "")
            sid = getattr(s, "id", "")
            desc = getattr(s, "description", "")
            candidates.append({"id": sid, "name": name, "description": desc})

        # 构造仲裁 prompt（直接调 LLM，不走 intent_parser 的完整流程）
        import json as _json

        candidates_text = _json.dumps(candidates, ensure_ascii=False, indent=2)
        prompt = (
            f"用户指令: {task}\n\n"
            f"候选技能列表:\n{candidates_text}\n\n"
            '请选出最匹配用户指令的技能，返回 JSON: {"skill_id": "选中的技能id", "confidence": 0.9}\n'
            "只返回 JSON，不要其他文字。"
        )

        try:
            raw = self._llm_parser._call_llm(prompt)
            # 提取 JSON
            text = raw.strip()
            if "```" in text:
                start = text.find("{")
                end = text.rfind("}") + 1
                text = text[start:end] if start != -1 and end > 0 else text

            data = _json.loads(text)
            chosen_id = data.get("skill_id", "")
            confidence = data.get("confidence", 0)

            if confidence < 0.5:
                logger.info("LLM 仲裁置信度过低 (%.2f)，使用规则结果", confidence)
                return None

            # 找到对应的技能
            for s in skills:
                if getattr(s, "id", "") == chosen_id:
                    logger.info("LLM 仲裁选择: %s", chosen_id)
                    return s

            logger.warning("LLM 仲裁返回未知技能 ID: %s", chosen_id)
        except Exception as exc:
            logger.warning("LLM 仲裁失败: %s", exc)

        return None

    def _generate_script_via_llm(self, task: str) -> str | None:
        """用 LLM 解析意图，再由 ScriptGenerator 生成脚本。

        流程: LLM → TaskIntent → _intent_to_script()
        """
        if not self._llm_parser:
            return None

        intent = self._llm_parser.parse(task)
        if not intent:
            return None

        # 用 ScriptGenerator 的模板拼装脚本
        return self._script_generator._intent_to_script(intent)

    def _extract_site(self, url: str) -> str:
        """从 URL 中提取站点名称。"""
        from urllib.parse import urlparse

        try:
            hostname = urlparse(url).hostname or ""
            # 去掉 www. 前缀，取第一段
            return hostname.removeprefix("www.").split(".")[0]
        except Exception:
            return ""

    # -------------------------------------------------------------------
    # ACT: 执行脚本
    # -------------------------------------------------------------------

    def _do_act(self, step: AgentStep) -> AgentState:
        """执行脚本。"""
        if not step.script:
            step.result = "无脚本可执行"
            logger.warning("ACT: no script to execute for step %d", step.step_number)
            return AgentState.FAILED

        logger.debug(
            "ACT: executing script for step %d (%d chars)",
            step.step_number,
            len(step.script),
        )

        before_event = self._bus.emit(
            Event(
                name=EVENT_AGENT_ACT,
                phase=Phase.BEFORE,
                data={
                    "step_number": step.step_number,
                    "script": step.script,
                    "action": step.action,
                },
            )
        )
        if before_event.cancelled:
            step.result = "act cancelled by hook"
            logger.info("ACT: cancelled by hook")
            return AgentState.FAILED

        # Allow hooks to modify the script
        script_to_run = before_event.data.get("script", step.script)

        with log_timing("agent_act_execute") as meta:
            result = self._script_engine.execute(script_to_run)
            meta["script_length"] = len(script_to_run)
            meta["success"] = result.success

        if result.success:
            step.success = True
            step.result = "执行成功"
            if result.output:
                step.result += f": {result.output.strip()[:100]}"
            logger.info("ACT: script executed successfully")

            # 保存成功的脚本到经验库
            if self._experience and script_to_run:
                try:
                    page = get_browser_manager().get_page()
                    site = self._extract_site(page.url)
                    self._experience.save_script(
                        task=step.action or "unknown",
                        script=script_to_run,
                        site=site,
                    )
                    logger.debug("ACT: saved script to experience")
                except Exception:
                    pass  # 保存失败不影响主流程

            self._bus.emit(
                Event(
                    name=EVENT_AGENT_ACT,
                    phase=Phase.AFTER,
                    data={
                        "step_number": step.step_number,
                        "action": step.action,
                        "output": result.output,
                    },
                    result=step.result,
                )
            )
            # 任务完成
            return AgentState.DONE
        else:
            step.success = False
            step.error = result.error or "未知错误"
            step.result = f"执行失败: {step.error[:100]}"
            logger.warning("ACT: script failed: %s", step.error[:200])

            self._bus.emit(
                Event(
                    name=EVENT_AGENT_ACT,
                    phase=Phase.AFTER,
                    data={
                        "step_number": step.step_number,
                        "action": step.action,
                        "error": step.error,
                    },
                    error=Exception(step.error),
                )
            )

            # 尝试自愈：如果有选择器错误，可以降级
            if "选择器" in step.error or "selector" in step.error.lower():
                return self._try_heal(step)

            return AgentState.FAILED

    def _try_heal(self, step: AgentStep) -> AgentState:
        """尝试自愈：用视觉 fallback 重试。"""
        if not self._vision:
            logger.warning("HEAL: no vision module available for fallback")
            return AgentState.FAILED

        logger.info(
            "HEAL: attempting vision fallback for step %d",
            step.step_number,
        )

        before_event = self._bus.emit(
            Event(
                name=EVENT_AGENT_HEAL,
                phase=Phase.BEFORE,
                data={
                    "step_number": step.step_number,
                    "original_error": step.error,
                    "method": "vision_fallback",
                },
            )
        )
        if before_event.cancelled:
            logger.info("HEAL: cancelled by hook")
            return AgentState.FAILED

        try:
            # 用视觉分析页面，找到可点击的元素
            with log_timing("agent_heal_vision") as meta:
                analysis = self._vision.analyze_page(
                    question="找到页面上可以点击的按钮或链接"
                )
                meta["elements_found"] = len(analysis.elements)

            if analysis.elements:
                # 用第一个元素生成新脚本
                elem = analysis.elements[0]
                if elem.suggested_selector:
                    step.script = f"""click("{elem.suggested_selector}")
wait_for_navigation()"""
                    step.action = f"视觉 fallback: 点击 {elem.description}"
                    step.result = f"视觉 fallback: 尝试点击 {elem.description}"
                    logger.info(
                        "HEAL: retrying with vision selector '%s' for '%s'",
                        elem.suggested_selector,
                        elem.description,
                    )

                    # 重新执行
                    with log_timing("agent_heal_reexecute") as meta:
                        result = self._script_engine.execute(step.script)
                        meta["success"] = result.success

                    if result.success:
                        step.success = True
                        step.result = f"视觉 fallback 成功: {elem.description}"
                        logger.info("HEAL: vision fallback succeeded")
                        self._bus.emit(
                            Event(
                                name=EVENT_AGENT_HEAL,
                                phase=Phase.AFTER,
                                data={
                                    "step_number": step.step_number,
                                    "method": "vision_fallback",
                                    "healed": True,
                                    "element": elem.description,
                                },
                                result=step.result,
                            )
                        )
                        return AgentState.DONE

            step.result = "视觉 fallback 也失败了"
            logger.warning("HEAL: vision fallback failed — no usable elements")
            self._bus.emit(
                Event(
                    name=EVENT_AGENT_HEAL,
                    phase=Phase.AFTER,
                    data={
                        "step_number": step.step_number,
                        "method": "vision_fallback",
                        "healed": False,
                    },
                    result=step.result,
                )
            )
            return AgentState.FAILED

        except Exception as exc:
            logger.error("HEAL: vision fallback raised: %s", exc, exc_info=True)
            self._bus.emit(
                Event(
                    name=EVENT_AGENT_HEAL,
                    phase=Phase.AFTER,
                    data={
                        "step_number": step.step_number,
                        "method": "vision_fallback",
                        "healed": False,
                    },
                    error=exc,
                )
            )
            return AgentState.FAILED


# ---------------------------------------------------------------------------
# 便捷函数
# ---------------------------------------------------------------------------


def run_task(
    task: str,
    max_steps: int = 10,
    library_dir: str | None = None,
) -> AgentTaskResult:
    """执行一个自然语言任务的便捷函数。

    Args:
        task: 用户的任务描述。
        max_steps: 最大执行步数。
        library_dir: 技能库目录。

    Returns:
        AgentTaskResult。
    """
    from pathlib import Path

    if library_dir is None:
        project_root = Path(__file__).resolve().parent.parent.parent
        library_dir = str(project_root / "src" / "skill_library")

    agent = AgentLoop(max_steps=max_steps, library_dir=library_dir)
    return agent.run(task)

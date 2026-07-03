"""
Agent 循环引擎 —— 自然语言驱动的自主浏览器操作。

核心逻辑：OBSERVE → PLAN → ACT → OBSERVE ... 循环，
直到任务完成或达到最大步数。

每一步：
1. OBSERVE: DOM Explorer 摘要当前页面状态
2. PLAN:   决定下一步行动（查技能库 or 生成脚本）
3. ACT:    执行脚本，观察结果

失败恢复：
- 脚本执行失败 → 自愈机制（选择器降级）
- 选择器全部失败 → 启用视觉 fallback，通过截图分析定位可点击元素
- 视觉 fallback 不可用 → 记录经验，尝试其他方案

集成:
- 结构化日志: 通过 src.logging 的 get_logger / bind_context / log_timing
- 事件钩子:   通过 src.core.event_bus 的 EventBus 在各生命周期阶段发射事件
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from src.core.browser_manager import get_browser_manager
from src.core.dom_explorer import summarize_page
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
from src.core.llm_utils import chat_json_with_retry
from src.core.script_engine import get_script_engine
from src.core.script_generator import ScriptGenerator
from src.core.skill_router import SkillDecision, SkillRouter, get_skill_router
from src.core.task_splitter import TaskSplitter, get_task_splitter
from src.core.vision import get_vision_module
# from src.core.vision import VisionModule, get_vision_module  # 暂时禁用
from src.layer_2.controls import get_controls_exports
from src.logging import bind_context, get_logger, log_timing
from src.skill_library.registry import SkillRegistry, get_skill_registry

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# LLM 调用适配器 —— 让 SkillRouter 复用 LLMIntentParser 的 HTTP 能力
# ---------------------------------------------------------------------------


class _LLMCallerAdapter:
    """将 LLMIntentParser 包装为 SkillRouter 期望的 LLM 调用接口。"""

    def __init__(self, parser: LLMIntentParser) -> None:
        self._parser = parser

    def call(self, prompt: str) -> str:
        return self._parser._client.chat(prompt)

    def call_json(
        self,
        prompt: str,
        schema: dict[str, Any] | None = None,
        system_prompt: str | None = None,
    ) -> dict[str, Any]:
        return chat_json_with_retry(
            self._parser._client,
            prompt,
            system_prompt=system_prompt or "根据用户输入，返回结构化 JSON 结果。",
            schema=schema,
        )


# ---------------------------------------------------------------------------
# 状态机
# ---------------------------------------------------------------------------


class AgentState(str, Enum):
    """Agent 循环状态。"""

    OBSERVE = "observe"  # DOM 摘要 + 分析页面
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
    sub_tasks: list[str] = field(default_factory=list)
    sub_results: list["AgentTaskResult"] = field(default_factory=list)


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
        self._skill_router: SkillRouter | None = None
        self._script_engine = None
        self._script_generator = ScriptGenerator()
        self._experience: ExperienceManager | None = None
        self._llm_parser: LLMIntentParser | None = None
        self._task_splitter: TaskSplitter | None = None

    def run(self, task: str) -> AgentTaskResult:
        """执行一个自然语言任务。

        支持多命令拆分：用户输入用句号分隔的多个命令时，自动拆分并顺序执行。

        Args:
            task: 用户的任务描述，如"帮我在百度搜索 Python 教程"。
                  支持多命令: "打开百度。搜索Python教程。截个图"。

        Returns:
            AgentTaskResult 包含执行步骤、结果和输出。
        """
        # 初始化模块（确保 TaskSplitter 可用）
        self._init_modules()

        # 拆分任务
        sub_tasks = self._task_splitter.split(task)  # type: ignore[union-attr]

        # 单命令 → 走原逻辑（零开销）
        if len(sub_tasks) <= 1:
            return self._run_single(task)

        # 多命令 → 顺序执行
        logger.info("Multi-command detected: %d sub-tasks", len(sub_tasks))
        return self._run_multi(sub_tasks)

    def _run_multi(self, sub_tasks: list[str]) -> AgentTaskResult:
        """顺序执行多个子任务，共享浏览器实例，合并结果。"""
        combined = AgentTaskResult(
            success=True,
            task=" | ".join(sub_tasks),
            sub_tasks=sub_tasks,
        )

        for i, sub_task in enumerate(sub_tasks):
            logger.info("Running sub-task %d/%d: %s", i + 1, len(sub_tasks), sub_task)
            sub_result = self._run_single(sub_task)
            combined.sub_results.append(sub_result)
            combined.steps.extend(sub_result.steps)

            if not sub_result.success:
                combined.success = False
                combined.error = f"子任务 {i + 1}/{len(sub_tasks)} 失败: {sub_task}"
                logger.warning("Sub-task %d failed: %s", i + 1, sub_task)
                break

        # 汇总最终 URL
        try:
            bm = get_browser_manager()
            if bm.is_alive():
                combined.final_url = bm.get_page().url
        except Exception:
            pass

        # 汇总输出
        outputs = []
        for i, sub_result in enumerate(combined.sub_results):
            status = "✓" if sub_result.success else "✗"
            outputs.append(f"[{status}] 子任务 {i + 1}: {sub_tasks[i]}")
            if sub_result.output:
                outputs.append(f"  {sub_result.output}")
        combined.output = "\n".join(outputs)

        logger.info(
            "Multi-command finished: success=%s sub_tasks=%d/%d",
            combined.success,
            sum(1 for r in combined.sub_results if r.success),
            len(sub_tasks),
        )
        return combined

    def _run_single(self, task: str) -> AgentTaskResult:
        """执行单个任务（原始状态机逻辑）。"""
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
            except (ValueError, ImportError) as exc:
                self._vision = None
                logger.warning(
                    "VisionModule unavailable, vision fallback disabled: %s",
                    exc,
                )

        if self._registry is None:
            self._registry = get_skill_registry(library_dir=self._library_dir)

        if self._script_engine is None:
            self._script_engine = get_script_engine()
            self._script_engine.register_functions(get_controls_exports())

        if self._experience is None:
            self._experience = get_experience_manager()

        if self._llm_parser is None:
            self._llm_parser = get_llm_intent_parser()

        if self._skill_router is None:
            llm_adapter = (
                _LLMCallerAdapter(self._llm_parser)
                if self._llm_parser and self._llm_parser.available
                else None
            )
            self._skill_router = get_skill_router(
                library_dir=self._library_dir, llm_caller=llm_adapter
            )

        if self._task_splitter is None:
            llm_caller = (
                _LLMCallerAdapter(self._llm_parser)
                if self._llm_parser and self._llm_parser.available
                else None
            )
            self._task_splitter = get_task_splitter(llm_caller=llm_caller)

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
    # OBSERVE: DOM Explorer + 基础页面信息
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

        try:
            with log_timing("agent_observe_dom") as meta:
                dom_summary = summarize_page(page)
                meta["interactive_count"] = dom_summary.interactive_count
                meta["has_modal"] = dom_summary.has_modal
                meta["has_canvas"] = dom_summary.canvas_count > 0

            step.page_summary = dom_summary.to_text()
            step.result = (
                f"页面: {dom_summary.title or dom_summary.url} "
                f"(可交互元素 {dom_summary.interactive_count} 个)"
            )
            logger.info(
                "OBSERVE: DOM summary collected (%d interactive elements)",
                dom_summary.interactive_count,
            )
            self._bus.emit(
                Event(
                    name=EVENT_AGENT_OBSERVE,
                    phase=Phase.AFTER,
                    data={
                        "step_number": step.step_number,
                        "method": "dom_explorer",
                        "url": dom_summary.url,
                        "title": dom_summary.title,
                        "interactive_count": dom_summary.interactive_count,
                        "has_modal": dom_summary.has_modal,
                        "has_drawer": dom_summary.has_drawer,
                        "has_dropdown": dom_summary.has_dropdown,
                        "canvas_count": dom_summary.canvas_count,
                        "svg_count": dom_summary.svg_count,
                    },
                    result=step.page_summary,
                )
            )
            return AgentState.PLAN
        except Exception as exc:
            logger.debug("OBSERVE: DOM explorer failed (%s), falling back", exc)

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
        """根据任务和页面状态，决定下一步。

        两级降级：
        1. SkillRouter 严格关键词匹配（确定时才命中）
        2. LLM 意图解析 → 从 skills.yaml 找技能脚本
        """
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

        # ── 1. SkillRouter 严格关键词匹配 ──
        with log_timing("agent_plan_skill_router") as meta:
            page_context = {
                "url": get_browser_manager().get_page().url,
                "title": get_browser_manager().get_page().title(),
            }
            decision = self._skill_router.route(task, page_context=page_context)
            meta["source"] = decision.source
            meta["confidence"] = decision.confidence
            meta["skill_id"] = decision.skill.id if decision.skill else None

        if decision.skill and decision.script:
            step.action = f"使用技能: {decision.skill.name}"
            step.script = decision.script
            step.result = (
                f"路由命中: {decision.skill.name} "
                f"(来源: {decision.source}, 置信度: {decision.confidence:.2f})"
            )
            logger.info(
                "PLAN: router matched '%s' via %s (confidence=%.2f)",
                decision.skill.name,
                decision.source,
                decision.confidence,
            )
            self._bus.emit(
                Event(
                    name=EVENT_AGENT_PLAN,
                    phase=Phase.AFTER,
                    data={
                        "step_number": step.step_number,
                        "source": f"skill_router:{decision.source}",
                        "skill_id": decision.skill.id,
                        "skill_name": decision.skill.name,
                        "confidence": decision.confidence,
                    },
                    result=step.result,
                )
            )
            return AgentState.ACT

        # ── 2. LLM 意图解析 → 找技能脚本 ──
        with log_timing("agent_plan_llm_intent") as meta:
            llm_decision = self._find_skill_via_llm(task)
            meta["matched"] = llm_decision is not None and llm_decision.skill is not None

        if llm_decision and llm_decision.skill and llm_decision.script:
            step.action = f"使用技能: {llm_decision.skill.name}"
            step.script = llm_decision.script
            step.result = (
                f"LLM 意图命中: {llm_decision.skill.name} "
                f"(置信度: {llm_decision.confidence:.2f})"
            )
            logger.info(
                "PLAN: LLM intent matched '%s' (confidence=%.2f)",
                llm_decision.skill.name,
                llm_decision.confidence,
            )
            self._bus.emit(
                Event(
                    name=EVENT_AGENT_PLAN,
                    phase=Phase.AFTER,
                    data={
                        "step_number": step.step_number,
                        "source": "llm_intent",
                        "skill_id": llm_decision.skill.id,
                        "skill_name": llm_decision.skill.name,
                        "confidence": llm_decision.confidence,
                    },
                    result=step.result,
                )
            )
            return AgentState.ACT

        # ── 3. 规则生成脚本 ──
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

        # ── 4. 无法规划 ──
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

    def _extract_site(self, url: str) -> str:
        if email_match and password_match:
            password = password_match.group(1).strip().strip("'\"`“”‘’()（）")
            return email_match.group(1), password
        return AgentLoop._extract_login_credentials(task)

    @staticmethod
    def _extract_gmail_send_fields(task: str) -> tuple[str | None, str | None, str | None]:
        import re

        quote_chars = "'\"`“”‘’"

        def clean(value: str | None) -> str | None:
            if not value:
                return None
            text = value.strip().strip(quote_chars)
            text = text.rstrip("，,。.;；!！?？)）\n\r\t ").strip()
            text = text.strip(quote_chars)
            return text or None

        def find_labeled(label_pattern: str, stop_pattern: str | None = None) -> str | None:
            quoted = re.search(
                rf"(?:{label_pattern})\s*(?:是|为|:|：|=)?\s*['\"“‘](.+?)['\"”’]",
                task,
                re.IGNORECASE | re.DOTALL,
            )
            if quoted:
                return clean(quoted.group(1))

            if stop_pattern:
                pattern = (
                    rf"(?:{label_pattern})\s*(?:是|为|:|：|=)?\s*(.+?)"
                    rf"(?=\s*(?:{stop_pattern})\s*(?:是|为|:|：|=)?|$)"
                )
            else:
                pattern = rf"(?:{label_pattern})\s*(?:是|为|:|：|=)?\s*(.+)$"
            match = re.search(pattern, task, re.IGNORECASE | re.DOTALL)
            if match:
                return clean(match.group(1))
            return None

        recipient = None
        recipient_match = re.search(
            r"(?:收件人|收件邮箱|收信人|发送给|发给|寄给|to|recipient)[^A-Z0-9@]{0,16}"
            r"([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})",
            task,
            re.IGNORECASE,
        )
        if recipient_match:
            recipient = recipient_match.group(1).strip()
        else:
            any_email = re.search(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", task, re.IGNORECASE)
            if any_email:
                recipient = any_email.group(0).strip()

        subject = find_labeled(
            r"邮件标题|信件标题|标题|主题|subject|title",
            r"邮件正文|正文内容|正文|邮件内容|内容|body|content",
        )
        body = find_labeled(r"邮件正文|正文内容|正文|邮件内容|内容|body|content")

        return recipient, subject, body

    @staticmethod
    def _extract_gmail_send_account(task: str) -> tuple[str | None, str | None]:
        import re

        sender = None
        sender_match = re.search(
            r"(?:发件邮箱|发件人|发信邮箱|发送邮箱|账号邮箱|邮箱账号|sender|from)[^A-Z0-9@]{0,16}"
            r"([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})",
            task,
            re.IGNORECASE,
        )
        if sender_match:
            sender = sender_match.group(1).strip()

        password = None
        password_match = re.search(
            r"(?:密码|口令|password|pass)[^A-Za-z0-9@]{0,16}([^\s,，;；。)）]+)",
            task,
            re.IGNORECASE,
        )
        if password_match:
            password = password_match.group(1).strip().strip("'\"`“”‘’()（）")

        return sender, password

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
    def _extract_xiaohongshu_publish_content(task: str) -> str | None:
        """从任务描述中提取小红书图文发布内容。"""
        import re

        def clean(value: str | None) -> str | None:
            if not value:
                return None
            text = value.strip()
            text = text.strip("'\"`“”‘’")
            text = re.split(r"\s*(?:然后|并且|接着|最后)\s*", text, maxsplit=1)[0]
            text = re.split(
                r"\s*(?:电话号码|电话|手机号|手机号码|phone)\s*(?:是|为|:|：|=)?\s*",
                text,
                maxsplit=1,
            )[0]
            text = text.rstrip("，,；;。.!！?？ \n\r\t")
            text = text.strip("'\"`“”‘’")
            return text or None

        quoted_patterns = [
            r"(?:图文内容|笔记内容|发布内容|内容|正文|文案|caption|content)\s*(?:是|为|:|：|=)?\s*['\"“‘](.+?)['\"”’]",
            r"(?:发布|发表|生成).{0,12}(?:图文|笔记).{0,16}['\"“‘](.+?)['\"”’]",
        ]
        for pattern in quoted_patterns:
            match = re.search(pattern, task, re.IGNORECASE | re.DOTALL)
            if match:
                content = clean(match.group(1))
                if content:
                    return content

        label_patterns = [
            r"(?:图文内容|笔记内容|发布内容|内容|正文|文案|caption|content)\s*(?:是|为|:|：|=)?\s*['\"“”‘’]?(.+)$",
            r"(?:发布|发表|生成).{0,12}(?:图文|笔记)\s*(?:内容)?\s*(?:是|为|:|：|=)\s*['\"“”‘’]?(.+)$",
        ]
        for pattern in label_patterns:
            match = re.search(pattern, task, re.IGNORECASE | re.DOTALL)
            if match:
                content = clean(match.group(1))
                if content:
                    return content

        return None

    @staticmethod
    def _extract_xiaohongshu_media_path(task: str, kind: str) -> str | None:
        """Extract a local image or video path from a Xiaohongshu publish task."""
        import re

        if kind == "video":
            extensions = r"mp4|mov|avi|mkv|webm|m4v"
            labels = r"视频地址|视频路径|视频|video_path|video|地址|path"
        else:
            extensions = r"jpg|jpeg|png|webp|bmp|gif"
            labels = r"图片地址|图片路径|图片|图像|image_path|image|地址|path"

        quoted_pattern = rf"['\"“”‘’]([^'\"“”‘’]+?\.(?:{extensions}))['\"“”‘’]"
        for match in re.finditer(quoted_pattern, task, re.IGNORECASE):
            value = match.group(1).strip()
            prefix = task[max(0, match.start() - 24) : match.start()]
            if re.search(labels, prefix, re.IGNORECASE) or re.search(
                rf"\.(?:{extensions})$",
                value,
                re.IGNORECASE,
            ):
                return value

        label_pattern = (
            rf"(?:{labels})\s*(?:是|为|:|：|=)?\s*"
            rf"['\"“”‘’]?([A-Za-z]:[\\/][^'\"“”‘’\s，,。；;]+?\.(?:{extensions}))"
        )
        match = re.search(label_pattern, task, re.IGNORECASE)
        if match:
            return match.group(1).strip()

        bare_pattern = rf"([A-Za-z]:[\\/][^'\"“”‘’\s，,。；;]+?\.(?:{extensions}))"
        match = re.search(bare_pattern, task, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return None

    @staticmethod
    def _extract_xiaohongshu_publish_mode(
        task: str,
        image_path: str | None = None,
        video_path: str | None = None,
    ) -> str:
        """Return text_to_image, image_upload, video, or article."""
        import re

        if re.search(r"(文章|长文|小说|article|novel)", task, re.IGNORECASE) and re.search(
            r"(小红书|xiaohongshu|xhs|rednote|上传|写|发布|发表|post|publish|write)",
            task,
            re.IGNORECASE,
        ):
            return "article"
        if video_path or re.search(r"(上传视频|视频地址|视频路径|video)", task, re.IGNORECASE):
            return "video"
        if image_path:
            return "image_upload"
        return "text_to_image"

    @staticmethod
    def _extract_xiaohongshu_publish_fields(task: str) -> tuple[str | None, str | None]:
        """Extract optional title and body/content for Xiaohongshu publishing."""
        import re

        def clean(value: str | None) -> str | None:
            if not value:
                return None
            text = value.strip().strip("'\"`“”‘’")
            text = re.split(
                r"\s*(?:图片地址|图片路径|视频地址|视频路径|地址|电话|电话号码|手机号|手机号码|phone|image_path|video_path)\s*(?:是|为|:|：|=)?",
                text,
                maxsplit=1,
            )[0]
            text = text.rstrip("，,。.;；!！\n\r\t ")
            text = text.strip("'\"`“”‘’")
            return text or None

        title = None
        title_patterns = [
            r"(?:标题|题目|title)\s*(?:是|为|:|：|=)?\s*['\"“‘](.+?)['\"”’]",
            r"(?:标题|题目|title)\s*(?:是|为|:|：|=)?\s*(.+?)(?=(?:正文|内容|文案|图片地址|图片路径|视频地址|视频路径|地址|电话|手机号|$))",
        ]
        for pattern in title_patterns:
            match = re.search(pattern, task, re.IGNORECASE | re.DOTALL)
            if match:
                title = clean(match.group(1))
                if title:
                    break

        body = AgentLoop._extract_xiaohongshu_publish_content(task)
        return title, body

    @staticmethod
    def _extract_xiaohongshu_cover_style(task: str) -> str | None:
        styles = ["基础", "弥散", "涂写", "光影", "手写", "备忘", "边框", "便签", "涂鸦", "简约"]
        for style in styles:
            if style in task:
                return style
        return None

    @staticmethod
    def _extract_xiaohongshu_schedule(task: str) -> tuple[bool, str | None]:
        import re

        enable = bool(re.search(r"(定时发布|定时|预约发布|scheduled)", task, re.IGNORECASE))
        if not enable:
            return False, None

        patterns = [
            r"(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})(?:日)?\s+(\d{1,2})[:：点](\d{1,2})",
            r"(\d{1,2})月(\d{1,2})日?\s*(\d{1,2})[:：点](\d{1,2})",
        ]
        for pattern in patterns:
            match = re.search(pattern, task)
            if not match:
                continue
            groups = match.groups()
            if len(groups) == 5:
                year, month, day, hour, minute = groups
            else:
                from datetime import datetime

                year = str(datetime.now().year)
                month, day, hour, minute = groups
            return True, (
                f"{int(year):04d}-{int(month):02d}-{int(day):02d} "
                f"{int(hour):02d}:{int(minute):02d}"
            )

        return True, None

    @staticmethod
    def _extract_xiaohongshu_note_url(task: str) -> str | None:
        import re

        match = re.search(
            r"(https?://(?:www\.)?xiaohongshu\.com/[A-Za-z0-9:/?#@!$&()*+,;=%._~%-]+)",
            task,
            re.IGNORECASE,
        )
        if not match:
            return None
        url = match.group(1)
        url = re.split(r"(?=下?(?:发布|发表|发送|发)?(?:评论|留言|回复))", url, maxsplit=1)[0]
        url = re.sub(r"[.,;:，。；：！!?）)>]+$", "", url)
        return url or None

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
            r"(?:评论内容|留言内容|回复内容|内容)\s*(?:是|为|:|：|=)?\s*['\"“‘](.+?)['\"”’]",
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
    def _extract_zhihu_publish_content(task: str) -> str | None:
        import re

        def clean(value: str | None) -> str | None:
            if not value:
                return None
            text = value.strip().strip("'\"`“”‘’")
            text = re.sub(r"[，。,.!?！？]$", "", text)
            return text or None

        patterns = [
            r"(?:在|到)?知乎(?:上)?(?:发布|发表|发文章|写文章|投稿)\s*[:：]?\s*(.+)$",
            r"(?:发布|发表|发文章|写文章|投稿)\s*[:：]?\s*(.+)$",
        ]
        for pattern in patterns:
            match = re.search(pattern, task, re.IGNORECASE | re.DOTALL)
            if match:
                content = clean(match.group(1))
                if content:
                    return content
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
        gmail_send_markers = (
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
        if any(marker in task_lower for marker in gmail_send_markers):
            for skill in skills:
                if getattr(skill, "id", "") == "domain/gmail_send":
                    return skill
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

        candidates_text = json.dumps(candidates, ensure_ascii=False, indent=2)
        prompt = (
            f"用户指令: {task}\n\n"
            f"候选技能列表:\n{candidates_text}\n\n"
            "请选出最匹配用户指令的技能。"
        )

        schema = {
            "type": "object",
            "properties": {
                "skill_id": {"type": "string"},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            },
            "required": ["skill_id", "confidence"],
        }

        try:
            data = chat_json_with_retry(
                self._llm_parser._client,
                prompt,
                system_prompt="你是一个技能路由器。从候选技能列表中选出最匹配用户指令的技能。",
                schema=schema,
            )
            chosen_id = data.get("skill_id", "")
            try:
                confidence = float(data.get("confidence", 0) or 0)
            except (TypeError, ValueError):
                logger.warning("LLM 仲裁返回非法 confidence: %s", data.get("confidence"))
                return None

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

    def _find_skill_via_llm(self, task: str) -> SkillDecision | None:
        """用 LLM 理解意图，从 skills.yaml 中匹配技能。

        两步流程：
        1. LLM 根据用户命令从技能名称列表中选出匹配的技能
        2. LLM 根据用户命令修改技能源码，生成可执行脚本

        Returns:
            SkillDecision（含 skill 和 script），或 None。
        """
        if not self._llm_parser or not self._llm_parser.available:
            return None

        # 1. 收集所有技能名称
        all_skills = self._skill_router.list_skills()
        if not all_skills:
            return None

        skill_names = "\n".join(
            f"- {s.id}: {s.name}" for s in all_skills
        )

        # ── Step 1: 匹配技能 ──
        match_prompt = (
            f"用户指令: {task}\n\n"
            f"可用技能:\n{skill_names}\n\n"
            f"选出最匹配的技能，只返回技能 id，不要其他文字。"
        )

        try:
            raw = self._llm_parser._call_llm(match_prompt)
            chosen_id = raw.strip().strip('"').strip("'")

            chosen_skill = self._skill_router.get_skill(chosen_id)
            if not chosen_skill:
                logger.warning("LLM 意图解析返回未知技能 ID: %s", chosen_id)
                return None

            # ── Step 2: 获取源码，让 AI 根据用户命令修改 ──
            source_code = ""
            if chosen_skill.source_file and self._skill_router._library_dir:
                source_path = self._skill_router._library_dir / chosen_skill.source_file
                if source_path.exists():
                    source_code = source_path.read_text(encoding="utf-8")

            if not source_code:
                detail = self._registry.get_detail(chosen_id)
                if detail and detail.source_code:
                    source_code = detail.source_code

            if not source_code:
                logger.warning("LLM 命中技能 '%s' 但无法获取源码", chosen_id)
                return None

            # 检查源码是否已有独立 run() 调用，如果有则直接用
            import re as _re

            code_without_defs = _re.sub(
                r"def\s+\w+\s*\([^)]*\)\s*:", "", source_code
            )
            if "run(" in code_without_defs:
                script = source_code
            else:
                # 让 AI 根据用户命令修改脚本
                modify_prompt = (
                    f"你是一个脚本修改器。根据用户指令，修改下面的 Python 脚本，"
                    f"使其能正确执行用户的请求。\n\n"
                    f"用户指令: {task}\n\n"
                    f"原始脚本:\n```python\n{source_code}\n```\n\n"
                    f"要求:\n"
                    f"1. 保留脚本的核心逻辑不变\n"
                    f"2. 根据用户指令中的具体信息（如关键词、URL、手机号等）"
                    f"填入 run() 函数的参数\n"
                    f"3. 如果用户指令中缺少必要参数，保留原始脚本不变\n"
                    f"4. 只返回修改后的完整 Python 脚本，不要其他文字"
                )

                script = self._llm_parser._call_llm(modify_prompt).strip()

                # 去掉可能的代码块标记
                if script.startswith("```"):
                    lines = script.split("\n")
                    script = "\n".join(lines[1:])
                if script.endswith("```"):
                    script = script[:-3].rstrip()

            logger.info("LLM 意图解析: %s", chosen_id)

            return SkillDecision(
                skill=chosen_skill,
                confidence=1.0,
                reason="LLM 意图解析",
                source="llm",
                script=script,
            )

        except Exception as exc:
            logger.warning("LLM 意图解析失败: %s", exc)
            return None

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
            step.result = "视觉 fallback 不可用（VisionModule 未配置）"
            logger.warning("HEAL: no vision module available for fallback")
            self._emit_heal_after(step, healed=False, result=step.result)
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
            with log_timing("agent_heal_vision") as meta:
                analysis = self._vision.analyze_page(
                    question="找到页面上可以点击的按钮或链接"
                )
                meta["elements_found"] = len(analysis.elements)

            elements = sorted(
                analysis.elements,
                key=lambda item: item.confidence,
                reverse=True,
            )

            for elem in elements:
                description = elem.description or "可点击元素"
                if elem.suggested_selector:
                    selector = elem.suggested_selector
                    heal_script = f"click({json.dumps(selector, ensure_ascii=False)})\nwait(1)"
                    assert self._script_engine is not None
                    heal_result = self._script_engine.execute(heal_script)
                    if heal_result.success:
                        step.success = True
                        step.error = ""
                        step.script = heal_script
                        step.action = f"视觉 fallback: 点击 {description}"
                        step.result = f"视觉 fallback 执行成功: {description}"
                        self._emit_heal_after(step, healed=True, result=step.result)
                        return AgentState.DONE

                    step.error = heal_result.error
                    step.result = (
                        f"视觉 fallback selector 执行失败: {heal_result.error}"
                    )

                if elem.confidence > 0 and elem.width >= 0 and elem.height >= 0:
                    page = get_browser_manager().get_page()
                    click_x = elem.x + max(elem.width, 0) // 2
                    click_y = elem.y + max(elem.height, 0) // 2
                    page.mouse.click(click_x, click_y)
                    step.success = True
                    step.error = ""
                    step.script = ""
                    step.action = f"视觉 fallback: 坐标点击 {description}"
                    step.result = f"视觉 fallback 坐标点击成功: {description}"
                    self._emit_heal_after(step, healed=True, result=step.result)
                    return AgentState.DONE

            step.result = "视觉 fallback 未找到可用元素"
            self._emit_heal_after(step, healed=False, result=step.result)
            return AgentState.FAILED

        except Exception as exc:
            logger.error("HEAL: vision fallback raised: %s", exc, exc_info=True)
            self._emit_heal_after(step, healed=False, error=exc)
            return AgentState.FAILED

    def _emit_heal_after(
        self,
        step: AgentStep,
        *,
        healed: bool,
        result: str | None = None,
        error: Exception | None = None,
    ) -> None:
        """发射自愈阶段的 after 事件。"""
        self._bus.emit(
            Event(
                name=EVENT_AGENT_HEAL,
                phase=Phase.AFTER,
                data={
                    "step_number": step.step_number,
                    "method": "vision_fallback",
                    "healed": healed,
                },
                result=result,
                error=error,
            )
        )


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

"""Explore-mode agent runner.

This module owns ARIA snapshots, Explore action planning/execution, entry-page
bootstrap, and Explore experience persistence. The top-level AgentLoop delegates
to this class instead of carrying script mode and Explore mode in one class.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any
from urllib.parse import urlparse

from src.core.browser_manager import get_browser_manager
from src.core.explore.executor import ExploreExecutor
from src.core.explore.experience import ExperienceManager as ExploreExperienceManager
from src.core.explore.models import (
    Action,
    ActionBatch,
    ActionRecord,
    ElementInfo,
    ExploreConfig,
    ExploreExperience,
    SnapshotMode,
)
from src.core.explore.snapshot import SnapshotGenerator
from src.core.intent_parser import LLMIntentParser
from src.core.llm_utils import chat_json_with_retry
from src.logging import get_logger

logger = get_logger(__name__)


GENERIC_SEARCH_ENGINES: tuple[str, ...] = (
    "baidu.com", "google.com", "bing.com",
    "sogou.com", "360.cn", "yandex.com", "duckduckgo.com",
)

_ENTRYPOINTS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("gmail", "https://mail.google.com/mail/u/0/#inbox", ("gmail", "谷歌邮箱", "google mail")),
    ("github", "https://github.com/", ("github",)),
    ("xiaohongshu", "https://www.xiaohongshu.com/", ("小红书", "xiaohongshu", "rednote")),
    ("zhihu", "https://www.zhihu.com/", ("知乎", "zhihu")),
    ("bilibili", "https://www.bilibili.com/", ("bilibili", "哔哩哔哩", "哔哩", "b站")),
    ("douyin", "https://www.douyin.com/", ("douyin", "抖音")),
    ("baidu", "https://www.baidu.com/", ("baidu", "百度")),
    ("google", "https://www.google.com/", ("google", "谷歌")),
    ("bing", "https://www.bing.com/", ("bing", "必应")),
    ("weibo", "https://weibo.com/", ("weibo", "微博")),
    ("taobao", "https://www.taobao.com/", ("taobao", "淘宝")),
    ("jd", "https://www.jd.com/", ("jd", "京东")),
)

_PLATFORM_ACTION_WORDS = (
    "搜索", "搜", "查找", "查询", "登录", "登陆", "发布", "发送",
    "发", "评论", "留言", "打开", "进入", "问", "提问", "写",
)


class ExploreAgent:
    """Runner for the Explore mode state machine branch."""

    def __init__(
        self,
        llm_parser: LLMIntentParser | None = None,
        config: ExploreConfig | None = None,
        experience_manager: ExploreExperienceManager | None = None,
        browser_manager_getter=None,
    ) -> None:
        self._llm_parser = llm_parser
        self._browser_manager_getter = browser_manager_getter or get_browser_manager
        self._config = config or self.build_config()
        self._snapshot_gen: SnapshotGenerator | None = SnapshotGenerator(self._config)
        self._executor: ExploreExecutor | None = None
        if experience_manager is None:
            from src.config import get_config

            storage_dir = get_config().get("EXPERIENCE_STORAGE_DIR")
            experience_manager = ExploreExperienceManager(storage_dir)
        self._experience_mgr = experience_manager
        self._last_snapshot = None
        self._current_snapshot = None
        self._last_panel_answer: str | None = None
        self._entry_bootstrap_attempted: set[str] = set()
        self.just_navigated_to_entry = False
        self.explore_mode_active = False  # 整个任务生命周期内标记 Explore 模式

        # ── 失败记忆与循环检测 ──
        self._action_history: list[ActionRecord] = []  # 最近 N 步操作记录
        self._max_history: int = 10  # 历史上限
        self._consecutive_same_page: int = 0  # 连续相同页面计数
        self._last_page_signature: str | None = None  # 上一次页面签名
        self._circuit_breakers: dict[str, int] = {}  # 动作类型 → 连续失败次数
        self._blocker_threshold: int = 3  # 连续失败 N 次触发 blocker

    def _get_browser_manager(self):
        return self._browser_manager_getter()

    @staticmethod
    def build_config() -> ExploreConfig:
        from src.config import get_config

        cfg = get_config()
        return ExploreConfig(
            max_retries=int(cfg.get("EXPLORE_MAX_RETRIES", 3)),
            action_timeout=int(cfg.get("EXPLORE_ACTION_TIMEOUT", 15000)),
            snapshot_max_elements=int(cfg.get("EXPLORE_SNAPSHOT_MAX_ELEMENTS", 50)),
            experience_upgrade_threshold=int(cfg.get("EXPERIENCE_UPGRADE_THRESHOLD", 3)),
            experience_confidence_threshold=float(cfg.get("EXPERIENCE_CONFIDENCE_THRESHOLD", 0.8)),
            min_interactive_threshold=int(cfg.get("EXPLORE_MIN_INTERACTIVE_THRESHOLD", 5)),
            deep_scan_max_elements=int(cfg.get("EXPLORE_DEEP_SCAN_MAX_ELEMENTS", 150)),
        )

    @property
    def config(self) -> ExploreConfig:
        return self._config

    @config.setter
    def config(self, value: ExploreConfig) -> None:
        self._config = value
        self._snapshot_gen = SnapshotGenerator(value)
        self._executor = None

    @property
    def experience_manager(self) -> ExploreExperienceManager:
        return self._experience_mgr

    @experience_manager.setter
    def experience_manager(self, value: ExploreExperienceManager) -> None:
        self._experience_mgr = value

    @property
    def current_snapshot(self):
        return self._current_snapshot

    @current_snapshot.setter
    def current_snapshot(self, value) -> None:
        self._current_snapshot = value

    @property
    def snapshot_generator(self):
        return self._snapshot_gen

    @snapshot_generator.setter
    def snapshot_generator(self, value) -> None:
        self._snapshot_gen = value

    @property
    def last_panel_answer(self) -> str | None:
        return self._last_panel_answer

    @property
    def has_pending_snapshot(self) -> bool:
        return self._last_snapshot is not None

    def update_llm_parser(self, parser: LLMIntentParser | None) -> None:
        self._llm_parser = parser

    def reset_task_state(self) -> None:
        self._last_snapshot = None
        self._current_snapshot = None
        self._last_panel_answer = None
        self._entry_bootstrap_attempted = set()
        self.just_navigated_to_entry = False
        self.explore_mode_active = False
        self._action_history = []
        self._consecutive_same_page = 0
        self._last_page_signature = None
        self._circuit_breakers = {}

    # ── 失败记忆与循环检测 ──────────────────────────────────────

    def record_action(self, record: ActionRecord) -> None:
        """追加一条操作记录，维护上限。"""
        self._action_history.append(record)
        if len(self._action_history) > self._max_history:
            self._action_history = self._action_history[-self._max_history:]

    def _build_history_prompt(self) -> str:
        """将最近操作记录格式化为 prompt 片段。"""
        if not self._action_history:
            return ""
        lines = ["最近操作历史（从旧到新）:"]
        for r in self._action_history[-6:]:  # 最多展示最近 6 步
            status = "成功" if r.success else f"失败: {r.error}"
            ref_info = f" ref={r.ref}" if r.ref else ""
            val_info = f" value={r.value}" if r.value else ""
            lines.append(f"  - {r.action}{ref_info}{val_info} → {status}")
        return "\n".join(lines)

    def _compute_page_signature(self, snapshot) -> str:
        """计算页面签名：url + 快照交互元素的 ref 序列。"""
        refs = sorted(
            n.ref for n in self._iter_snapshot_nodes(snapshot.nodes) if n.ref
        )
        return f"{snapshot.url}|{','.join(refs)}"

    def _check_loop_detection(self, snapshot) -> bool:
        """检测是否卡在相同页面。返回 True 表示检测到循环。"""
        sig = self._compute_page_signature(snapshot)
        if sig == self._last_page_signature:
            self._consecutive_same_page += 1
        else:
            self._consecutive_same_page = 0
        self._last_page_signature = sig
        return self._consecutive_same_page >= 2

    def _check_circuit_breaker(self, action_type: str, success: bool) -> bool:
        """更新某动作类型的连续失败计数。返回 True 表示触发熔断。"""
        if success:
            self._circuit_breakers.pop(action_type, None)
            return False
        count = self._circuit_breakers.get(action_type, 0) + 1
        self._circuit_breakers[action_type] = count
        return count >= self._blocker_threshold

    def _get_top_circuit_breaker(self) -> str | None:
        """返回连续失败最多的动作类型（如果超过阈值）。"""
        for action_type, count in self._circuit_breakers.items():
            if count >= self._blocker_threshold:
                return action_type
        return None

    def should_skip_generated_script(self, task: str, script: str) -> bool:
        if not self.should_resolve_entry_with_llm(task):
            return False
        try:
            page_url = self._get_browser_manager().get_page().url
        except Exception:
            page_url = ""
        if not page_url:
            return False
        lowered_script = script.lower()
        has_search_engine_script = any(engine in lowered_script for engine in GENERIC_SEARCH_ENGINES)
        if not has_search_engine_script:
            return False
        if self.is_blank_page(page_url):
            return True
        if any(engine in page_url.lower() for engine in ("bing.com/search", "google.com/search", "baidu.com/s")):
            return True
        if not any(engine in page_url.lower() for engine in GENERIC_SEARCH_ENGINES):
            return True
        return False

    def bootstrap_initial_page(self, task: str) -> str | None:
        bm = self._get_browser_manager()
        page = bm.get_page()
        if not self.is_blank_page(getattr(page, "url", "")):
            return None

        target_url = self.resolve_initial_entry_url(task)
        if target_url:
            return self._goto_initial_entry_url(target_url)

        if self.should_resolve_entry_with_llm(task):
            self._entry_bootstrap_attempted.add(task)
            target_url = self._resolve_initial_entry_url_via_llm(task)
            if target_url:
                return self._goto_initial_entry_url(target_url)
            target_url = self._resolve_entry_url_via_search(task)
            if target_url:
                return self._goto_initial_entry_url(target_url)

        return None

    def bootstrap_entry_page(self, task: str) -> str | None:
        if task in self._entry_bootstrap_attempted:
            return None

        bm = self._get_browser_manager()
        page = bm.get_page()
        if not self.is_blank_page(getattr(page, "url", "")):
            return None

        self._entry_bootstrap_attempted.add(task)
        target_url = self.resolve_initial_entry_url(task)
        if not target_url:
            should_resolve = self.should_resolve_entry_with_llm(task)
            if should_resolve:
                target_url = self._resolve_initial_entry_url_via_llm(task)
            if should_resolve and not target_url:
                target_url = self._resolve_entry_url_via_search(task)
        if not target_url:
            return None
        return self._goto_initial_entry_url(target_url)

    def find_experience(self, task: str, url: str) -> ExploreExperience | None:
        site = self.extract_site(url)
        if not site:
            return None
        return self._experience_mgr.find_similar(task, site)

    def prepare_experience_actions(
        self,
        experience: ExploreExperience,
        executor: ExploreExecutor | None = None,
    ) -> list[Action] | None:
        if not experience.actions:
            return None

        page = self._get_browser_manager().get_page()
        snapshot = self._snapshot_generator().snapshot(page, mode=SnapshotMode.COMPACT)
        self._current_snapshot = snapshot
        active_executor = executor or self.ensure_executor()
        active_executor.update_snapshot(snapshot)

        by_selector: dict[str, str] = {}
        by_role_name: dict[tuple[str, str], str] = {}
        for node in self._iter_snapshot_nodes(snapshot.nodes):
            if not node.ref:
                continue
            if node.selector:
                by_selector[node.selector] = node.ref
            by_role_name[(node.role, node.name)] = node.ref

        remapped: list[Action] = []
        for stored in experience.actions:
            action = Action.model_validate(stored.model_dump(mode="json"))
            if not action.ref:
                remapped.append(action)
                continue

            element = experience.element_map.get(action.ref)
            new_ref = None
            if element:
                new_ref = by_selector.get(element.selector)
                if not new_ref:
                    new_ref = by_role_name.get((element.role, element.name))
            if not new_ref:
                return None

            action.ref = new_ref
            action.snapshot_v = snapshot.version
            remapped.append(action)

        return remapped

    def snapshot(self, step: Any) -> None:
        page = self._get_browser_manager().get_page()
        snapshot = self._snapshot_generator().snapshot(page, mode=SnapshotMode.COMPACT)
        step.snapshot = snapshot
        self._last_snapshot = snapshot
        self._current_snapshot = snapshot
        step.page_summary = json.dumps(snapshot.model_dump(mode="json"), ensure_ascii=False)
        step.result = (
            f"Explore 快照: {snapshot.version} "
            f"(可交互元素 {snapshot.interactive_count} 个)"
        )
        # 输出快照中的交互元素列表，方便调试
        interactive = [
            f"  [{n.ref}] {n.role} \"{n.name}\""
            for n in self._iter_snapshot_nodes(snapshot.nodes)
            if n.ref
        ]
        if interactive:
            logger.info("Explore 快照交互元素:\n%s", "\n".join(interactive))
        self.ensure_executor().update_snapshot(snapshot)

    def plan_actions(self, task: str) -> ActionBatch | None:
        if not self._llm_parser or not self._llm_parser.available:
            return None
        if self._last_snapshot is None:
            return None

        snapshot = self._last_snapshot
        schema = {
            "type": "object",
            "properties": {
                "actions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "action": {
                                "type": "string",
                                "enum": [
                                    "click",
                                    "fill",
                                    "hover",
                                    "select",
                                    "check",
                                    "uncheck",
                                    "goto",
                                    "back",
                                    "forward",
                                    "scroll",
                                    "wait",
                                    "screenshot",
                                    "double_click",
                                    "keyboard",
                                    "drag",
                                    "upload",
                                    "evaluate",
                                    "pause_for_input",
                                    "click_at",
                                    "type",
                                    "dialog",
                                    "request_deep_scan",
                                    "complete",
                                ],
                            },
                            "ref": {"type": ["string", "null"]},
                            "value": {"type": ["string", "null"]},
                            "url": {"type": ["string", "null"]},
                            "direction": {"type": ["string", "null"]},
                            "amount": {"type": ["integer", "null"]},
                            "condition": {
                                "type": ["string", "null"],
                                "enum": ["none", "load", "networkidle", "selector_visible", "text_visible", None],
                            },
                            "timeout": {"type": ["integer", "null"]},
                            "title": {"type": ["string", "null"]},
                            "fields": {"type": ["array", "null"], "items": {"type": "object"}},
                            "snapshot_v": {"type": ["string", "null"]},
                            "intent": {"type": ["string", "null"]},
                            "reasoning": {"type": ["string", "null"]},
                            "x": {"type": ["integer", "null"]},
                            "y": {"type": ["integer", "null"]},
                            "dialog_action": {"type": ["string", "null"]},
                            "delay": {"type": ["integer", "null"]},
                        },
                        "required": ["action"],
                    },
                }
            },
            "required": ["actions"],
        }
        prompt = (
            "你是 Explore 模式浏览器操作规划器。根据用户任务和 ARIA 快照，"
            "输出一个短的原子操作数组。\n\n"
            f"用户任务: {task}\n\n"
            f"当前快照版本: {snapshot.version}\n"
            f"深度扫描: {'是' if snapshot.deep_scanned else '否'}\n"
            f"ARIA 快照:\n{json.dumps(snapshot.model_dump(mode='json'), ensure_ascii=False)}\n\n"
            "规则:\n"
            "2. click/double_click/fill/select/check/uncheck/hover/drag/upload 必须填写 ref。\n"
            "3. fill/select/type/upload 必须填写 value。\n"
            "4. keyboard 的 value 是按键名（Enter, Escape, Tab, Control+a 等）。\n"
            "5. drag 的 ref 是源元素，value 是目标元素的 ref。\n"
            "6. click_at 需要 x, y 视口坐标（用于 canvas 等无 ref 元素）。\n"
            "7. 会导致页面跳转的最后一步请加 condition=load 或 networkidle。\n"
            "8. 每个使用 ref 的动作都填写 snapshot_v 为当前快照版本。\n"
            "9. 不要编造快照里不存在的 ref。\n"
            "10. 如果任务是在当前网站搜索商品/内容，优先找到搜索框，fill 搜索关键词，再 keyboard(Enter) 或 click 搜索按钮。\n"
            "11. 如果任务是在 AI/问答/聊天网站询问问题，优先找到消息输入框，fill 用户问题，再 keyboard(Enter) 或 click 发送按钮。\n"
            "12. 如果刚完成登录或页面发生变化，不要继续使用旧页面假设；等待重新快照后再规划。\n"
            "13. 遇到登录、验证码、人机验证、缺少必要信息或不确定下一步时，"
            "使用 pause_for_input 暂停询问用户。pause_for_input 的 value 是问题文本，"
            "可用 [选项] 提供快捷选择；如需结构化输入可填写 fields。\n"
            "14. pause_for_input 应作为本批次最后一步。\n"
            "15. 每个动作尽量填写 intent（意图）和 reasoning（推理）帮助调试。\n"
            "16. 每个 action 必须是包含 action/ref/value 等字段的对象，"
            "不要用字符串或 null 代替。不需要的字段直接省略，不要填 null 或 \"string\"。\n"
            "17. request_deep_scan 只用于当前页面确实有目标元素但快照没检测到的情况。"
            "如果当前页面还没有导航到目标页面（比如需要先点击链接进入某个页面），"
            "应该先执行导航操作（click 链接/按钮），而不是 request_deep_scan。\n"
            "18. request_deep_scan 应作为本批次唯一动作。深度扫描完成后会重新拍快照，你再基于新快照规划。\n"
            "19. 如果快照已经标记 deep_scanned=true，说明已经深度扫描过，不要再 request_deep_scan。"
            "此时仍找不到目标元素，使用 pause_for_input 问用户。\n"
            "20. 当任务完成时（例如：已经找到并操作了目标元素，或者已经获取到所需信息），"
            "使用 complete 动作结束任务。complete 的 value 可以填写任务完成的摘要。\n"
            "21. complete 应作为本批次最后一步。\n"
            "22. 如果页面显示登录表单、验证码、人机验证等需要人工介入的内容，"
            "且从操作历史中可以看到已经尝试过类似操作但失败了，"
            "必须使用 pause_for_input 暂停并告知用户，不要重复尝试。\n"
        )

        # ── 注入操作历史 ──
        history_prompt = self._build_history_prompt()
        if history_prompt:
            prompt += f"\n{history_prompt}\n"

        # ── 循环检测警告 ──
        if self._check_loop_detection(snapshot):
            prompt += (
                "\n⚠️ 循环检测：当前页面与上一轮完全相同，说明之前的操作没有产生效果。"
                "请换一种策略，不要重复之前的操作。\n"
            )

        # ── 熔断警告 ──
        broken = self._get_top_circuit_breaker()
        if broken:
            count = self._circuit_breakers[broken]
            prompt += (
                f"\n🚨 熔断警告：{broken} 类操作已连续失败 {count} 次。"
                f"不要再尝试 {broken} 操作。如果是登录/验证码等需要人工介入的场景，"
                f"请使用 pause_for_input 告知用户并等待用户手动操作。\n"
            )

        # ── 示例 ──
        prompt += (
            '\n输出格式示例:\n'
            '{"actions": ['
            '{"action": "fill", "ref": "e12", "value": "台风", "snapshot_v": "v1"}, '
            '{"action": "keyboard", "value": "Enter", "condition": "networkidle"}'
            "]}\n"
        )
        if self._last_panel_answer:
            prompt += f"\n\n上一次用户回答: {self._last_panel_answer}"
        try:
            data = chat_json_with_retry(
                self._llm_parser._client,
                prompt,
                system_prompt="只返回 Explore ActionBatch JSON，不要输出解释。",
                schema=schema,
                temperature=0,
                max_tokens=2048,
            )
            data = self.normalize_action_batch_data(data)
            batch = ActionBatch.model_validate(data)
        except Exception as exc:
            logger.warning("Explore planner failed: %s", exc)
            return None

        for action in batch.actions:
            if action.ref and not action.snapshot_v:
                action.snapshot_v = snapshot.version
        self._last_snapshot = None
        return batch

    @staticmethod
    def normalize_action_batch_data(data: Any) -> Any:
        """Accept common LLM shape drift while preserving the ActionBatch contract."""

        if isinstance(data, list):
            return {"actions": data}
        if not isinstance(data, dict):
            return data

        if "actions" in data:
            actions = data.get("actions")
            if isinstance(actions, dict) and "action" in actions:
                normalized = dict(data)
                normalized["actions"] = [actions]
                return normalized
            # 过滤掉 LLM 返回的非字典项（如 "string"、"null" 等 schema 类型名字面量）
            if isinstance(actions, list):
                filtered = [a for a in actions if isinstance(a, dict)]
                if len(filtered) != len(actions):
                    logger.warning(
                        "normalize: filtered %d non-dict action items",
                        len(actions) - len(filtered),
                    )
                normalized = dict(data)
                normalized["actions"] = filtered
                return normalized
            return data

        if "action" in data:
            return {"actions": [data]}

        for key in ("steps", "operations"):
            value = data.get(key)
            if isinstance(value, list):
                return {"actions": value, "task_id": data.get("task_id")}
            if isinstance(value, dict) and "action" in value:
                return {"actions": [value], "task_id": data.get("task_id")}

        return data

    def execute(self, step: Any, executor: ExploreExecutor | None = None) -> str:
        if not step.actions:
            step.result = "无 Explore 操作指令"
            return "failed"

        active_executor = executor or self.ensure_executor()
        result = active_executor.execute(ActionBatch(actions=step.actions))

        # ── 记录操作历史 ──
        step_num = getattr(step, "step_number", 0)
        for action_result in result.results:
            self.record_action(ActionRecord(
                action=str(action_result.action),
                ref=action_result.ref,
                value=action_result.value,
                success=action_result.success,
                error=action_result.error,
                step_number=step_num,
            ))

        if result.success:
            step.success = True
            step.result = f"Explore 执行成功: {result.status}"
            for action_result in result.results:
                if action_result.action in ("panel_prompt", "pause_for_input") and action_result.value is not None:
                    self._last_panel_answer = action_result.value
                    # 遇到登录/验证码时沉淀站点知识
                    self._maybe_record_site_knowledge(action_result.value)
                # 如果执行了 complete 动作，任务完成
                if action_result.action == "complete":
                    self.save_experience(step)
                    return "done"
            self.save_experience(step)
            # 执行成功后，返回 "explore" 让程序继续拍快照、规划下一步操作
            # 只有当任务明确完成时才返回 "done"
            return "explore"

        step.success = False
        step.error = result.error or "Explore 执行失败"
        step.result = f"Explore 执行失败: {step.error[:100]}"

        # ── 更新 circuit breaker ──
        for action in step.actions:
            action_type = str(action.action)
            self._check_circuit_breaker(action_type, success=False)

        # ── 保存失败经验（降级已有经验） ──
        self.save_experience(step, success=False)

        # ── 循环/熔断检测 → 返回 stuck ──
        if self._current_snapshot and self._check_loop_detection(self._current_snapshot):
            logger.warning("Explore: 检测到页面循环，操作无效")
            return "stuck"
        if self._get_top_circuit_breaker():
            broken = self._get_top_circuit_breaker()
            logger.warning("Explore: %s 类操作触发熔断", broken)
            return "stuck"

        return "failed"

    def save_experience(self, step: Any, success: bool = True) -> None:
        if not self._experience_mgr or not step.actions:
            return

        page = self._get_browser_manager().get_page()
        current_url = str(getattr(page, "url", "") or "")
        site = self.extract_site(current_url)
        if not site or self._current_snapshot is None:
            return

        # ── 失败经验：降级已有相似经验 ──
        if not success:
            task = step.task or step.action or "explore task"
            similar = self._experience_mgr.find_similar(task, site)
            if similar:
                self._experience_mgr.update_confidence(similar.id, success=False)
                logger.info("Explore: 降级已有经验 %s (confidence=%.2f)", similar.id, similar.confidence)
            return

        if len(step.actions) < self._config.experience_save_threshold:
            return

        selector_map = self.ensure_executor().get_ref_locator_mapping()
        snapshot_nodes = {
            node.ref: node for node in self._iter_snapshot_nodes(self._current_snapshot.nodes) if node.ref
        }

        element_map: dict[str, ElementInfo] = {}
        for action in step.actions:
            if not action.ref:
                continue
            node = snapshot_nodes.get(action.ref)
            selector = selector_map.get(action.ref) or (node.selector if node else "")
            if not selector:
                continue
            element_map[action.ref] = ElementInfo(
                selector=selector,
                role=node.role if node else "",
                name=node.name if node else "",
                tag=node.tag or "" if node else "",
            )
        if not element_map:
            return

        persisted_actions = []
        for action in step.actions:
            cloned = Action.model_validate(action.model_dump(mode="json"))
            cloned.snapshot_v = None
            persisted_actions.append(cloned)

        task = step.task or step.action or "explore task"
        payload = {
            "task": task,
            "site": site,
            "actions": [a.model_dump(mode="json") for a in persisted_actions],
        }
        digest = hashlib.sha1(
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()[:12]
        experience = ExploreExperience(
            id=f"explore_{site}_{digest}",
            task=task,
            site=site,
            url_pattern=self._url_pattern(current_url),
            actions=persisted_actions,
            action_count=len(persisted_actions),
            element_map=element_map,
            snapshot_roles=[node.role for node in self._iter_snapshot_nodes(self._current_snapshot.nodes)],
            snapshot_names=[node.name for node in self._iter_snapshot_nodes(self._current_snapshot.nodes) if node.name],
        )
        self._experience_mgr.save(experience)

    def _maybe_record_site_knowledge(self, panel_text: str) -> None:
        """如果面板问题涉及登录/验证码等，沉淀站点知识。"""
        keywords = ("登录", "登陆", "验证码", "人机验证", "滑块", "captcha", "login", "verify")
        if not any(kw in panel_text.lower() for kw in keywords):
            return
        try:
            page = self._get_browser_manager().get_page()
            current_url = str(getattr(page, "url", "") or "")
            site = self.extract_site(current_url)
            if not site:
                return
            from src.core.experience import get_experience_manager
            gotcha = panel_text.strip()[:100]
            get_experience_manager().add_knowledge(site, gotcha=gotcha)
            logger.info("Explore: 沉淀站点知识 [%s] %s", site, gotcha)
        except Exception:
            pass

    def ask_user_for_help(self, question: str) -> str | None:
        """直接暂停询问用户，不触发历史记录/循环检测等副作用。

        返回用户的回答文本，如果用户取消则返回 None。
        """
        from src.core.explore.models import Action as ExploreAction, ActionType

        executor = self.ensure_executor()
        action = ExploreAction(action=ActionType.PAUSE_FOR_INPUT, value=question)
        try:
            answer = executor._pause_for_input(action)
            if answer:
                self._last_panel_answer = answer
                return answer
        except Exception as exc:
            logger.warning("Explore: pause_for_input 失败: %s", exc)
        return None

    def ensure_executor(self) -> ExploreExecutor:
        bm = self._get_browser_manager()
        page = bm.get_page()
        if (
            self._executor is None
            or getattr(self._executor, "_page", None) is not page
        ):
            self._executor = ExploreExecutor(
                page,
                self._snapshot_generator(),
                self._config,
                browser_manager=bm,
            )
        return self._executor

    def _snapshot_generator(self) -> SnapshotGenerator:
        if self._snapshot_gen is None:
            self._snapshot_gen = SnapshotGenerator(self._config)
        return self._snapshot_gen

    def _goto_initial_entry_url(self, target_url: str) -> str | None:
        page = self._get_browser_manager().get_page()
        try:
            try:
                page.goto(target_url, wait_until="load")
            except TypeError:
                page.goto(target_url)
        except Exception as exc:
            logger.warning("Explore bootstrap navigation failed: %s", exc)
            return None

        # SPA 页面 load 事件触发后交互元素可能尚未渲染，等待网络空闲
        try:
            page.wait_for_load_state("networkidle", timeout=10_000)
        except Exception:
            logger.debug("networkidle wait timed out, continuing anyway")

        logger.info("Explore bootstrap navigated to %s", target_url)
        self.just_navigated_to_entry = True
        self.explore_mode_active = True  # 标记整个任务进入 Explore 模式
        return target_url

    def _resolve_initial_entry_url_via_llm(self, task: str) -> str | None:
        if not self._llm_parser or not self._llm_parser.available:
            return None

        schema = {
            "type": "object",
            "properties": {
                "should_open": {"type": "boolean"},
                "url": {"type": ["string", "null"]},
                "confidence": {"type": "number"},
                "reason": {"type": "string"},
            },
            "required": ["should_open", "url", "confidence", "reason"],
        }
        prompt = (
            "你是浏览器 Explore 模式的起始网页解析器。当前页面是 about:blank，"
            "技能库和固定规则没有命中。请判断执行用户任务前是否需要先打开某个网页。\n\n"
            f"用户任务: {task}\n\n"
            "要求:\n"
            "1. 如果任务明确提到某个网站、平台、购物网站、AI 对话网站或 Web 服务，返回它的官方入口 URL。\n"
            "2. 购物网站搜索商品时，返回该购物网站主页，不要返回搜索引擎。\n"
            "3. AI 网站询问问题时，优先返回该网站的对话/聊天入口；不知道具体对话入口时返回主页。\n"
            "4. 如果任务是本地软件、微信/WPS/桌面客户端操作，或无法可靠判断网站，should_open=false。\n"
            "5. 不要把未知站点任务转成百度/Google/Bing 搜索；目标是打开相关网站本身。\n"
            "6. 如果只确定域名，也可以返回裸域名，系统会自动补 https://。\n"
            "7. 不要编造不存在的网站；url 必须是相关网站的域名或完整 http/https 地址。\n"
        )
        try:
            data = chat_json_with_retry(
                self._llm_parser._client,
                prompt,
                system_prompt="只返回起始网页判断 JSON，不要输出解释。",
                schema=schema,
                temperature=0,
                max_tokens=1024,
            )
        except Exception as exc:
            logger.warning("Explore entry URL LLM resolution failed: %s", exc)
            return None

        if not data.get("should_open"):
            return None
        try:
            confidence = float(data.get("confidence", 0))
        except (TypeError, ValueError):
            confidence = 0
        if confidence < 0.55:
            return None
        return self.normalize_entry_url(data.get("url"))

    def _resolve_entry_url_via_search(self, task: str) -> str | None:
        if not self._llm_parser or not self._llm_parser.available:
            return None

        site_phrase = self.extract_web_target_phrase(task) or task.strip()[:40]
        search_query = f"{site_phrase} 官网"
        bing_url = f"https://www.bing.com/search?q={search_query}"

        page = self._get_browser_manager().get_page()
        try:
            try:
                page.goto(bing_url, wait_until="domcontentloaded", timeout=15000)
            except TypeError:
                page.goto(bing_url)
            try:
                page.wait_for_timeout(2000)
            except Exception:
                pass
        except Exception as exc:
            logger.warning("Bing search navigation failed: %s", exc)
            return None

        try:
            results = page.evaluate(
                """
                () => {
                    const links = Array.from(document.querySelectorAll('h2 a[href^="http"], .b_algo a[href^="http"]'));
                    return links.slice(0, 8).map(a => ({
                        title: (a.textContent || '').trim().slice(0, 100),
                        url: a.href
                    })).filter(r => r.url && r.title);
                }
                """
            )
        except Exception as exc:
            logger.warning("Bing result extraction failed: %s", exc)
            return None

        if not results or not isinstance(results, list):
            logger.warning("No Bing search results found")
            return None

        lines = []
        for i, r in enumerate(results[:6]):
            lines.append(f"{i + 1}. {r.get('title', '')} - {r.get('url', '')}")
        schema = {
            "type": "object",
            "properties": {
                "best_index": {"type": "integer", "minimum": 1, "maximum": min(len(results), 6)},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "reason": {"type": "string"},
            },
            "required": ["best_index", "confidence", "reason"],
        }
        prompt = (
            f"用户任务: {task}\n\n"
            f"以下是 Bing 搜索 \"{search_query}\" 的结果:\n"
            f"{chr(10).join(lines)}\n\n"
            "请选出最可能是用户要访问的网站。如果搜索结果中没有合适的网站，confidence 设为 0。"
        )

        try:
            data = chat_json_with_retry(
                self._llm_parser._client,
                prompt,
                system_prompt="只返回 JSON，不要输出解释。",
                schema=schema,
                temperature=0,
                max_tokens=1024,
            )
        except Exception as exc:
            logger.warning("LLM search result selection failed: %s", exc)
            return self._first_non_search_result(results)

        try:
            confidence = float(data.get("confidence", 0))
        except (TypeError, ValueError):
            confidence = 0
        if confidence < 0.5:
            return self._first_non_search_result(results)

        best_idx = int(data.get("best_index", 1)) - 1
        if 0 <= best_idx < len(results):
            url = results[best_idx].get("url")
            if url:
                logger.info("Search-based entry resolved: %s", url)
                return self.normalize_entry_url(url)

        return None

    @staticmethod
    def _first_non_search_result(results: list[dict[str, Any]]) -> str | None:
        for result in results[:6]:
            url = result.get("url", "")
            if url and not any(engine in url.lower() for engine in ("bing.com", "google.com", "baidu.com", "sogou.com")):
                logger.info("Search fallback selected: %s", url)
                return ExploreAgent.normalize_entry_url(url)
        return None

    @staticmethod
    def is_blank_page(url: str | None) -> bool:
        value = (url or "").strip().lower()
        return value in {"", "about:blank"} or value.startswith("about:blank?")

    @classmethod
    def resolve_initial_entry_url(cls, task: str) -> str | None:
        explicit_url = cls.extract_first_url(task)
        if explicit_url:
            return explicit_url
        platform = cls.infer_target_platform(task)
        if platform:
            for name, url, _aliases in _ENTRYPOINTS:
                if name == platform:
                    return url
        return None

    @staticmethod
    def extract_first_url(task: str) -> str | None:
        match = re.search(r"https?://[^\s<>'\"，。；、]+", task)
        if not match:
            match = re.search(r"\bwww\.[^\s<>'\"，。；、]+", task, re.IGNORECASE)
        if not match:
            return None
        url = match.group(0).rstrip(").,，。；;、]】\"'")
        if not re.match(r"^https?://", url, re.IGNORECASE):
            url = f"https://{url}"
        return url

    @classmethod
    def infer_target_platform(cls, task: str) -> str | None:
        mentions: list[tuple[int, str]] = []
        action_pattern = "|".join(re.escape(word) for word in _PLATFORM_ACTION_WORDS)
        search_verbs = re.compile(r"(?:搜索|搜|查找|查询|查|找|search|how|怎么|如何|是什么|是什么)", re.IGNORECASE)
        email_platforms = {"gmail", "outlook"}

        for platform, _url, aliases in _ENTRYPOINTS:
            for alias in sorted(aliases, key=len, reverse=True):
                alias_pattern = re.escape(alias)
                patterns = (
                    rf"(?:在|到|用|打开|进入|去)\s*{alias_pattern}(?:上|里|中)?",
                    rf"{alias_pattern}(?:上|里|中)?\s*(?:{action_pattern})",
                )
                for pattern in patterns:
                    for match in re.finditer(pattern, task, re.IGNORECASE):
                        mentions.append((match.start(), platform))

        if mentions:
            best = max(mentions, key=lambda item: item[0])[1]
            if best in email_platforms and search_verbs.search(task):
                return None
            return best

        service_platforms = email_platforms | {"google"}
        has_search_intent = bool(search_verbs.search(task))
        lowered = task.lower()
        for platform, _url, aliases in _ENTRYPOINTS:
            if any(alias.lower() in lowered for alias in aliases):
                if has_search_intent and platform in service_platforms:
                    continue
                return platform
        return None

    @classmethod
    def should_resolve_entry_with_llm(cls, task: str) -> bool:
        if cls.extract_first_url(task) or cls.infer_target_platform(task):
            return False
        return cls.extract_web_target_phrase(task) is not None

    @staticmethod
    def extract_web_target_phrase(task: str) -> str | None:
        actions = (
            r"搜索|搜|查找|查询|查|找|询问|问|提问|登录|登陆|打开|进入|访问|"
            r"search|ask|login|open|visit"
        )
        patterns = (
            rf"(?:在|到|去|打开|进入|用)\s*([^，。,.；;\s]{{2,40}})\s*(?:上|里|中|网站)?\s*(?:{actions})",
            rf"^\s*([^，。,.；;\s]{{2,40}})\s*(?:上|里|中|网站)?\s*(?:{actions})",
        )
        blocked = {
            "帮我", "请帮我", "搜索", "查询", "查找", "打开", "进入", "访问",
            "点击", "按下", "本地", "微信", "wps", "WPS",
        }
        for pattern in patterns:
            match = re.search(pattern, task, re.IGNORECASE)
            if not match:
                continue
            phrase = match.group(1).strip(" “\"'`")
            if phrase and phrase not in blocked:
                return phrase
        return None

    @staticmethod
    def normalize_entry_url(value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        url = value.strip().strip("'\"")
        if not url:
            return None
        if not re.match(r"^https?://", url, re.IGNORECASE):
            url = f"https://{url}"
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return None
        if "." not in parsed.hostname and parsed.hostname not in {"localhost"}:
            return None
        if not parsed.path:
            url = f"{url}/"
        return url

    @staticmethod
    def extract_site(url: str) -> str:
        try:
            hostname = urlparse(url).hostname or ""
            return hostname.removeprefix("www.").split(".")[0]
        except Exception:
            return ""

    @staticmethod
    def _url_pattern(url: str) -> str:
        parsed = urlparse(url)
        if parsed.scheme and parsed.hostname:
            return f"{parsed.scheme}://{parsed.hostname}/*"
        return url

    def _iter_snapshot_nodes(self, nodes: list[Any]):
        for node in nodes:
            yield node
            yield from self._iter_snapshot_nodes(node.children)

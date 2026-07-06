"""Explore experience storage, lookup, and skill upgrade."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

from .models import ActionType, ExploreExperience, Skill


class ExperienceManager:
    """Manage persisted Explore experiences."""

    def __init__(self, storage_dir: str | Path | None = None) -> None:
        self._storage_dir = (
            Path(storage_dir) if storage_dir else Path("data/explore_experiences")
        )
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        self._experiences: dict[str, ExploreExperience] = {}
        self._load_from_disk()

    def save(self, experience: ExploreExperience) -> ExploreExperience:
        """Save a new experience or update a similar one."""

        existing = self.find_similar(experience.task, experience.site)
        if existing:
            existing.success_count += 1
            existing.confidence = min(0.95, existing.confidence + 0.05)
            existing.last_used = datetime.now()
            self._experiences[existing.id] = existing
            self._save_to_disk(existing)
            return existing

        if not experience.action_count:
            experience.action_count = len(experience.actions)
        self._experiences[experience.id] = experience
        self._save_to_disk(experience)
        return experience

    def find_similar(self, task: str, site: str) -> ExploreExperience | None:
        candidates = [
            exp
            for exp in self._experiences.values()
            if exp.site == site and exp.status == "active"
        ]
        for existing in candidates:
            if self._calculate_similarity(task, site, existing) > 0.8:
                return existing
        return None

    def find_by_url(self, url: str) -> list[ExploreExperience]:
        from urllib.parse import urlparse

        hostname = urlparse(url).hostname or ""
        site = hostname.removeprefix("www.").split(".")[0]
        return [
            exp
            for exp in self._experiences.values()
            if exp.site == site and exp.status == "active"
        ]

    def update_confidence(self, experience_id: str, success: bool) -> None:
        exp = self._experiences.get(experience_id)
        if not exp:
            return
        if success:
            exp.success_count += 1
            exp.confidence = min(0.95, exp.confidence + 0.05)
        else:
            exp.fail_count += 1
            exp.confidence = max(0.1, exp.confidence - 0.15)
        exp.last_used = datetime.now()
        if exp.confidence < 0.3:
            exp.status = "deprecated"
        self._experiences[experience_id] = exp
        self._save_to_disk(exp)

    def try_upgrade_to_skill(self, experience_id: str) -> Skill | None:
        exp = self._experiences.get(experience_id)
        if not exp:
            return None
        if exp.success_count < 3 or exp.confidence < 0.8:
            return None
        if exp.fail_count > exp.success_count * 0.2:
            return None

        script = self._generate_script(exp)
        if not script:
            return None

        digest = hashlib.sha1(f"{exp.site}:{exp.task}".encode("utf-8")).hexdigest()[:8]
        return Skill(
            id=f"auto/{exp.site}_{digest}",
            name=exp.task,
            triggers=self._extract_triggers(exp.task),
            url_patterns=[exp.url_pattern] if exp.url_pattern else [],
            source_code=script,
            from_explore=True,
            confidence=exp.confidence,
            auto_generated=True,
        )

    def list_all(self) -> list[ExploreExperience]:
        return list(self._experiences.values())

    def _calculate_similarity(
        self,
        task: str,
        site: str,
        existing: ExploreExperience,
    ) -> float:
        task_sim = self._text_similarity(task, existing.task)
        score = task_sim * 0.4
        if site == existing.site:
            score += 0.3
        max_len = max(len(task), len(existing.task), 1)
        score += (1.0 - abs(len(task) - len(existing.task)) / max_len) * 0.3
        return score

    @staticmethod
    def _text_similarity(a: str, b: str) -> float:
        set_a = set(a)
        set_b = set(b)
        union = len(set_a | set_b)
        if union == 0:
            return 0.0
        return len(set_a & set_b) / union

    def _generate_script(self, exp: ExploreExperience) -> str | None:
        if not exp.actions or not exp.element_map:
            return None

        params = self._extract_params(exp)
        param_str = ", ".join(params)
        lines = [
            f'"""自动从 Explore 经验生成: {exp.task}"""',
            "",
            "from src.layer_1.actions import do_click, do_fill",
            "",
            "",
            f"def run({param_str}):",
            f'    """{exp.task}"""',
        ]

        emitted = False
        for action in exp.actions:
            if not action.ref:
                continue
            element = exp.element_map.get(action.ref)
            if not element:
                continue
            selector = element.selector
            if action.action == ActionType.CLICK:
                lines.append(f"    do_click(page, [{selector!r}])")
                emitted = True
            elif action.action == ActionType.FILL:
                value = action.value or ""
                if self._is_user_input(value, exp.task):
                    param_name = self._guess_param_name(value, exp.task)
                    lines.append(f"    do_fill(page, [{selector!r}], {param_name})")
                else:
                    lines.append(f"    do_fill(page, [{selector!r}], {value!r})")
                emitted = True

        return "\n".join(lines) if emitted else None

    def _extract_params(self, exp: ExploreExperience) -> list[str]:
        params = ["page"]
        for action in exp.actions:
            if action.action == ActionType.FILL and action.value:
                if self._is_user_input(action.value, exp.task):
                    param_name = self._guess_param_name(action.value, exp.task)
                    if param_name not in params:
                        params.append(param_name)
        return params

    @staticmethod
    def _is_user_input(value: str, task: str) -> bool:
        if value and value in task:
            return True
        if re.fullmatch(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", value, re.I):
            return True
        return bool(re.fullmatch(r"1[3-9]\d{9}", value))

    @staticmethod
    def _guess_param_name(value: str, task: str) -> str:
        if "搜索" in task or "search" in task.lower():
            return "keyword"
        if "登录" in task or "login" in task.lower():
            return "username" if "@" in value else "password"
        return "input_value"

    @staticmethod
    def _extract_triggers(task: str) -> list[str]:
        triggers = [task]
        for verb in ("搜索", "登录", "注册", "提交", "点击", "输入", "打开"):
            if verb in task:
                triggers.append(verb)
        return triggers

    def _save_to_disk(self, experience: ExploreExperience) -> None:
        file_path = self._storage_dir / f"{experience.id}.json"
        file_path.write_text(experience.model_dump_json(indent=2), encoding="utf-8")

    def _load_from_disk(self) -> None:
        for file_path in self._storage_dir.glob("*.json"):
            try:
                data = json.loads(file_path.read_text(encoding="utf-8"))
                exp = ExploreExperience.model_validate(data)
            except Exception:
                continue
            self._experiences[exp.id] = exp

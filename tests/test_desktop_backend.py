"""Tests for the desktop pet backend and DOM-free interaction bridge."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from src.core.skill_router import SkillRouter
from src.core.user_interaction import UserInteractionBroker
from src.desktop.api import create_app
from src.desktop.database import DesktopDatabase
from src.desktop.events import DesktopEventHub
from src.desktop.prompts import parse_desktop_prompt
from src.desktop.task_service import ConfirmationWait, DesktopTaskService


class FakeInteractionAdapter:
    def __init__(self) -> None:
        self.logs: list[str] = []
        self.prompts: list[tuple[str, str, list[dict]]] = []

    def log(self, message: str) -> None:
        self.logs.append(message)

    def prompt(self, question: str, *, title: str = "", fields=None):
        self.prompts.append((question, title, fields or []))
        return "approved"

    def read_data(self):
        return {"answer": "approved"}

    def read_events(self):
        return [{"action": "confirmation_resolved"}]


def test_interaction_broker_routes_without_page_dom() -> None:
    broker = UserInteractionBroker()
    adapter = FakeInteractionAdapter()
    broker.attach(adapter)
    broker.set_title("需要确认")
    broker.set_fields([{"name": "comment", "type": "textarea"}])

    broker.log("正在提交")
    answer = broker.prompt("是否继续？")

    assert answer == "approved"
    assert adapter.logs == ["正在提交"]
    assert adapter.prompts == [
        (
            "是否继续？",
            "需要确认",
            [{"name": "comment", "type": "textarea"}],
        )
    ]
    assert broker.read_data() == {"answer": "approved"}


def test_database_persists_history_and_confirmation_is_single_use(tmp_path) -> None:
    database = DesktopDatabase(tmp_path / "desktop.db")
    database.create_conversation("conversation_1", "测试会话")
    message = database.add_message(
        "message_1",
        "conversation_1",
        role="user",
        message_type="user",
        content="执行任务",
    )
    database.create_task("task_1", "conversation_1", message["id"])
    database.create_confirmation(
        "confirm_1", "task_1", "需要确认", "是否提交？"
    )

    assert database.resolve_confirmation("confirm_1", "approved", "继续") is True
    assert database.resolve_confirmation("confirm_1", "rejected", "重复") is False
    assert database.list_messages("conversation_1")[0]["content"] == "执行任务"
    assert database.get_confirmation("confirm_1")["status"] == "approved"

    reopened = DesktopDatabase(tmp_path / "desktop.db")
    assert reopened.get_conversation("conversation_1")["title"] == "测试会话"


def test_desktop_api_requires_token_and_manages_conversations(tmp_path) -> None:
    app = create_app(token="test-token", database_path=tmp_path / "api.db")
    headers = {"Authorization": "Bearer test-token"}
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 401
        assert client.get("/api/health", headers=headers).json()["status"] == "ok"

        created = client.post(
            "/api/conversations",
            headers=headers,
            json={"title": "桌宠测试"},
        )
        assert created.status_code == 200
        conversation_id = created.json()["id"]
        assert client.get("/api/conversations", headers=headers).json()[0]["title"] == "桌宠测试"

        renamed = client.patch(
            f"/api/conversations/{conversation_id}",
            headers=headers,
            json={"title": "已重命名"},
        )
        assert renamed.json() == {"ok": True}
        assert client.get(
            f"/api/conversations/{conversation_id}/messages", headers=headers
        ).json() == []


def test_panel_manager_compatibility_layer_does_not_evaluate_page() -> None:
    from src.panel.panel_manager import PanelManager

    page = MagicMock()
    panel = PanelManager()
    panel.inject(MagicMock())
    panel.toggle(page, True)

    assert panel.is_injected(page) is False
    page.evaluate.assert_not_called()


def test_zhihu_mode_prompt_becomes_structured_choices() -> None:
    prompt = parse_desktop_prompt(
        "知乎文章内容请选择输入方式：[AI生成] [手动输入/确认]"
    )

    assert prompt["prompt_type"] == "choice"
    assert prompt["parameter_name"] == "文章内容"
    assert [option["value"] for option in prompt["options"]] == [
        "AI生成",
        "手动输入/确认",
    ]
    assert "[AI生成]" not in prompt["message"]


def test_missing_and_existing_zhihu_values_get_different_controls() -> None:
    missing = parse_desktop_prompt(
        "请确认技能「知乎发布」的参数「文章标题」。当前值：-1。"
        "如需修改请输入新值，直接回车则沿用当前值："
    )
    existing = parse_desktop_prompt(
        "请确认技能「知乎发布」的参数「文章标题」。当前值：测试标题。"
        "如需修改请输入新值，直接回车则沿用当前值："
    )

    assert missing["prompt_type"] == "input"
    assert missing["input_required"] is True
    assert missing["current_value"] is None
    assert existing["prompt_type"] == "confirm_value"
    assert existing["current_value"] == "测试标题"
    assert [action["id"] for action in existing["actions"]] == ["keep", "replace"]


def test_confirmation_resolution_preserves_selected_option(tmp_path) -> None:
    database = DesktopDatabase(tmp_path / "resolve.db")
    database.create_conversation("conversation_1", "测试")
    database.add_message(
        "message_1",
        "conversation_1",
        role="user",
        message_type="user",
        content="知乎发布图文",
    )
    database.create_task("task_1", "conversation_1", "message_1")
    database.create_confirmation("confirm_1", "task_1", "选择输入方式", "请选择")
    service = DesktopTaskService(database, DesktopEventHub())
    wait = ConfirmationWait()
    service.register_confirmation("confirm_1", wait)

    assert service.resolve_confirmation(
        "confirm_1",
        approved=True,
        value="AI生成",
        action_id="option_0",
    )
    assert wait.resolved is True
    assert wait.value == "AI生成"
    assert wait.action_id == "option_0"
    service.shutdown()


def test_zhihu_prompts_run_before_login_and_browser_actions() -> None:
    library_dir = Path(__file__).resolve().parents[1] / "src" / "skill_library"
    router = SkillRouter(library_dir=library_dir)
    router.load()
    skill = router._skills["domain/zhihu_send"]

    script = router.build_script(skill, "知乎发布图文")

    option_prompt = "是否为知乎文章添加 AI 配图"
    assert option_prompt in script
    generated_auth_index = script.rindex('ensure_auth("zhihu"')
    assert script.index("__param_add_picture =") < generated_auth_index
    assert script.index("panel_prompt('知乎文章内容请选择输入方式") < generated_auth_index


def test_zhihu_picture_question_is_executed_as_prompt_before_auth() -> None:
    library_dir = Path(__file__).resolve().parents[1] / "src" / "skill_library"
    router = SkillRouter(library_dir=library_dir)
    router.load()
    script = router.build_script(router._skills["domain/zhihu_send"], "知乎发布图文")
    prompts: list[str] = []
    answers = iter(
        ["手动输入/确认", "测试正文", "手动输入/确认", "测试标题", "no"]
    )

    def panel_prompt(question: str) -> str:
        prompts.append(question)
        return next(answers)

    def stop_at_auth(*_args) -> None:
        raise RuntimeError("STOP_AFTER_PROMPTS")

    with pytest.raises(RuntimeError, match="STOP_AFTER_PROMPTS"):
        exec(
            script,
            {
                "panel_prompt": panel_prompt,
                "ensure_auth": stop_at_auth,
                "llm_generate_text": lambda _prompt: "unused",
            },
        )

    assert prompts[-1] == "是否为知乎文章添加 AI 配图？当前默认：no。[yes] [no]"
    picture_prompt = parse_desktop_prompt(prompts[-1])
    assert picture_prompt["prompt_type"] == "choice"
    assert [option["label"] for option in picture_prompt["options"]] == [
        "yes",
        "no",
    ]

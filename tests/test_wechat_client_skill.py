"""Tests for WeChat desktop official account skills."""

from __future__ import annotations

from pathlib import Path

from src.core.script_engine import ScriptEngine
from src.core.skill_router import SkillRouter
from src.layer_1.wechat_client import (
    PywinautoWechatAutomation,
    follow_official_account,
    send_contact_message,
    send_official_account_message,
)
from src.skill_library.others.wechat_follow_official_account import (
    run as run_follow,
)
from src.skill_library.send.wechat_send_contact_message import (
    run as run_contact_send,
)
from src.skill_library.send.wechat_send_official_account_message import (
    run as run_send,
)


class FakeWechatAutomation:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []
        self.follow_clicked = True

    def open(self) -> None:
        self.calls.append(("open", None))

    def search_official_account(self, account_name: str) -> None:
        self.calls.append(("search", account_name))

    def search_contact(self, contact_name: str) -> None:
        self.calls.append(("search_contact", contact_name))

    def follow_current_account(self) -> bool:
        self.calls.append(("follow", None))
        return self.follow_clicked

    def send_message(self, message: str) -> None:
        self.calls.append(("send", message))


class FakeRect:
    def __init__(self, width: int = 160, height: int = 36) -> None:
        self._width = width
        self._height = height

    def width(self) -> int:
        return self._width

    def height(self) -> int:
        return self._height


class FakeUiElement:
    def __init__(
        self,
        text: str = "",
        children: list["FakeUiElement"] | None = None,
        process_name: str = "",
        control_type: str = "",
        width: int = 160,
        height: int = 36,
    ) -> None:
        self.text = text
        self.process_name = process_name
        self.control_type = control_type
        self.width = width
        self.height = height
        self.children = children or []
        self.parent_node: FakeUiElement | None = None
        self.clicked = False
        for child in self.children:
            child.parent_node = self

    def window_text(self) -> str:
        return self.text

    def descendants(self, control_type=None):
        result = []
        for child in self.children:
            if control_type is None or child.control_type == control_type:
                result.append(child)
            result.extend(child.descendants(control_type=control_type))
        return result

    def parent(self):
        return self.parent_node

    def rectangle(self):
        return FakeRect(self.width, self.height)

    def click_input(self) -> None:
        self.clicked = True

    def friendly_class_name(self) -> str:
        return self.control_type


class FakeDesktop:
    def __init__(self, windows: list[FakeUiElement]) -> None:
        self._windows = windows

    def windows(self):
        return self._windows


def test_wechat_window_selection_ignores_browser_title_with_wechat_text():
    browser = FakeUiElement("微信网页版 - Chrome", process_name="chrome.exe")
    wechat = FakeUiElement("微信", process_name="WeChat.exe")
    desktop = FakeDesktop([browser, wechat])

    selected = PywinautoWechatAutomation._find_window(desktop)

    assert selected is wechat


def test_wechat_window_selection_returns_none_for_browser_only():
    browser = FakeUiElement("微信网页版 - Chrome", process_name="chrome.exe")
    desktop = FakeDesktop([browser])

    selected = PywinautoWechatAutomation._find_window(desktop)

    assert selected is None


def test_follow_official_account_searches_service_account_and_follows():
    fake = FakeWechatAutomation()

    result = follow_official_account("火眼审阅", automation=fake)

    assert result["success"] is True
    assert result["account_name"] == "火眼审阅"
    assert result["follow_clicked"] is True
    assert fake.calls == [
        ("open", None),
        ("search", "火眼审阅"),
        ("follow", None),
    ]


def test_wechat_clicks_parent_row_when_service_account_type_is_sibling():
    row = FakeUiElement("", [FakeUiElement("火眼审阅"), FakeUiElement("服务号")])
    other_row = FakeUiElement("", [FakeUiElement("火眼审阅"), FakeUiElement("联系人")])
    window = FakeUiElement("", [other_row, row])
    automation = PywinautoWechatAutomation()
    automation.window = window

    automation._click_service_account_result("火眼审阅")

    assert row.clicked is True
    assert other_row.clicked is False


def test_wechat_clicks_contact_row_and_avoids_official_account_result():
    official_row = FakeUiElement("", [FakeUiElement("文件传输助手"), FakeUiElement("公众号")])
    contact_row = FakeUiElement("", [FakeUiElement("文件传输助手")])
    window = FakeUiElement("", [official_row, contact_row])
    automation = PywinautoWechatAutomation()
    automation.window = window

    automation._click_contact_result("文件传输助手")

    assert contact_row.clicked is True
    assert official_row.clicked is False


def test_wechat_contact_search_does_not_click_search_input():
    search_input = FakeUiElement(
        "文件传输助手",
        control_type="Edit",
        width=180,
        height=28,
    )
    search_container = FakeUiElement("搜索", [search_input])
    contact_row = FakeUiElement("", [FakeUiElement("文件传输助手")])
    window = FakeUiElement("", [search_container, contact_row])
    automation = PywinautoWechatAutomation()
    automation.window = window

    automation._click_contact_result("文件传输助手")

    assert search_input.clicked is False
    assert search_container.clicked is False
    assert contact_row.clicked is True


def test_wechat_send_message_uses_chat_input_not_search_input():
    search_input = FakeUiElement(
        "文件传输助手",
        control_type="Edit",
        width=180,
        height=28,
    )
    search_container = FakeUiElement("搜索", [search_input])
    message_edit = FakeUiElement(
        "",
        control_type="Edit",
        width=420,
        height=90,
    )
    window = FakeUiElement("", [search_container, message_edit])
    automation = PywinautoWechatAutomation()
    automation.window = window
    sent_keys: list[str] = []
    automation._paste_or_type = lambda text: sent_keys.append(text)
    automation._send_keys = lambda keys: sent_keys.append(keys)

    automation.send_message("你好")

    assert search_input.clicked is False
    assert message_edit.clicked is True
    assert sent_keys == ["你好", "{ENTER}"]


def test_wechat_switches_to_app_ex_window_after_clicking_service_account_result():
    row = FakeUiElement("", [FakeUiElement("火眼审阅"), FakeUiElement("服务号")])
    main_window = FakeUiElement("微信", [row], process_name="WeChat.exe")
    follow_parent = FakeUiElement("", [FakeUiElement("关注")])
    detail_window = FakeUiElement("", [follow_parent], process_name="WeChatAppEx.exe")
    automation = PywinautoWechatAutomation()
    automation.window = main_window
    automation.desktop = FakeDesktop([main_window, detail_window])

    automation._click_service_account_result("火眼审阅")

    assert row.clicked is True
    assert automation.window is detail_window
    assert automation.follow_current_account() is True
    assert follow_parent.clicked is True


def test_wechat_follow_clicks_parent_for_text_only_follow_control():
    follow_parent = FakeUiElement("", [FakeUiElement("关注")])
    window = FakeUiElement("", [follow_parent])
    automation = PywinautoWechatAutomation()
    automation.window = window

    assert automation.follow_current_account() is True
    assert follow_parent.clicked is True


def test_send_official_account_message_searches_and_sends():
    fake = FakeWechatAutomation()

    result = send_official_account_message(
        "火眼审阅",
        "你好呀",
        automation=fake,
    )

    assert result["success"] is True
    assert result["message"] == "你好呀"
    assert fake.calls == [
        ("open", None),
        ("search", "火眼审阅"),
        ("send", "你好呀"),
    ]


def test_send_contact_message_searches_contact_and_sends():
    fake = FakeWechatAutomation()

    result = send_contact_message(
        "文件传输助手",
        "你好",
        automation=fake,
    )

    assert result["success"] is True
    assert result["contact_name"] == "文件传输助手"
    assert result["message"] == "你好"
    assert fake.calls == [
        ("open", None),
        ("search_contact", "文件传输助手"),
        ("send", "你好"),
    ]


def test_wechat_follow_skill_run_calls_registered_function():
    calls = []

    result = run_follow(
        account_name="火眼审阅",
        log_fn=lambda message: None,
        follow_fn=lambda **kwargs: calls.append(kwargs)
        or {"success": True, "account_name": kwargs.get("account_name")},
    )

    assert result["success"] is True
    assert calls == [
        {
            "account_name": "火眼审阅",
            "message": None,
            "launch_path": None,
        }
    ]


def test_wechat_send_contact_skill_run_calls_registered_function():
    calls = []

    result = run_contact_send(
        contact_name="文件传输助手",
        message="你好",
        log_fn=lambda message: None,
        send_fn=lambda **kwargs: calls.append(kwargs)
        or {"success": True, "contact_name": kwargs.get("contact_name")},
    )

    assert result["success"] is True
    assert calls == [
        {
            "contact_name": "文件传输助手",
            "message": "你好",
            "launch_path": None,
        }
    ]


def test_wechat_send_skill_run_calls_registered_function():
    calls = []

    result = run_send(
        account_name="火眼审阅",
        message="你好呀",
        log_fn=lambda message: None,
        send_fn=lambda **kwargs: calls.append(kwargs)
        or {"success": True, "account_name": kwargs.get("account_name")},
    )

    assert result["success"] is True
    assert calls == [
        {
            "account_name": "火眼审阅",
            "message": "你好呀",
            "launch_path": None,
        }
    ]


def test_wechat_follow_source_runs_inside_script_engine():
    source = Path(
        "src/skill_library/others/wechat_follow_official_account.py"
    ).read_text(encoding="utf-8")
    calls = []
    engine = ScriptEngine()
    engine.register_functions(
        {
            "wechat_follow_official_account": lambda **kwargs: calls.append(kwargs)
            or {"success": True},
            "log": lambda message: None,
        }
    )

    result = engine.execute(source + '\nresult = run(account_name="火眼审阅")\n')

    assert result.success is True
    assert calls[0]["account_name"] == "火眼审阅"


def test_wechat_send_contact_source_runs_inside_script_engine():
    source = Path(
        "src/skill_library/send/wechat_send_contact_message.py"
    ).read_text(encoding="utf-8")
    calls = []
    engine = ScriptEngine()
    engine.register_functions(
        {
            "wechat_send_contact_message": lambda **kwargs: calls.append(kwargs)
            or {"success": True},
            "log": lambda message: None,
        }
    )

    result = engine.execute(
        source + '\nresult = run(contact_name="文件传输助手", message="你好")\n'
    )

    assert result.success is True
    assert calls[0]["contact_name"] == "文件传输助手"
    assert calls[0]["message"] == "你好"


def test_wechat_send_source_runs_inside_script_engine():
    source = Path(
        "src/skill_library/send/wechat_send_official_account_message.py"
    ).read_text(encoding="utf-8")
    calls = []
    engine = ScriptEngine()
    engine.register_functions(
        {
            "wechat_send_official_account_message": lambda **kwargs: calls.append(kwargs)
            or {"success": True},
            "log": lambda message: None,
        }
    )

    result = engine.execute(
        source + '\nresult = run(account_name="火眼审阅", message="你好呀")\n'
    )

    assert result.success is True
    assert calls[0]["account_name"] == "火眼审阅"
    assert calls[0]["message"] == "你好呀"


def test_router_routes_wechat_follow_official_account():
    router = SkillRouter(library_dir="src/skill_library")

    decision = router.route("关注火眼审阅公众号")

    assert decision.skill is not None
    assert decision.skill.id == "domain/wechat_follow_official_account"
    assert 'account_name="火眼审阅"' in decision.script


def test_router_routes_wechat_send_contact_message():
    router = SkillRouter(library_dir="src/skill_library")

    decision = router.route("微信给文件传输助手发送你好")

    assert decision.skill is not None
    assert decision.skill.id == "domain/wechat_send_contact_message"
    assert 'contact_name="文件传输助手"' in decision.script
    assert 'message="你好"' in decision.script


def test_router_routes_wechat_send_official_account_message():
    router = SkillRouter(library_dir="src/skill_library")

    decision = router.route("给火眼审阅公众号发送你好呀")

    assert decision.skill is not None
    assert decision.skill.id == "domain/wechat_send_official_account_message"
    assert 'account_name="火眼审阅"' in decision.script
    assert 'message="你好呀"' in decision.script

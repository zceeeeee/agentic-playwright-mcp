"""Tests for WeChat desktop official account skills."""

from __future__ import annotations

import sys
import tomllib
import types
from pathlib import Path

import pytest

import src.layer_1.wechat_client as wechat_module
from src.core.script_engine import ScriptEngine
from src.core.skill_router import SkillRouter
from src.layer_1.wechat_client import (
    CHAT_INPUT_REL,
    SEARCH_ACCOUNTS_TAB_REL,
    SEARCH_ACCOUNTS_TAB_SETTLE_SECONDS,
    SEARCH_RESULT_WINDOW_DETECT_SECONDS,
    ImageMatch,
    PywinautoWechatAutomation,
    ScreenImageLocator,
    WeChatWindowManager,
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
    def __init__(
        self,
        width: int = 160,
        height: int = 36,
        left: int = 10,
        top: int = 20,
    ) -> None:
        self._width = width
        self._height = height
        self.left = left
        self.top = top

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
        left: int = 10,
        top: int = 20,
    ) -> None:
        self.text = text
        self.process_name = process_name
        self.control_type = control_type
        self.width = width
        self.height = height
        self.left = left
        self.top = top
        self.children = children or []
        self.parent_node: FakeUiElement | None = None
        self.clicked = False
        self.focused = False
        self.moved_to: tuple[int, int, int, int] | None = None
        self.click_coords = None
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
        return FakeRect(self.width, self.height, self.left, self.top)

    def click_input(self, coords=None) -> None:
        self.clicked = True
        self.click_coords = coords

    def set_focus(self) -> None:
        self.focused = True

    def restore(self) -> None:
        pass

    def move_window(self, x, y, width, height, repaint=True) -> None:
        self.moved_to = (x, y, width, height)
        self.left = x
        self.top = y
        self.width = width
        self.height = height

    def friendly_class_name(self) -> str:
        return self.control_type


class FakeDesktop:
    def __init__(self, windows: list[FakeUiElement]) -> None:
        self._windows = windows

    def windows(self):
        return self._windows


class FakeImageLocator:
    def __init__(self, matches: list[object | None] | None = None) -> None:
        self.matches = list(matches or [])
        self.calls: list[tuple[str, object, float]] = []
        self.find_matches: list[object | None] = []
        self.find_calls: list[tuple[str, object, float]] = []
        self.xy_clicks: list[tuple[int, int]] = []
        self.relative_clicks: list[tuple[object, float, float]] = []
        self.green_matches: list[object | None] = []
        self.green_calls: list[object] = []
        self.green_text_matches: list[object | None] = []
        self.green_text_calls: list[tuple[object, str]] = []
        self.first_green_text_matches: list[object | None] = []
        self.first_green_text_calls: list[tuple[object, str]] = []
        self.ocr_matches: list[object | None] = []
        self.ocr_calls: list[tuple[object, str]] = []
        self.ocr_find_matches: list[object | None] = []
        self.ocr_find_calls: list[tuple[object, str]] = []
        self.moment_author_matches: list[object | None] = []
        self.moment_author_calls: list[tuple[object, str]] = []
        self.moment_action_matches: list[object | None] = []
        self.moment_action_calls: list[object] = []
        self.moment_menu_matches: list[object | None] = []
        self.moment_menu_calls: list[object] = []
        self.moment_states: list[str | None] = []
        self.moment_state_calls: list[object] = []

    def click(self, template_name, *, region=None, threshold=0.0):
        self.calls.append((template_name, region, threshold))
        if self.matches:
            return self.matches.pop(0)
        return None

    def find(self, template_name, *, region=None, threshold=0.0):
        self.find_calls.append((template_name, region, threshold))
        if self.find_matches:
            return self.find_matches.pop(0)
        return None

    def click_xy(self, x, y):
        self.xy_clicks.append((x, y))

    def click_relative(self, region, rx, ry):
        self.relative_clicks.append((region, rx, ry))
        left, top, width, height = region
        self.xy_clicks.append((left + int(width * rx), top + int(height * ry)))
        return True

    def click_green_button(self, *, region=None, min_area=900):
        self.green_calls.append(region)
        if self.green_matches:
            return self.green_matches.pop(0)
        return None

    def click_green_text(self, *, region=None, text=""):
        self.green_text_calls.append((region, text))
        if self.green_text_matches:
            return self.green_text_matches.pop(0)
        return None

    def click_first_result_green_text(self, *, region=None, text=""):
        self.first_green_text_calls.append((region, text))
        if self.first_green_text_matches:
            return self.first_green_text_matches.pop(0)
        return self.click_green_text(region=region, text=text)

    def click_ocr_text(self, *, region=None, text=""):
        self.ocr_calls.append((region, text))
        if self.ocr_matches:
            return self.ocr_matches.pop(0)
        return None

    def find_ocr_text(self, *, region=None, text=""):
        self.ocr_find_calls.append((region, text))
        if self.ocr_find_matches:
            return self.ocr_find_matches.pop(0)
        return None

    def find_moment_author(self, *, region=None, text=""):
        self.moment_author_calls.append((region, text))
        if self.moment_author_matches:
            return self.moment_author_matches.pop(0)
        return None

    def find_first_moment_action(self, *, region=None):
        self.moment_action_calls.append(region)
        if self.moment_action_matches:
            return self.moment_action_matches.pop(0)
        return None

    def find_moment_like_menu(self, *, region=None):
        self.moment_menu_calls.append(region)
        if self.moment_menu_matches:
            return self.moment_menu_matches.pop(0)
        return None

    def find_moment_like_state(self, *, region=None):
        self.moment_state_calls.append(region)
        if self.moment_states:
            return self.moment_states.pop(0)
        return None


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


def test_wechat_window_manager_normalizes_window_size():
    win = FakeUiElement("微信", process_name="WeChat.exe")
    manager = WeChatWindowManager(
        FakeDesktop([win]),
        window_rect_provider=lambda app_ex=False: (0, 0, 960, 1040),
    )

    result = manager.normalize(win)

    assert result is win
    assert win.focused is True
    assert win.moved_to == (0, 0, 960, 1040)


def test_wechat_window_manager_normalizes_appex_to_left_half():
    win = FakeUiElement("火眼审阅", process_name="WeChatAppEx.exe")
    manager = WeChatWindowManager(
        FakeDesktop([win]),
        window_rect_provider=lambda app_ex=False: (0, 0, 960, 1040),
    )

    result = manager.normalize(win, app_ex=True)

    assert result is win
    assert win.focused is True
    assert win.moved_to == (0, 0, 960, 1040)


def test_wechat_window_manager_prefers_win32_set_window_pos(monkeypatch):
    calls = []
    win = FakeUiElement("微信", process_name="WeChat.exe")
    manager = WeChatWindowManager(
        FakeDesktop([win]),
        window_rect_provider=lambda app_ex=False: (0, 0, 960, 1040),
    )

    def fake_set_window_pos(window, x, y, width, height):
        calls.append((window, x, y, width, height))
        return True

    monkeypatch.setattr(
        WeChatWindowManager,
        "_set_window_pos",
        staticmethod(fake_set_window_pos),
    )

    result = manager.normalize(win)

    assert result is win
    assert calls == [(win, 0, 0, 960, 1040)]
    assert win.moved_to is None
    assert win.focused is True


def test_wechat_window_manager_normalizes_all_wechat_windows():
    main_window = FakeUiElement("微信", process_name="WeChat.exe")
    app_ex_window = FakeUiElement("火眼审阅", process_name="WeChatAppEx.exe")
    manager = WeChatWindowManager(
        FakeDesktop([main_window, app_ex_window]),
        window_rect_provider=lambda app_ex=False: (0, 0, 960, 1040),
    )

    manager.normalize_all(active_window=main_window)

    assert main_window.moved_to == (0, 0, 960, 1040)
    assert app_ex_window.moved_to == (0, 0, 960, 1040)
    assert main_window.focused is True
    assert app_ex_window.focused is False


def test_wechat_window_manager_moves_new_appex_as_soon_as_detected():
    main_window = FakeUiElement("微信", process_name="WeChat.exe")
    app_ex_window = FakeUiElement("火眼审阅", process_name="WeChatAppEx.exe")
    manager = WeChatWindowManager(
        FakeDesktop([main_window, app_ex_window]),
        window_rect_provider=lambda app_ex=False: (0, 0, 960, 1040),
    )
    before = {PywinautoWechatAutomation._window_handle(main_window)}

    result = manager.latest_new_appex(before, title_hint="火眼审阅", timeout=0.1)

    assert result is app_ex_window
    assert app_ex_window.moved_to == (0, 0, 960, 1040)
    assert app_ex_window.focused is False


def test_wechat_window_manager_logs_move_failures(caplog):
    class FailingMoveWindow(FakeUiElement):
        def move_window(self, x, y, width, height, repaint=True) -> None:
            raise RuntimeError("move blocked")

    win = FailingMoveWindow("微信", process_name="WeChat.exe")
    manager = WeChatWindowManager(
        FakeDesktop([win]),
        window_rect_provider=lambda app_ex=False: (0, 0, 960, 1040),
    )

    with caplog.at_level("WARNING", logger=wechat_module.__name__):
        manager.normalize(win)

    assert "Failed to move WeChat window to left half" in caplog.text
    assert "move blocked" in caplog.text


def test_wechat_screen_locator_taskbar_region_uses_bottom_screen_area():
    assert ScreenImageLocator.taskbar_region_for_size(1920, 1080) == (
        0,
        777,
        1920,
        303,
    )


def test_wechat_screen_locator_captures_window_region_directly():
    class RecordingLocator(ScreenImageLocator):
        def __init__(self) -> None:
            super().__init__(pic_dir=".")
            self.screenshot_regions = []

        def _screenshot_array(self, region=None):
            self.screenshot_regions.append(region)
            return object()

    locator = RecordingLocator()

    capture = locator._capture_region((10, 20, 300, 400))

    assert capture is not None
    assert capture[1:] == (10, 20)
    assert locator.screenshot_regions == [(10, 20, 300, 400)]


def test_wechat_screen_locator_clicks_green_text_inside_first_result_card():
    import cv2
    import numpy as np

    image = np.full((445, 1081, 3), 15, dtype=np.uint8)
    image[0:34, :] = (25, 25, 25)
    image[57:291, 47:1034] = (21, 21, 21)
    image[304:444, 47:1034] = (21, 21, 21)
    green = (42, 224, 126)
    cv2.putText(image, "Huoyan Account", (67, 108), cv2.FONT_HERSHEY_SIMPLEX, 0.9, green, 2)
    cv2.putText(image, "Huoyan", (181, 190), cv2.FONT_HERSHEY_SIMPLEX, 0.9, green, 2)
    cv2.putText(image, "Huoyan desc", (181, 263), cv2.FONT_HERSHEY_SIMPLEX, 0.55, green, 1)

    class SyntheticLocator(ScreenImageLocator):
        def _capture_region(self, region=None):
            return image, 0, 0

    match = SyntheticLocator().find_first_result_green_text(text="火眼审阅")

    assert match is not None
    assert match.template_name == "first_result_green_text:火眼审阅"
    assert match.x > 180
    assert 160 <= match.y <= 210


def test_wechat_screen_locator_finds_green_rectangle_button():
    import cv2
    import numpy as np

    image = np.full((220, 420, 3), 18, dtype=np.uint8)
    cv2.rectangle(image, (20, 30), (330, 62), (7, 193, 96), thickness=-1)
    cv2.rectangle(image, (140, 100), (280, 152), (85, 188, 122), thickness=-1)
    cv2.putText(
        image,
        "follow",
        (175, 133),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (255, 255, 255),
        2,
    )

    class SyntheticLocator(ScreenImageLocator):
        def _capture_region(self, region=None):
            return image, 0, 0

    match = SyntheticLocator().find_green_button()

    assert match is not None
    assert match.template_name == "green_button"
    assert 185 <= match.x <= 235
    assert 115 <= match.y <= 145


def test_wechat_moment_author_locator_uses_ocr(monkeypatch):
    locator = ScreenImageLocator()
    expected = ImageMatch(320, 240, 1.0, "ocr_text:张三")
    calls = []

    def find_ocr_text(*, region=None, text=""):
        calls.append((region, text))
        return expected

    monkeypatch.setattr(locator, "find_ocr_text", find_ocr_text)

    match = locator.find_moment_author(
        text="张三",
        region=(100, 50, 600, 800),
    )

    assert match == ImageMatch(320, 240, 1.0, "moment_author:张三")
    assert calls == [((100, 50, 600, 800), "张三")]


def test_wechat_ocr_uses_windows_ocr_when_tesseract_is_unavailable(
    monkeypatch,
):
    np = pytest.importorskip("numpy")
    from src.core.ocr import OcrResult, OcrWord

    image = np.full((100, 200, 3), 255, dtype=np.uint8)
    locator = ScreenImageLocator()
    calls = []

    class FakeWindowsOcr:
        async def recognize(
            self,
            screenshot_bytes,
            viewport_width=0,
            viewport_height=0,
        ):
            calls.append(
                (
                    bool(screenshot_bytes),
                    viewport_width,
                    viewport_height,
                )
            )
            return OcrResult(
                words=[
                    OcrWord(
                        text="瑞幸首席官",
                        x=0.2,
                        y=0.3,
                        width=0.4,
                        height=0.1,
                    )
                ],
                viewport_width=viewport_width,
                viewport_height=viewport_height,
            )

    monkeypatch.setattr(locator, "_load_pytesseract", lambda: None)
    monkeypatch.setattr(
        locator,
        "_capture_region",
        lambda _region: (image, 100, 50),
    )
    monkeypatch.setattr(
        "src.core.ocr.get_ocr_module",
        lambda language="zh-CN": FakeWindowsOcr(),
    )

    match = locator.find_ocr_text(
        region=(100, 50, 200, 100),
        text="瑞幸首席官",
    )

    assert match == ImageMatch(
        180,
        85,
        1.0,
        "windows_ocr_text:瑞幸首席官",
    )
    assert calls == [(True, 200, 100)]


def test_windows_ocr_runtime_is_installed_with_default_dependencies():
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    dependencies = project["project"]["dependencies"]

    assert any(
        dependency.startswith("winrt-Windows.Media.Ocr")
        for dependency in dependencies
    )


def test_wechat_moment_action_locator_uses_template_and_returns_topmost(
    monkeypatch,
):
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    template = cv2.imdecode(
        np.frombuffer(Path("pic/beforeLike.png").read_bytes(), dtype=np.uint8),
        cv2.IMREAD_COLOR,
    )
    template = cv2.cvtColor(template, cv2.COLOR_BGR2RGB)
    template_h, template_w = template.shape[:2]
    image = np.full((800, 1200, 3), 20, dtype=np.uint8)
    target_left = 1000 - template_w // 2
    image[500 : 500 + template_h, target_left : target_left + template_w] = template
    image[220 : 220 + template_h, target_left : target_left + template_w] = template

    locator = ScreenImageLocator()
    monkeypatch.setattr(
        locator,
        "_capture_region",
        lambda _region: (image, 0, 0),
    )

    match = locator.find_first_moment_action(region=(0, 0, 1200, 800))

    assert match is not None
    assert match.template_name == "beforeLike.png"
    assert abs(match.x - 1000) <= 2
    assert abs(match.y - (220 + template_h // 2)) <= 2


def test_wechat_moment_like_menu_uses_like_template(monkeypatch):
    locator = ScreenImageLocator()
    expected = ImageMatch(850, 744, 0.95, "like.png")
    calls = []

    def find(template_name, *, region=None, threshold=0.0):
        calls.append((template_name, region, threshold))
        return expected

    monkeypatch.setattr(locator, "find", find)

    match = locator.find_moment_like_menu(region=(0, 680, 1200, 140))

    assert match == expected
    assert calls == [("like.png", (0, 680, 1200, 140), 0.8)]


@pytest.mark.parametrize(
    ("visible_label", "expected"),
    [("取消", "already_liked"), ("赞", "can_like")],
)
def test_wechat_moment_like_state_uses_menu_text(
    monkeypatch,
    visible_label,
    expected,
):
    locator = ScreenImageLocator()

    def find_ocr_text(*, region=None, text=""):
        if text == visible_label:
            return ImageMatch(400, 500, 1.0, f"ocr_text:{text}")
        return None

    monkeypatch.setattr(locator, "find_ocr_text", find_ocr_text)

    assert (
        locator.find_moment_like_state(region=(100, 50, 500, 600))
        == expected
    )


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


def test_wechat_opens_independent_moments_window(monkeypatch):
    monkeypatch.setattr(wechat_module.time, "sleep", lambda _seconds: None)
    entry = FakeUiElement("朋友圈", control_type="Button")
    main = FakeUiElement(
        "微信",
        [entry],
        process_name="Weixin.exe",
        width=1000,
        height=800,
    )
    moments = FakeUiElement(
        "朋友圈",
        process_name="Weixin.exe",
        width=700,
        height=900,
    )
    desktop = FakeDesktop([main, moments])
    automation = PywinautoWechatAutomation()
    automation.desktop = desktop
    automation.window = main
    automation.window_manager = WeChatWindowManager(
        desktop,
        window_rect_provider=lambda: (0, 0, 960, 1040),
    )

    automation.open_moments()

    assert entry.clicked is True
    assert automation.window is moments


def test_wechat_likes_first_moment_and_verifies(monkeypatch):
    monkeypatch.setattr(wechat_module.time, "sleep", lambda _seconds: None)
    locator = FakeImageLocator()
    locator.moment_action_matches = [
        ImageMatch(1000, 744, 1.0, "beforeLike.png")
    ]
    locator.moment_menu_matches = [
        ImageMatch(850, 744, 1.0, "like.png"),
        None,
    ]
    automation = PywinautoWechatAutomation(image_locator=locator)
    automation.window = FakeUiElement(
        "朋友圈",
        process_name="Weixin.exe",
        width=653,
        height=825,
        left=0,
        top=0,
    )
    monkeypatch.setattr(automation, "open_moments", lambda: None)

    result = automation.like_moment(target="first")

    assert result["status"] == "liked"
    assert result["target"] == "first"
    assert locator.xy_clicks == [(1000, 744), (750, 744)]


def test_wechat_already_liked_moment_does_not_toggle_like(monkeypatch):
    monkeypatch.setattr(wechat_module.time, "sleep", lambda _seconds: None)
    locator = FakeImageLocator()
    locator.moment_action_matches = [
        ImageMatch(1000, 744, 1.0, "beforeLike.png")
    ]
    locator.moment_menu_matches = [None]
    locator.moment_states = ["already_liked"]
    automation = PywinautoWechatAutomation(image_locator=locator)
    automation.window = FakeUiElement(
        "朋友圈",
        process_name="Weixin.exe",
        width=653,
        height=825,
    )
    monkeypatch.setattr(automation, "open_moments", lambda: None)

    result = automation.like_moment(target="first")

    assert result["status"] == "already_liked"
    assert locator.xy_clicks == [(1000, 744)]
    assert locator.ocr_find_calls == []


def test_wechat_likes_newest_moment_by_author(monkeypatch):
    monkeypatch.setattr(wechat_module.time, "sleep", lambda _seconds: None)
    locator = FakeImageLocator()
    locator.moment_author_matches = [
        ImageMatch(210, 360, 1.0, "moment_author:张三")
    ]
    locator.moment_action_matches = [
        ImageMatch(1000, 744, 1.0, "beforeLike.png")
    ]
    locator.moment_menu_matches = [
        ImageMatch(850, 744, 1.0, "like.png"),
        None,
    ]
    automation = PywinautoWechatAutomation(image_locator=locator)
    automation.window = FakeUiElement(
        "朋友圈",
        process_name="Weixin.exe",
        width=653,
        height=825,
    )
    monkeypatch.setattr(automation, "open_moments", lambda: None)

    result = automation.like_moment(author_name="张三", target="author")

    assert result["status"] == "liked"
    assert result["author_name"] == "张三"
    author_region = locator.moment_author_calls[0][0]
    action_region = locator.moment_action_calls[0]
    assert action_region[1] >= author_region[1]


def test_wechat_moment_author_search_has_bounded_scrolling(monkeypatch):
    monkeypatch.setattr(wechat_module.time, "sleep", lambda _seconds: None)
    locator = FakeImageLocator()
    locator.moment_author_matches = [None, None, None]
    automation = PywinautoWechatAutomation(image_locator=locator)
    automation.window = FakeUiElement(
        "朋友圈",
        process_name="Weixin.exe",
        width=653,
        height=825,
    )
    monkeypatch.setattr(automation, "open_moments", lambda: None)
    keys = []
    monkeypatch.setattr(automation, "_send_keys", keys.append)

    with pytest.raises(RuntimeError, match="张三"):
        automation.like_moment(
            author_name="张三",
            target="author",
            max_scrolls=2,
        )

    assert keys == ["{PGDN}", "{PGDN}"]


def test_wechat_like_moment_function_delegates_to_automation():
    class FakeMomentAutomation:
        def __init__(self):
            self.calls = []

        def open(self):
            self.calls.append(("open",))

        def like_moment(self, *, author_name=None, target="first"):
            self.calls.append(("like", author_name, target))
            return {
                "success": True,
                "status": "liked",
                "author_name": author_name,
                "target": target,
            }

    automation = FakeMomentAutomation()

    result = wechat_module.like_moment(
        author_name="张三",
        target="author",
        automation=automation,
    )

    assert result["status"] == "liked"
    assert automation.calls == [("open",), ("like", "张三", "author")]


def test_wechat_clicks_parent_row_when_service_account_type_is_sibling():
    row = FakeUiElement("", [FakeUiElement("火眼审阅"), FakeUiElement("服务号")])
    other_row = FakeUiElement("", [FakeUiElement("火眼审阅"), FakeUiElement("联系人")])
    window = FakeUiElement("", [other_row, row])
    automation = PywinautoWechatAutomation()
    automation.window = window

    automation._click_service_account_result("火眼审阅")

    assert row.clicked is True
    assert other_row.clicked is False


def test_wechat_clicks_account_name_result_without_service_label():
    row = FakeUiElement("", [FakeUiElement("火眼审阅")])
    window = FakeUiElement("", [row])
    automation = PywinautoWechatAutomation()
    automation.window = window

    automation._click_service_account_result("火眼审阅")

    assert row.clicked is True


def test_wechat_clicks_first_visual_result_when_text_result_missing(monkeypatch):
    monkeypatch.setattr(wechat_module.time, "sleep", lambda _seconds: None)
    image_locator = FakeImageLocator()
    window = FakeUiElement("微信", process_name="WeChat.exe", width=1000, height=800, left=0, top=0)
    automation = PywinautoWechatAutomation(image_locator=image_locator)
    automation.window = window
    automation._send_keys = lambda _keys: None
    automation._switch_to_account_window = lambda _account, before_handles=None: True

    automation._click_service_account_result("火眼审阅")

    assert image_locator.xy_clicks == [(190, 312)]


def test_wechat_clicks_green_account_text_before_visual_position(monkeypatch):
    monkeypatch.setattr(wechat_module.time, "sleep", lambda _seconds: None)
    image_locator = FakeImageLocator()
    image_locator.green_text_matches = [object()]
    window = FakeUiElement("微信", process_name="WeChat.exe", width=1000, height=800, left=0, top=0)
    automation = PywinautoWechatAutomation(image_locator=image_locator)
    automation.window = window
    automation._send_keys = lambda _keys: None
    automation._switch_to_account_window = lambda _account, before_handles=None: True

    automation._click_service_account_result("火眼审阅")

    assert image_locator.first_green_text_calls == [((0, 0, 1000, 800), "火眼审阅")]
    assert image_locator.green_text_calls == [((0, 0, 1000, 800), "火眼审阅")]
    assert image_locator.xy_clicks == []


def test_wechat_first_account_result_clicks_fixed_point_after_tab(monkeypatch):
    monkeypatch.setattr(wechat_module.time, "sleep", lambda _seconds: None)
    image_locator = FakeImageLocator()
    image_locator.first_green_text_matches = [object()]
    text_row = FakeUiElement("", [FakeUiElement("火眼审阅")])
    window = FakeUiElement(
        "火眼审阅",
        [text_row],
        process_name="WeChatAppEx.exe",
        width=1000,
        height=800,
        left=0,
        top=0,
    )
    automation = PywinautoWechatAutomation(image_locator=image_locator)
    automation.window = window
    confirmed: list[tuple[str, set[int] | None]] = []
    automation._confirm_after_search_result_click = (
        lambda account, before_handles=None: confirmed.append((account, before_handles))
        or True
    )

    assert automation._click_first_account_result_after_tab(
        "火眼审阅",
        before_handles={1},
    )

    assert image_locator.xy_clicks == [(440, 460)]
    assert image_locator.first_green_text_calls == []
    assert text_row.clicked is False
    assert confirmed == [("火眼审阅", {1})]


def test_wechat_clicks_accounts_tab_by_text(monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr(wechat_module.time, "sleep", lambda seconds: sleeps.append(seconds))
    accounts_tab = FakeUiElement("账号")
    window = FakeUiElement("火眼审阅", [accounts_tab], process_name="WeChatAppEx.exe")
    automation = PywinautoWechatAutomation(image_locator=FakeImageLocator())
    automation.window = window

    assert automation._click_search_accounts_tab(timeout=0.1)

    assert accounts_tab.clicked is True
    assert SEARCH_ACCOUNTS_TAB_SETTLE_SECONDS in sleeps


def test_wechat_clicks_accounts_tab_by_window_relative_fallback(monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr(wechat_module.time, "sleep", lambda seconds: sleeps.append(seconds))
    image_locator = FakeImageLocator()
    window = FakeUiElement(
        "火眼审阅",
        process_name="WeChatAppEx.exe",
        width=1000,
        height=800,
        left=50,
        top=70,
    )
    automation = PywinautoWechatAutomation(image_locator=image_locator)
    automation.window = window

    assert automation._click_search_accounts_tab(timeout=0.0)

    assert image_locator.relative_clicks == [((50, 70, 1000, 800), *SEARCH_ACCOUNTS_TAB_REL)]
    assert SEARCH_ACCOUNTS_TAB_SETTLE_SECONDS in sleeps


def test_wechat_normalizes_window_after_accounts_tab_refresh(monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr(wechat_module.time, "sleep", lambda seconds: sleeps.append(seconds))
    image_locator = FakeImageLocator()
    image_locator.ocr_matches = [object()]
    window = FakeUiElement("火眼审阅", process_name="WeChatAppEx.exe")
    automation = PywinautoWechatAutomation(image_locator=image_locator)
    automation.window = window
    normalized: list[str] = []
    automation._normalize_current_window = lambda: normalized.append("after-tab")

    assert automation._click_search_accounts_tab(timeout=0.1)

    assert sleeps == [SEARCH_ACCOUNTS_TAB_SETTLE_SECONDS]
    assert normalized == ["after-tab"]


def test_wechat_clicks_accounts_tab_with_ocr_before_coordinate_fallback(monkeypatch):
    monkeypatch.setattr(wechat_module.time, "sleep", lambda _seconds: None)
    image_locator = FakeImageLocator()
    image_locator.ocr_matches = [object()]
    window = FakeUiElement(
        "火眼审阅",
        process_name="WeChatAppEx.exe",
        width=1000,
        height=800,
        left=50,
        top=70,
    )
    automation = PywinautoWechatAutomation(image_locator=image_locator)
    automation.window = window

    assert automation._click_search_accounts_tab(timeout=0.0)

    assert image_locator.ocr_calls == [((50, 70, 1000, 800), "账号")]
    assert image_locator.relative_clicks == []


def test_wechat_clicks_result_relative_to_souyisou_anchor(monkeypatch):
    monkeypatch.setattr(wechat_module.time, "sleep", lambda _seconds: None)
    image_locator = FakeImageLocator()
    image_locator.find_matches = [ImageMatch(40, 30, 0.95, "搜一搜.png")]
    window = FakeUiElement("微信", process_name="WeChat.exe", width=1000, height=800, left=500, top=100)
    automation = PywinautoWechatAutomation(image_locator=image_locator)
    automation.window = window

    assert automation._click_first_search_result_visual()

    assert image_locator.find_calls[0] == ("搜一搜.png", None, 0.72)
    assert image_locator.xy_clicks == [(280, 270)]


def test_wechat_search_result_window_wait_retries_until_app_ex_available(monkeypatch):
    now = [0.0]
    sleeps: list[float] = []
    monkeypatch.setattr(wechat_module.time, "time", lambda: now[0])

    def fake_sleep(seconds):
        sleeps.append(seconds)
        now[0] += seconds

    monkeypatch.setattr(wechat_module.time, "sleep", fake_sleep)
    automation = PywinautoWechatAutomation()
    calls: list[tuple[str, float, set[int] | None, bool]] = []

    def fake_switch(
        account_name,
        timeout=6.0,
        before_handles=None,
        allow_taskbar_activation=True,
    ):
        calls.append(
            (account_name, timeout, before_handles, allow_taskbar_activation)
        )
        return len(calls) >= 2

    automation._switch_to_account_window = fake_switch

    assert automation._wait_for_search_result_window(
        "火眼审阅",
        before_handles={1},
        wait_seconds=1.0,
    )
    assert len(calls) >= 2
    assert calls[0] == ("火眼审阅", 1.0, {1}, False)
    assert sleeps


def test_wechat_search_result_rejects_main_window_with_matching_text(monkeypatch):
    monkeypatch.setattr(wechat_module.time, "sleep", lambda _seconds: None)
    main_window = FakeUiElement(
        "微信",
        [FakeUiElement("火眼审阅")],
        process_name="WeChat.exe",
    )
    automation = PywinautoWechatAutomation()
    automation.window = main_window
    automation.desktop = FakeDesktop([main_window])

    assert not automation._switch_to_account_window(
        "火眼审阅",
        timeout=0.01,
        before_handles={PywinautoWechatAutomation._window_handle(main_window)},
        allow_taskbar_activation=False,
    )
    assert automation.window is main_window


def test_wechat_clicks_contact_row_and_avoids_official_account_result():
    official_row = FakeUiElement("", [FakeUiElement("文件传输助手"), FakeUiElement("公众号")])
    contact_row = FakeUiElement("", [FakeUiElement("文件传输助手")])
    window = FakeUiElement("", [official_row, contact_row])
    automation = PywinautoWechatAutomation()
    automation.window = window
    automation._send_keys = lambda _keys: None

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
    automation._send_keys = lambda _keys: None

    automation._click_contact_result("文件传输助手")

    assert search_input.clicked is False
    assert search_container.clicked is False
    assert contact_row.clicked is True


def test_wechat_official_search_submits_with_enter_then_uses_ocr_accounts_tab(monkeypatch):
    monkeypatch.setattr(wechat_module.time, "sleep", lambda _seconds: None)
    image_locator = FakeImageLocator()
    automation = PywinautoWechatAutomation(image_locator=image_locator)
    automation.window = FakeUiElement("微信", process_name="WeChat.exe")
    sent: list[str] = []
    actions: list[tuple[str, object, object]] = []
    automation._send_keys = lambda keys: sent.append(keys)
    automation._paste_or_type = lambda text: sent.append(text)
    automation._snapshot_window_handles = lambda: {1}
    automation._normalize_current_window = lambda: None
    automation._wait_for_search_result_window = (
        lambda account, before_handles=None, wait_seconds=0.0: actions.append(
            ("wait", account, (before_handles, wait_seconds))
        )
        or True
    )
    automation._click_search_accounts_tab = lambda timeout=3.0: actions.append(
        ("tab", "账号", timeout)
    ) or True
    automation._click_first_account_result_after_tab = (
        lambda account, before_handles=None: actions.append(
            ("first", account, before_handles)
        )
        or True
    )
    automation._click_service_account_result = (
        lambda account, before_handles=None: actions.append(
            ("fallback", account, before_handles)
        )
    )
    main_handle = PywinautoWechatAutomation._window_handle(automation.window)

    automation.search_official_account("火眼审阅")

    assert image_locator.calls == []
    assert sent == ["^f", "^a", "火眼审阅", "{ENTER}"]
    assert actions == [
        (
            "wait",
            "火眼审阅",
            ({main_handle}, SEARCH_RESULT_WINDOW_DETECT_SECONDS),
        ),
        ("tab", "账号", 10.0),
        ("first", "火眼审阅", {1}),
    ]


def test_wechat_official_search_waits_between_keyboard_steps(monkeypatch):
    events: list[tuple[str, object]] = []
    monkeypatch.setattr(
        wechat_module.time,
        "sleep",
        lambda seconds: events.append(("sleep", seconds)),
    )
    automation = PywinautoWechatAutomation(image_locator=FakeImageLocator())
    automation.window = FakeUiElement("微信", process_name="WeChat.exe")
    automation._normalize_current_window = lambda: None
    automation._snapshot_window_handles = lambda: events.append(
        ("snapshot", None)
    ) or {1}
    automation._send_keys = lambda keys: events.append(("keys", keys))
    automation._paste_or_type = lambda text: events.append(("input", text))
    automation._wait_for_search_result_window = lambda *args, **kwargs: events.append(
        ("detect", None)
    ) or True
    automation._click_search_accounts_tab = lambda timeout=3.0: True
    automation._click_first_account_result_after_tab = lambda *args, **kwargs: True

    automation.search_official_account("火眼审阅")

    assert events[:6] == [
        ("keys", "^f"),
        ("sleep", 0.5),
        ("keys", "^a"),
        ("input", "火眼审阅"),
        ("sleep", 0.5),
        ("keys", "{ENTER}"),
    ]
    assert events[6:8] == [("detect", None), ("snapshot", None)]


def test_wechat_official_search_retries_enter_when_appex_does_not_open(monkeypatch):
    monkeypatch.setattr(wechat_module.time, "sleep", lambda _seconds: None)
    automation = PywinautoWechatAutomation(image_locator=FakeImageLocator())
    automation.window = FakeUiElement("微信", process_name="WeChat.exe")
    sent: list[str] = []
    normalizations: list[object] = []
    wait_results = iter([False, True])
    waits: list[tuple[str, set[int] | None, float]] = []
    automation._normalize_current_window = lambda: normalizations.append(
        automation.window
    )
    automation._snapshot_window_handles = lambda: {1}
    automation._send_keys = lambda keys: sent.append(keys)
    automation._paste_or_type = lambda _text: None

    def fake_wait(account, *, before_handles, wait_seconds):
        waits.append((account, before_handles, wait_seconds))
        return next(wait_results)

    automation._wait_for_search_result_window = fake_wait
    automation._click_search_accounts_tab = lambda timeout=3.0: True
    automation._click_first_account_result_after_tab = lambda *args, **kwargs: True
    main_handle = PywinautoWechatAutomation._window_handle(automation.window)

    automation.search_official_account("火眼审阅")

    assert sent.count("{ENTER}") == 2
    assert len(normalizations) == 2
    assert waits == [
        ("火眼审阅", {main_handle}, SEARCH_RESULT_WINDOW_DETECT_SECONDS),
        ("火眼审阅", {main_handle}, SEARCH_RESULT_WINDOW_DETECT_SECONDS),
    ]


def test_wechat_official_search_requires_accounts_tab_before_fallback(monkeypatch):
    monkeypatch.setattr(wechat_module.time, "sleep", lambda _seconds: None)
    image_locator = FakeImageLocator(matches=[object()])
    automation = PywinautoWechatAutomation(image_locator=image_locator)
    automation.window = FakeUiElement("微信", process_name="WeChat.exe")
    automation._send_keys = lambda _keys: None
    automation._paste_or_type = lambda _text: None
    automation._snapshot_window_handles = lambda: {1}
    automation._wait_for_search_result_window = lambda *args, **kwargs: True
    actions: list[str] = []
    automation._click_search_accounts_tab = lambda timeout=3.0: actions.append("tab") or False
    automation._click_first_account_result_after_tab = (
        lambda account, before_handles=None: actions.append("first") or False
    )
    automation._click_service_account_result = (
        lambda account, before_handles=None: actions.append("fallback")
    )

    with pytest.raises(RuntimeError, match="账号"):
        automation.search_official_account("火眼审阅")

    assert actions == ["tab"]


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
    automation = PywinautoWechatAutomation(image_locator=FakeImageLocator())
    automation.window = window
    sent_keys: list[str] = []
    automation._paste_or_type = lambda text: sent_keys.append(text)
    automation._send_keys = lambda keys: sent_keys.append(keys)
    automation._click_relative = lambda win, _rx, _ry: setattr(win, "clicked", True)
    automation._click_send_button_visual = lambda timeout=1.5: (_ for _ in ()).throw(
        AssertionError("send button should not be clicked")
    )

    automation.send_message("你好")

    assert search_input.clicked is False
    assert message_edit.clicked is True
    assert sent_keys == ["你好", "{ENTER}"]


def test_wechat_send_message_uses_visual_input_and_enter(monkeypatch):
    monkeypatch.setattr(wechat_module.time, "sleep", lambda _seconds: None)
    image_locator = FakeImageLocator(matches=[object()])
    window = FakeUiElement("微信", process_name="WeChat.exe", width=1000, height=800, left=0, top=0)
    automation = PywinautoWechatAutomation(image_locator=image_locator)
    automation.window = window
    sent_keys: list[str] = []
    automation._paste_or_type = lambda text: sent_keys.append(text)
    automation._send_keys = lambda keys: sent_keys.append(keys)
    automation._find_message_edit = lambda: None
    automation._click_send_button_visual = lambda timeout=1.5: (_ for _ in ()).throw(
        AssertionError("send button should not be clicked")
    )
    automation._click_relative = lambda *_args: (_ for _ in ()).throw(
        AssertionError("relative fallback should not be used")
    )

    automation.send_message("你好")

    assert image_locator.calls == [
        ("wechatSend.png", (0, 0, 1000, 800), 0.72),
    ]
    assert sent_keys == ["你好", "{ENTER}"]


def test_wechat_template_click_normalizes_window_before_screenshot(monkeypatch):
    monkeypatch.setattr(wechat_module.time, "sleep", lambda _seconds: None)
    image_locator = FakeImageLocator(matches=[object()])
    window = FakeUiElement(
        "微信",
        process_name="WeChat.exe",
        width=700,
        height=600,
        left=300,
        top=200,
    )
    automation = PywinautoWechatAutomation(image_locator=image_locator)
    automation.window = window
    automation.desktop = FakeDesktop([window])
    automation.window_manager = WeChatWindowManager(
        automation.desktop,
        window_rect_provider=lambda app_ex=False: (0, 0, 960, 1040),
    )

    assert automation._click_message_box_visual(timeout=0.0)

    assert window.moved_to == (0, 0, 960, 1040)
    assert window.focused is False
    assert image_locator.calls == [("wechatSend.png", (0, 0, 960, 1040), 0.72)]


def test_wechat_switches_to_app_ex_window_after_clicking_service_account_result(monkeypatch):
    monkeypatch.setattr(wechat_module.time, "sleep", lambda _seconds: None)
    image_locator = FakeImageLocator()
    image_locator.green_matches = [object()]
    row = FakeUiElement("", [FakeUiElement("火眼审阅"), FakeUiElement("服务号")])
    main_window = FakeUiElement("微信", [row], process_name="WeChat.exe")
    follow_parent = FakeUiElement("", [FakeUiElement("关注")])
    detail_window = FakeUiElement(
        "",
        [FakeUiElement("服务号"), follow_parent],
        process_name="WeChatAppEx.exe",
        width=1000,
        height=800,
        left=0,
        top=0,
    )
    automation = PywinautoWechatAutomation(image_locator=image_locator)
    automation.window = main_window
    automation.desktop = FakeDesktop([main_window, detail_window])
    automation.window_manager = WeChatWindowManager(
        automation.desktop,
        window_rect_provider=lambda app_ex=False: (0, 0, 1000, 800),
    )

    automation._click_service_account_result("火眼审阅")

    assert row.clicked is True
    assert automation.window is detail_window
    states = [False, True]
    automation._is_followed_state = lambda: states.pop(0) if states else True
    assert automation.follow_current_account() is True
    assert follow_parent.clicked is False
    assert image_locator.green_calls == [(0, 0, 1000, 800)]


def test_wechat_prefers_new_appex_window_after_click():
    row = FakeUiElement("", [FakeUiElement("火眼审阅"), FakeUiElement("服务号")])
    main_window = FakeUiElement("微信", [row], process_name="WeChat.exe")
    old_window = FakeUiElement("旧公众号", process_name="WeChatAppEx.exe")
    new_window = FakeUiElement("火眼审阅", [FakeUiElement("服务号")], process_name="WeChatAppEx.exe")
    automation = PywinautoWechatAutomation()
    automation.window = main_window
    automation.desktop = FakeDesktop([main_window, old_window, new_window])
    automation.window_manager = WeChatWindowManager(automation.desktop)
    before = {
        PywinautoWechatAutomation._window_handle(main_window),
        PywinautoWechatAutomation._window_handle(old_window),
    }

    automation._click_service_account_result("火眼审阅", before_handles=before)

    assert automation.window is new_window


def test_wechat_switch_clicks_appex_taskbar_icon_when_window_is_hidden(monkeypatch):
    monkeypatch.setattr(wechat_module.time, "sleep", lambda _seconds: None)
    main_window = FakeUiElement("微信", process_name="WeChat.exe")
    detail_window = FakeUiElement("火眼审阅", process_name="WeChatAppEx.exe")
    desktop = FakeDesktop([main_window])
    image_locator = FakeImageLocator(matches=[object()])
    automation = PywinautoWechatAutomation(image_locator=image_locator)
    automation.window = main_window
    automation.desktop = desktop
    before = {PywinautoWechatAutomation._window_handle(main_window)}

    def windows_after_taskbar_click():
        if image_locator.calls:
            return [main_window, detail_window]
        return [main_window]

    desktop.windows = windows_after_taskbar_click

    assert automation._switch_to_account_window(
        "火眼审阅",
        timeout=0.1,
        before_handles=before,
    )
    assert automation.window is detail_window
    assert ("WeChatAppExLogo.png", "taskbar", 0.72) in image_locator.calls


def test_wechat_switch_skips_taskbar_while_waiting_for_new_appex(monkeypatch):
    monkeypatch.setattr(wechat_module.time, "sleep", lambda _seconds: None)
    main_window = FakeUiElement("微信", process_name="WeChat.exe")
    automation = PywinautoWechatAutomation(image_locator=FakeImageLocator())
    automation.window = main_window
    automation.desktop = FakeDesktop([main_window])
    taskbar_attempts: list[float] = []
    automation._activate_appex_from_taskbar = (
        lambda *, timeout=2.0: taskbar_attempts.append(timeout) or False
    )

    assert not automation._switch_to_account_window(
        "火眼审阅",
        timeout=0.0,
        before_handles={PywinautoWechatAutomation._window_handle(main_window)},
        allow_taskbar_activation=False,
    )
    assert taskbar_attempts == []


def test_wechat_open_starts_by_name_before_taskbar_click(monkeypatch):
    monkeypatch.setattr(wechat_module.time, "sleep", lambda _seconds: None)
    image_locator = FakeImageLocator()
    main_window = FakeUiElement("微信", process_name="WeChat.exe")
    desktop = FakeDesktop([])
    launches: list[str] = []

    class FakeApplication:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def start(self, launch_name):
            launches.append(launch_name)
            desktop._windows = [main_window]
            return self

    fake_pywinauto = types.SimpleNamespace(
        Application=FakeApplication,
        Desktop=lambda backend=None: desktop,
    )
    monkeypatch.setitem(sys.modules, "pywinauto", fake_pywinauto)

    automation = PywinautoWechatAutomation(
        image_locator=image_locator,
        wait_timeout=0.1,
    )
    automation.open()

    assert automation.window is main_window
    assert launches == ["WeChat.exe"]
    assert image_locator.calls == []


def test_wechat_open_uses_win32_backend(monkeypatch):
    monkeypatch.setattr(wechat_module.time, "sleep", lambda _seconds: None)
    main_window = FakeUiElement("微信", process_name="WeChat.exe")
    desktop = FakeDesktop([])
    backends: list[tuple[str, object]] = []

    class FakeApplication:
        def __init__(self, *args, **kwargs) -> None:
            backends.append(("Application", kwargs.get("backend")))

        def start(self, launch_name):
            desktop._windows = [main_window]
            return self

    def fake_desktop(*, backend=None):
        backends.append(("Desktop", backend))
        return desktop

    fake_pywinauto = types.SimpleNamespace(
        Application=FakeApplication,
        Desktop=fake_desktop,
    )
    monkeypatch.setitem(sys.modules, "pywinauto", fake_pywinauto)

    PywinautoWechatAutomation(image_locator=FakeImageLocator(), wait_timeout=0.1).open()

    assert backends == [("Desktop", "win32"), ("Application", "win32")]


def test_wechat_follow_uses_green_rectangle_even_when_text_follow_control_exists(monkeypatch):
    monkeypatch.setattr(wechat_module.time, "sleep", lambda _seconds: None)
    image_locator = FakeImageLocator()
    image_locator.green_matches = [object()]
    follow_parent = FakeUiElement("", [FakeUiElement("关注")])
    window = FakeUiElement(
        "",
        [follow_parent],
        process_name="WeChatAppEx.exe",
        width=1000,
        height=800,
        left=0,
        top=0,
    )
    automation = PywinautoWechatAutomation(image_locator=image_locator)
    automation.window = window
    automation._needs_official_account_home_confirmation = lambda: False
    states = [False, True]
    automation._is_followed_state = lambda: states.pop(0) if states else True

    assert automation.follow_current_account() is True
    assert follow_parent.clicked is False
    assert image_locator.green_calls == [(0, 0, 1000, 800)]


def test_wechat_follow_clicks_green_button_when_text_target_missing(monkeypatch):
    monkeypatch.setattr(wechat_module.time, "sleep", lambda _seconds: None)
    image_locator = FakeImageLocator()
    image_locator.green_matches = [object()]
    window = FakeUiElement(
        "火眼审阅",
        [FakeUiElement("服务号")],
        process_name="WeChatAppEx.exe",
        width=1000,
        height=800,
        left=0,
        top=0,
    )
    automation = PywinautoWechatAutomation(image_locator=image_locator)
    automation.window = window
    states = [False, True]
    automation._is_followed_state = lambda: states.pop(0) if states else True

    assert automation.follow_current_account() is True
    assert image_locator.green_calls == [(0, 0, 1000, 800)]


def test_wechat_follow_visual_uses_green_rectangle_only(monkeypatch):
    monkeypatch.setattr(wechat_module.time, "sleep", lambda _seconds: None)
    image_locator = FakeImageLocator()
    image_locator.green_matches = [object()]
    window = FakeUiElement(
        "服务号",
        [FakeUiElement("服务号")],
        process_name="WeChatAppEx.exe",
        width=1000,
        height=800,
        left=0,
        top=0,
    )
    automation = PywinautoWechatAutomation(image_locator=image_locator)
    automation.window = window
    automation._needs_official_account_home_confirmation = lambda: False
    states = [False, True]
    automation._is_followed_state = lambda: states.pop(0) if states else True
    automation._click_screen_template = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("template matching should not be used for follow")
    )

    assert automation.follow_current_account() is True
    assert image_locator.green_calls == [(0, 0, 1000, 800)]


def test_wechat_follow_retries_until_followed_private_message_state(monkeypatch):
    monkeypatch.setattr(wechat_module.time, "sleep", lambda _seconds: None)
    window = FakeUiElement(
        "服务号",
        [FakeUiElement("关注")],
        process_name="WeChatAppEx.exe",
        width=1000,
        height=800,
        left=0,
        top=0,
    )
    automation = PywinautoWechatAutomation(image_locator=FakeImageLocator())
    automation.window = window
    automation._needs_official_account_home_confirmation = lambda: False
    states = [False, False, True]
    clicks: list[float] = []
    automation._is_followed_state = lambda: states.pop(0) if states else True
    automation._find_follow_button_target = lambda: None
    automation._click_follow_button_visual = lambda timeout=1.0: clicks.append(timeout) or True

    assert automation.follow_current_account() is True
    assert clicks == [1.0, 1.0]


def test_wechat_followed_state_requires_followed_and_private_message_text():
    window = FakeUiElement(
        "服务号",
        [FakeUiElement("已关注"), FakeUiElement("私信")],
        process_name="WeChatAppEx.exe",
    )
    automation = PywinautoWechatAutomation()
    automation.window = window

    assert automation._is_followed_state() is True


def test_wechat_official_home_can_be_confirmed_by_template(monkeypatch):
    monkeypatch.setattr(wechat_module.time, "sleep", lambda _seconds: None)
    image_locator = FakeImageLocator()
    image_locator.find_matches = [object()]
    window = FakeUiElement("火眼审阅", process_name="WeChatAppEx.exe", width=1000, height=800, left=0, top=0)
    automation = PywinautoWechatAutomation(image_locator=image_locator)
    automation.window = window

    assert automation._wait_for_official_account_home(account_name="火眼审阅", timeout=0.1)
    assert image_locator.find_calls == [("公众号.png", (0, 0, 1000, 800), 0.72)]


def test_wechat_send_message_uses_relative_input_fallback():
    image_locator = FakeImageLocator()
    window = FakeUiElement(
        "微信",
        process_name="WeChat.exe",
        width=1000,
        height=800,
        left=50,
        top=70,
    )
    automation = PywinautoWechatAutomation(image_locator=image_locator)
    automation.window = window
    sent_keys: list[str] = []
    automation._paste_or_type = lambda text: sent_keys.append(text)
    automation._send_keys = lambda keys: sent_keys.append(keys)
    automation._click_message_box_visual = lambda timeout=2.0: False
    automation._click_send_button_visual = lambda timeout=1.5: (_ for _ in ()).throw(
        AssertionError("send button should not be clicked")
    )

    automation.send_message("你好")

    assert sent_keys == ["你好", "{ENTER}"]
    assert image_locator.relative_clicks == [((50, 70, 1000, 800), *CHAT_INPUT_REL)]
    assert image_locator.xy_clicks == [(630, 774)]


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
        ("follow", None),
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


def test_wechat_like_moment_source_runs_inside_script_engine():
    source = Path(
        "src/skill_library/others/wechat_like_moment.py"
    ).read_text(encoding="utf-8")
    calls = []
    engine = ScriptEngine()
    engine.register_functions(
        {
            "wechat_like_moment": lambda **kwargs: calls.append(kwargs)
            or {"success": True, "status": "liked"},
            "log": lambda message: None,
        }
    )

    result = engine.execute(
        source + '\nresult = run(author_name="张三", target="author")\n'
    )

    assert result.success is True
    assert calls == [
        {
            "author_name": "张三",
            "target": "author",
            "launch_path": None,
        }
    ]


def test_router_routes_first_moment_like_typo_alias():
    router = SkillRouter(library_dir="src/skill_library")

    decision = router.route("给朋友圈的第一天点赞")

    assert decision.skill is not None
    assert decision.skill.id == "domain/wechat_like_moment"
    assert "# 自动调用\nrun()" in decision.script


def test_router_extracts_moment_author():
    router = SkillRouter(library_dir="src/skill_library")

    decision = router.route("给朋友圈张三发的内容点赞")

    assert decision.skill is not None
    assert decision.skill.id == "domain/wechat_like_moment"
    assert '__param_author_name = "张三"' in decision.script
    assert "run(author_name=__param_author_name)" in decision.script


def test_router_routes_wechat_follow_official_account():
    router = SkillRouter(library_dir="src/skill_library")

    decision = router.route("关注火眼审阅公众号")

    assert decision.skill is not None
    assert decision.skill.id == "domain/wechat_follow_official_account"
    assert '__param_account_name = "火眼审阅"' in decision.script
    assert "run(account_name=__param_account_name)" in decision.script
    assert "panel_prompt(" not in decision.script


def test_router_routes_wechat_send_contact_message():
    router = SkillRouter(library_dir="src/skill_library")

    decision = router.route("微信给文件传输助手发送你好")

    assert decision.skill is not None
    assert decision.skill.id == "domain/wechat_send_contact_message"
    assert '__param_contact_name = "文件传输助手"' in decision.script
    assert '__param_message = "你好"' in decision.script
    assert "run(contact_name=__param_contact_name, message=__param_message)" in decision.script
    assert "panel_prompt(" not in decision.script


def test_router_routes_wechat_send_official_account_message():
    router = SkillRouter(library_dir="src/skill_library")

    decision = router.route("给火眼审阅公众号发送你好呀")

    assert decision.skill is not None
    assert decision.skill.id == "domain/wechat_send_official_account_message"
    assert '__param_account_name = "火眼审阅"' in decision.script
    assert '__param_message = "你好呀"' in decision.script
    assert "run(account_name=__param_account_name, message=__param_message)" in decision.script
    assert "panel_prompt(" not in decision.script

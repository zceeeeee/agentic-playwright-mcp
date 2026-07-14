"""Tests for safe WeChat contact file sending."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

import src.layer_1.wechat_client as wechat_module
from src.core.script_engine import ScriptEngine
from src.core.skill_router import SkillRouter
from src.layer_1.wechat_client import (
    OPEN_BUTTON_NAMES,
    ClipboardTextSnapshot,
    ContactSelectionResult,
    FileSendPhase,
    PywinautoWechatAutomation,
    ValidatedLocalFile,
    WeChatFileSendError,
    WeChatFileSendResult,
    looks_like_windows_file_path,
    normalize_local_file_path,
    revalidate_local_file,
    send_contact_file,
    send_contact_message,
    validate_local_file,
)
from src.layer_2.controls import get_controls_exports
from src.skill_library.send.wechat_send_contact_file import run as run_file_skill
from src.skill_library.send.wechat_send_contact_message import run as run_message_skill


class FakeFileAutomation:
    def __init__(self, *, send_result: WeChatFileSendResult | None = None) -> None:
        self.calls: list[tuple[str, object | None]] = []
        self.send_result = send_result or WeChatFileSendResult(
            success=True,
            status="ui_verified",
            method="native_file_dialog",
            verified=True,
            phase=FileSendPhase.VERIFIED,
        )

    def open(self) -> None:
        self.calls.append(("open", None))

    def search_contact_verified(self, recipient: str) -> ContactSelectionResult:
        self.calls.append(("search_contact_verified", recipient))
        return ContactSelectionResult(recipient, recipient, True, None, True)

    def send_file(self, path: Path) -> WeChatFileSendResult:
        self.calls.append(("send_file", path.name))
        return self.send_result


class FakeEdit:
    def __init__(self, *, fail_set: bool = False) -> None:
        self.fail_set = fail_set
        self.clicked = False
        self.value = ""

    def click_input(self) -> None:
        self.clicked = True

    def set_edit_text(self, value: str) -> None:
        if self.fail_set:
            raise RuntimeError("set_edit_text failed")
        self.value = value


class FakeDialogButton:
    def __init__(self) -> None:
        self.clicked = False

    def click_input(self) -> None:
        self.clicked = True


def _validated(path: Path, *, dangerous: bool = False) -> ValidatedLocalFile:
    stat = path.stat()
    return ValidatedLocalFile(
        path=path,
        name=path.name,
        size_bytes=stat.st_size,
        modified_ns=stat.st_mtime_ns,
        extension=path.suffix.lower(),
        potentially_dangerous=dangerous,
    )


def test_windows_file_path_detection() -> None:
    assert looks_like_windows_file_path(r"D:\docs\a.pdf") is True
    assert looks_like_windows_file_path(r"D:/docs/a.pdf") is True
    assert looks_like_windows_file_path(r"\\server\share\a.pdf") is True
    assert looks_like_windows_file_path("普通文字消息") is False


def test_non_windows_file_send_is_rejected(monkeypatch) -> None:
    monkeypatch.setattr(wechat_module.sys, "platform", "linux")
    with pytest.raises(WeChatFileSendError, match="仅支持 Windows") as exc_info:
        normalize_local_file_path(r"D:\docs\a.pdf")
    assert exc_info.value.code == "UNSUPPORTED_PLATFORM"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows path validation")
def test_file_validation_and_change_detection(tmp_path: Path) -> None:
    path = tmp_path / "培养方案.pdf"
    path.write_bytes(b"first")
    validated = validate_local_file(str(path), max_size_bytes=100)
    assert validated.name == "培养方案.pdf"
    assert validated.size_bytes == 5
    assert validated.potentially_dangerous is False

    path.write_bytes(b"changed")
    with pytest.raises(WeChatFileSendError) as exc_info:
        revalidate_local_file(validated)
    assert exc_info.value.code == "FILE_CHANGED_AFTER_CONFIRMATION"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows path validation")
def test_file_validation_rejects_large_file_and_marks_dangerous(tmp_path: Path) -> None:
    large = tmp_path / "large.bin"
    large.write_bytes(b"12345")
    with pytest.raises(WeChatFileSendError) as exc_info:
        validate_local_file(str(large), max_size_bytes=4)
    assert exc_info.value.code == "FILE_TOO_LARGE"

    script = tmp_path / "run.ps1"
    script.write_text("Write-Host test", encoding="utf-8")
    validated = validate_local_file(str(script), max_size_bytes=1000)
    assert validated.potentially_dangerous is True


@pytest.mark.skipif(sys.platform != "win32", reason="Windows path validation")
@pytest.mark.parametrize(
    ("value", "expected_code"),
    [
        (r"docs\a.pdf", "PATH_NOT_ABSOLUTE"),
        ("https://example.com/a.pdf", "PATH_NOT_ABSOLUTE"),
        (r"D:\docs\*.pdf", "PATH_NOT_ABSOLUTE"),
    ],
)
def test_file_validation_rejects_unsupported_paths(
    value: str,
    expected_code: str,
) -> None:
    with pytest.raises(WeChatFileSendError) as exc_info:
        validate_local_file(value)
    assert exc_info.value.code == expected_code


@pytest.mark.skipif(sys.platform != "win32", reason="Windows path validation")
def test_file_validation_rejects_folder_and_accepts_empty_file(tmp_path: Path) -> None:
    with pytest.raises(WeChatFileSendError) as exc_info:
        validate_local_file(str(tmp_path))
    assert exc_info.value.code == "NOT_A_FILE"

    empty = tmp_path / "空文件.txt"
    empty.touch()
    validated = validate_local_file(str(empty))
    assert validated.size_bytes == 0


@pytest.mark.skipif(sys.platform != "win32", reason="Windows path validation")
def test_send_contact_file_sends_without_confirmation(tmp_path: Path) -> None:
    path = tmp_path / "年度报告 2026.pdf"
    path.write_bytes(b"report")
    automation = FakeFileAutomation()
    result = send_contact_file(
        recipient_name="文件传输助手",
        file_path=str(path),
        automation=automation,
        log_fn=lambda message: None,
    )

    assert result["success"] is True
    assert result["status"] == "ui_verified"
    assert result["file_name"] == path.name
    assert automation.calls == [
        ("open", None),
        ("search_contact_verified", "文件传输助手"),
        ("send_file", path.name),
    ]
@pytest.mark.skipif(sys.platform != "win32", reason="Windows path validation")
def test_invalid_file_does_not_open_wechat(tmp_path: Path) -> None:
    automation = FakeFileAutomation()

    with pytest.raises(WeChatFileSendError) as exc_info:
        send_contact_file(
            recipient_name="张三",
            file_path=str(tmp_path / "missing.pdf"),
            automation=automation,
            log_fn=lambda message: None,
        )

    assert exc_info.value.code == "FILE_NOT_FOUND"
    assert automation.calls == []


@pytest.mark.skipif(sys.platform != "win32", reason="Windows path validation")
def test_send_logs_do_not_expose_full_file_path(tmp_path: Path) -> None:
    private_dir = tmp_path / "private-folder"
    private_dir.mkdir()
    path = private_dir / "report.pdf"
    path.write_bytes(b"report")
    logs: list[str] = []

    result = send_contact_file(
        recipient_name="文件传输助手",
        file_path=str(path),
        automation=FakeFileAutomation(),
        log_fn=logs.append,
    )

    assert result["success"] is True
    assert str(private_dir) not in "\n".join(logs)


def test_unknown_send_status_is_returned_without_retry(monkeypatch, tmp_path: Path) -> None:
    path = tmp_path / "unknown.txt"
    path.write_text("unknown", encoding="utf-8")
    validated = _validated(path)
    automation = FakeFileAutomation()

    def unknown(_path):
        raise WeChatFileSendError(
            code="SEND_STATUS_UNKNOWN",
            message="unknown",
            send_may_have_started=True,
        )

    automation.send_file = unknown
    monkeypatch.setattr(wechat_module, "validate_local_file", lambda value: validated)
    monkeypatch.setattr(wechat_module, "revalidate_local_file", lambda value: None)
    result = send_contact_file(
        recipient_name="张三",
        file_path=str(path),
        automation=automation,
        log_fn=lambda message: None,
    )
    assert result["status"] == "unknown"
    assert result["retryable"] is False
    assert result["send_may_have_started"] is True


def test_chat_input_file_paste_presses_enter_exactly_once(monkeypatch, tmp_path: Path) -> None:
    path = tmp_path / "state.txt"
    path.write_text("state", encoding="utf-8")
    validated = _validated(path)
    automation = PywinautoWechatAutomation()
    automation.window = object()
    actions: list[str] = []
    monkeypatch.setattr(wechat_module, "validate_local_file", lambda value: validated)
    monkeypatch.setattr(wechat_module, "revalidate_local_file", lambda value: None)
    monkeypatch.setattr(automation, "_normalize_current_window", lambda: None)
    monkeypatch.setattr(
        automation,
        "_focus_message_input",
        lambda: actions.append("focus_chat_input") or "uia",
    )
    monkeypatch.setattr(automation, "_snapshot_file_markers", lambda name: set())
    monkeypatch.setattr(
        automation,
        "_set_file_drop_clipboard",
        lambda path: actions.append("set_file_clipboard")
        or ClipboardTextSnapshot(None, False),
    )
    monkeypatch.setattr(
        automation,
        "_restore_clipboard_text",
        lambda snapshot: actions.append("restore_clipboard"),
    )
    monkeypatch.setattr(
        automation,
        "_send_keys",
        lambda keys: actions.append("paste_file" if keys == "^v" else "press_enter"),
    )
    monkeypatch.setattr(
        automation,
        "_verify_outgoing_file",
        lambda name, baseline, timeout: True,
    )

    result = automation.send_file(path)
    assert result.status == "ui_verified"
    assert result.method == "clipboard_file_paste"
    assert actions == [
        "focus_chat_input",
        "set_file_clipboard",
        "paste_file",
        "press_enter",
        "restore_clipboard",
    ]
    assert actions.count("press_enter") == 1


def test_chat_input_file_returns_submitted_when_ui_verification_is_unavailable(
    monkeypatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "preview.txt"
    path.write_text("preview", encoding="utf-8")
    validated = _validated(path)
    automation = PywinautoWechatAutomation()
    automation.window = object()
    keys: list[str] = []
    monkeypatch.setattr(wechat_module, "validate_local_file", lambda value: validated)
    monkeypatch.setattr(wechat_module, "revalidate_local_file", lambda value: None)
    monkeypatch.setattr(automation, "_normalize_current_window", lambda: None)
    monkeypatch.setattr(automation, "_focus_message_input", lambda: "uia")
    monkeypatch.setattr(automation, "_snapshot_file_markers", lambda name: set())
    monkeypatch.setattr(
        automation,
        "_set_file_drop_clipboard",
        lambda path: ClipboardTextSnapshot(None, False),
    )
    monkeypatch.setattr(automation, "_restore_clipboard_text", lambda snapshot: None)
    monkeypatch.setattr(automation, "_send_keys", keys.append)
    monkeypatch.setattr(
        automation,
        "_verify_outgoing_file",
        lambda name, baseline, timeout: False,
    )

    result = automation.send_file(path)
    assert result.status == "submitted"
    assert result.method == "clipboard_file_paste"
    assert result.verified is False
    assert result.phase == FileSendPhase.SEND_TRIGGERED
    assert keys == ["^v", "{ENTER}"]


def test_send_file_falls_back_to_native_dialog_before_paste(monkeypatch, tmp_path: Path) -> None:
    path = tmp_path / "fallback.txt"
    path.write_text("fallback", encoding="utf-8")
    validated = _validated(path)
    automation = PywinautoWechatAutomation()
    automation.window = object()
    expected = WeChatFileSendResult(
        success=True,
        status="ui_verified",
        method="native_file_dialog",
        verified=True,
        phase=FileSendPhase.VERIFIED,
    )
    monkeypatch.setattr(wechat_module, "validate_local_file", lambda value: validated)
    monkeypatch.setattr(automation, "_normalize_current_window", lambda: None)
    monkeypatch.setattr(automation, "_focus_message_input", lambda: "uia")
    monkeypatch.setattr(automation, "_snapshot_file_markers", lambda name: set())
    monkeypatch.setattr(
        automation,
        "_send_file_via_chat_input",
        lambda validated, baseline: (_ for _ in ()).throw(
            WeChatFileSendError(
                code="FILE_CLIPBOARD_FAILED",
                message="clipboard unavailable",
            )
        ),
    )
    monkeypatch.setattr(
        automation,
        "_send_file_via_native_dialog",
        lambda validated, baseline: expected,
    )

    assert automation.send_file(path) == expected


def test_native_file_dialog_uses_set_edit_text_for_unicode_path(monkeypatch) -> None:
    automation = PywinautoWechatAutomation()
    edit = FakeEdit()
    monkeypatch.setattr(automation, "_find_file_name_edit", lambda dialog: edit)

    path = Path(r"D:\年度报告 2026\最终版本.pdf")
    automation._set_file_dialog_path(object(), path)

    assert edit.clicked is True
    assert edit.value == str(path)


def test_native_file_dialog_falls_back_to_clipboard_paste(monkeypatch) -> None:
    automation = PywinautoWechatAutomation()
    edit = FakeEdit(fail_set=True)
    keys: list[str] = []
    pasted: list[str] = []
    monkeypatch.setattr(automation, "_find_file_name_edit", lambda dialog: edit)
    monkeypatch.setattr(automation, "_send_keys", keys.append)
    monkeypatch.setattr(automation, "_paste_text_preserving_clipboard", pasted.append)

    path = Path(r"D:\中文目录\培养方案.pdf")
    automation._set_file_dialog_path(object(), path)

    assert keys == ["^a"]
    assert pasted == [str(path)]


@pytest.mark.parametrize("button_name", ["打开", "Open"])
def test_native_file_dialog_accepts_chinese_and_english_open_buttons(
    monkeypatch,
    button_name: str,
) -> None:
    automation = PywinautoWechatAutomation()
    button = FakeDialogButton()
    looked_up: list[tuple[tuple[str, ...], bool]] = []

    def find_by_name(dialog, names, **kwargs):
        del dialog
        looked_up.append((names, kwargs["exact"]))
        return button if button_name in names else None

    monkeypatch.setattr(automation.locator, "find_by_name", find_by_name)
    monkeypatch.setattr(automation, "_dialog_is_visible", lambda dialog: False)
    automation._confirm_file_dialog(object())

    assert button.clicked is True
    assert looked_up == [(OPEN_BUTTON_NAMES, True)]


def test_verified_contact_uses_regular_message_search_flow(monkeypatch) -> None:
    automation = PywinautoWechatAutomation()
    automation.window = object()
    searched: list[str] = []
    monkeypatch.setattr(automation, "search_contact", searched.append)

    result = automation.search_contact_verified("张三")

    assert searched == ["张三"]
    assert result.displayed_name == "张三"
    assert result.candidate_count is None
    assert result.verified is True


@pytest.mark.parametrize(
    ("task", "recipient", "file_path"),
    [
        ('微信给张三发送"D:\\comp_sci\\培养方案.pdf"', "张三", r"D:\comp_sci\培养方案.pdf"),
        ('用微信把"D:\\docs\\a.pdf"发给文件传输助手', "文件传输助手", r"D:\docs\a.pdf"),
        ('微信发送文件"D:\\docs\\a.pdf"给张三', "张三", r"D:\docs\a.pdf"),
        (
            '微信给居窝发送"D:\\Users\\qq275\\Pictures\\Screenshots\\屏幕截图 2026-04-01 133430.png"',
            "居窝",
            r"D:\Users\qq275\Pictures\Screenshots\屏幕截图 2026-04-01 133430.png",
        ),
    ],
)
def test_router_routes_wechat_file_send(task: str, recipient: str, file_path: str) -> None:
    decision = SkillRouter(library_dir="src/skill_library").route(task)
    assert decision.skill is not None
    assert decision.skill.id == "domain/wechat_send_contact_file"
    assert f'__param_recipient_name = "{recipient}"' in decision.script
    expected_json_path = file_path.replace("\\", "\\\\")
    assert f'__param_file_path = "{expected_json_path}"' in decision.script
    assert "run(recipient_name=__param_recipient_name, file_path=__param_file_path)" in decision.script


def test_router_keeps_text_and_file_skills_separate() -> None:
    router = SkillRouter(library_dir="src/skill_library")
    text = router.route("微信给张三发送你好")
    assert text.skill is not None
    assert text.skill.id == "domain/wechat_send_contact_message"

    file_task = router.route('微信给张三发送"D:\\docs\\a.pdf"')
    assert file_task.skill is not None
    assert file_task.skill.id == "domain/wechat_send_contact_file"

    question = router.route("请问微信怎么发送文件")
    assert question.skill is None
    negative = router.route('不要给张三发送"D:\\docs\\a.pdf"')
    assert negative.skill is None

    official_account = router.route('微信给火眼审阅公众号发送"D:\\docs\\a.pdf"')
    assert official_account.skill is None or (
        official_account.skill.id != "domain/wechat_send_contact_file"
    )


def test_unquoted_file_path_with_spaces_requires_panel_input() -> None:
    decision = SkillRouter(library_dir="src/skill_library").route(
        r"微信把D:\docs\年度报告 2026.pdf发给文件传输助手"
    )
    assert decision.skill is not None
    assert decision.skill.id == "domain/wechat_send_contact_file"
    assert "panel_prompt(" in decision.script
    assert '__param_file_path = "D:' not in decision.script


def test_missing_file_path_routes_to_file_skill_and_requests_input() -> None:
    decision = SkillRouter(library_dir="src/skill_library").route("微信给张三发送文件")
    assert decision.skill is not None
    assert decision.skill.id == "domain/wechat_send_contact_file"
    assert "panel_prompt(" in decision.script


def test_text_message_guards_against_file_paths() -> None:
    with pytest.raises(ValueError, match="wechat_send_contact_file"):
        run_message_skill(
            contact_name="张三",
            message=r"D:\docs\a.pdf",
            log_fn=lambda message: None,
            send_fn=lambda **kwargs: {"success": True},
        )
    with pytest.raises(WeChatFileSendError) as exc_info:
        send_contact_message(
            "张三",
            r"D:\docs\a.pdf",
            automation=object(),
        )
    assert exc_info.value.code == "ROUTE_VALIDATION_FAILED"


def test_file_skill_wrapper_handles_success_failure_and_unknown() -> None:
    calls = []
    success = run_file_skill(
        recipient_name="文件传输助手",
        file_path=r"D:\docs\a.pdf",
        log_fn=lambda message: None,
        send_fn=lambda **kwargs: calls.append(kwargs) or {"success": True, "status": "ui_verified"},
    )
    assert success["success"] is True
    assert calls[0]["recipient_name"] == "文件传输助手"

    with pytest.raises(RuntimeError, match="WeChat contact file sending failed"):
        run_file_skill(
            recipient_name="张三",
            file_path=r"D:\docs\a.pdf",
            log_fn=lambda message: None,
            send_fn=lambda **kwargs: {"success": False, "status": "cancelled"},
        )
    unknown = run_file_skill(
        recipient_name="张三",
        file_path=r"D:\docs\a.pdf",
        log_fn=lambda message: None,
        send_fn=lambda **kwargs: {"success": False, "status": "unknown"},
    )
    assert unknown["status"] == "unknown"


def test_file_skill_is_registered_in_script_engine() -> None:
    assert "wechat_send_contact_file" in get_controls_exports()
    source = Path("src/skill_library/send/wechat_send_contact_file.py").read_text(
        encoding="utf-8"
    )
    calls = []
    engine = ScriptEngine()
    engine.register_functions(
        {
            "wechat_send_contact_file": lambda **kwargs: calls.append(kwargs)
            or {"success": True, "status": "ui_verified"},
            "log": lambda message: None,
        }
    )
    result = engine.execute(
        source
        + '\nresult = run(recipient_name="文件传输助手", file_path="D:\\\\docs\\\\a.pdf")\n'
    )
    assert result.success is True
    assert calls[0]["recipient_name"] == "文件传输助手"


def test_wechat_send_skills_do_not_request_confirmation() -> None:
    router = SkillRouter(library_dir="src/skill_library")
    router.load()
    file_skill = router._skills["domain/wechat_send_contact_file"]
    message_skill = router._skills["domain/wechat_send_contact_message"]

    assert file_skill.confirm_before_run is False
    assert message_skill.confirm_before_run is False
    file_script = router.build_script(
        file_skill,
        '微信给文件传输助手发送"D:\\tmp\\report.txt"',
    )
    message_script = router.build_script(
        message_skill,
        "微信给文件传输助手发送你好",
    )
    assert "panel_prompt" not in file_script
    assert "panel_prompt" not in message_script


@pytest.mark.parametrize(
    "kwargs",
    [
        {"recipient_name": "-1", "file_path": r"D:\docs\a.pdf"},
        {"recipient_name": "张三", "file_path": "-1"},
    ],
)
def test_file_skill_requires_recipient_and_file_path(kwargs: dict[str, str]) -> None:
    with pytest.raises(ValueError):
        run_file_skill(
            **kwargs,
            log_fn=lambda message: None,
            send_fn=lambda **values: {"success": True},
        )

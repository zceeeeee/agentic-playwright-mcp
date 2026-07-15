from __future__ import annotations

import json
import subprocess
import sys
import threading
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.layer_1.wechat_history_service import WechatHistoryService
from src.layer_1.wx_cli_client import (
    WxChatCandidate,
    WxCliClient,
    WxCliError,
    WxCliExecutableResolver,
    WxCliStatus,
    WxHistoryMeta,
    WxHistoryQuery,
    _CommandResult,
    normalize_history_query,
)


class StaticResolver:
    def __init__(self, command: list[str]) -> None:
        self.command = command

    def resolve(self) -> list[str]:
        return list(self.command)


def test_project_native_executable_is_preferred(tmp_path: Path) -> None:
    executable = (
        tmp_path
        / "tools"
        / "wx-cli"
        / "node_modules"
        / "@jackwener"
        / "wx-cli-win32-x64"
        / "bin"
        / "wx.exe"
    )
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"binary")

    assert WxCliExecutableResolver(tmp_path).resolve() == [str(executable.resolve())]


def test_explicit_path_rejects_unrelated_executable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    executable = tmp_path / "powershell.exe"
    executable.write_bytes(b"binary")
    monkeypatch.setenv("WX_CLI_PATH", str(executable))

    with pytest.raises(WxCliError) as exc_info:
        WxCliExecutableResolver(tmp_path).resolve()
    assert exc_info.value.code == "WX_CLI_NOT_INSTALLED"


@pytest.mark.parametrize(
    "dangerous_name",
    [
        "张三 & del C:\\\\",
        "张三 | whoami",
        '张三"test',
        "%PATH%",
        "$(whoami)",
        "张 三",
        "emoji😀",
    ],
)
def test_invoke_passes_user_input_as_one_argument_without_shell(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    dangerous_name: str,
) -> None:
    script = "import json,sys; print(json.dumps({'args':sys.argv[1:]}, ensure_ascii=False))"
    client = WxCliClient(
        resolver=StaticResolver([sys.executable, "-c", script]),
        repository_root=tmp_path,
    )
    original_popen = subprocess.Popen
    calls: list[dict] = []

    def recording_popen(*args, **kwargs):
        calls.append(kwargs)
        return original_popen(*args, **kwargs)

    monkeypatch.setattr("src.layer_1.wx_cli_client.subprocess.Popen", recording_popen)
    result = client._invoke(["history", dangerous_name, "--json"], timeout=10)

    assert result.returncode == 0
    assert json.loads(result.stdout)["args"] == ["history", dangerous_name, "--json"]
    assert calls[0]["shell"] is False


def test_invoke_honors_cancellation(tmp_path: Path) -> None:
    client = WxCliClient(
        resolver=StaticResolver(
            [sys.executable, "-c", "import time; time.sleep(30)"]
        ),
        repository_root=tmp_path,
    )
    cancelled = threading.Event()
    timer = threading.Timer(0.15, cancelled.set)
    timer.start()
    try:
        with pytest.raises(WxCliError) as exc_info:
            client._invoke([], timeout=10, cancel_event=cancelled)
    finally:
        timer.cancel()
    assert exc_info.value.code == "WX_CLI_CANCELLED"


def test_initialize_skips_init_when_status_is_already_ready(tmp_path: Path) -> None:
    client = WxCliClient(
        resolver=StaticResolver(["wx.exe"]),
        repository_root=tmp_path,
    )
    status = WxCliStatus(
        installed=True,
        executable="wx.exe",
        version="0.3.0",
        compatible=True,
        initialized=True,
        daemon_available=True,
        sessions_available=True,
        error_code=None,
        message="ok",
    )
    client._invoke = MagicMock(
        return_value=_CommandResult(0, "", "", 0.1)
    )
    client.check_status = MagicMock(return_value=status)

    assert client.initialize() == status
    client._invoke.assert_not_called()
    client.check_status.assert_called_once_with(cancel_event=None)


def test_explicit_initialize_uses_windows_elevation_without_force(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = WxCliClient(
        resolver=StaticResolver(["wx.exe"]),
        repository_root=tmp_path,
    )
    not_ready = WxCliStatus(
        installed=True,
        executable="wx.exe",
        version="0.3.0",
        compatible=True,
        initialized=False,
        daemon_available=True,
        sessions_available=False,
        error_code="WX_CLI_INIT_REQUIRED",
        message="setup required",
    )
    healthy = WxCliStatus(
        installed=True,
        executable="wx.exe",
        version="0.3.0",
        compatible=True,
        initialized=True,
        daemon_available=True,
        sessions_available=True,
        error_code=None,
        message="ok",
    )
    client._invoke_elevated_windows = MagicMock(
        return_value=_CommandResult(0, "", "", 0.2)
    )
    client.check_status = MagicMock(side_effect=[not_ready, healthy])
    monkeypatch.setattr("src.layer_1.wx_cli_client.sys.platform", "win32")

    assert client.initialize() == healthy
    client._invoke_elevated_windows.assert_called_once_with(
        ["wx.exe"], ["init"], timeout=120, cancel_event=None
    )


def test_force_init_only_runs_after_explicit_force_request(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = WxCliClient(
        resolver=StaticResolver(["wx.exe"]),
        repository_root=tmp_path,
    )
    broken = WxCliStatus(
        installed=True,
        executable="wx.exe",
        version="0.3.0",
        compatible=True,
        initialized=False,
        daemon_available=True,
        sessions_available=False,
        error_code="WX_CLI_DATABASE_DECRYPT_FAILED",
        message="无法解密 session.db",
    )
    healthy = WxCliStatus(
        installed=True,
        executable="wx.exe",
        version="0.3.0",
        compatible=True,
        initialized=True,
        daemon_available=True,
        sessions_available=True,
        error_code=None,
        message="ok",
    )
    client._invoke = MagicMock(
        return_value=_CommandResult(0, "initialized", "", 0.1)
    )
    client._invoke_elevated_windows = MagicMock(
        return_value=_CommandResult(0, "", "", 0.2)
    )
    client.check_status = MagicMock(side_effect=[broken, healthy])
    monkeypatch.setattr("src.layer_1.wx_cli_client.sys.platform", "win32")

    assert client.initialize(force=True) == healthy
    client._invoke_elevated_windows.assert_called_once_with(
        ["wx.exe"], ["init", "--force"], timeout=120, cancel_event=None
    )
    assert client.check_status.call_count == 2


def test_decrypt_failure_has_a_specific_error_code() -> None:
    error = WxCliClient._error_from_command(
        _CommandResult(1, "", "错误: 无法解密 session.db", 0.1),
        stage="sessions",
    )
    assert error.code == "WX_CLI_DATABASE_DECRYPT_FAILED"
    assert error.stage == "sessions"
    assert "密钥" in error.message


def test_check_status_uses_sessions_as_primary_health_check(tmp_path: Path) -> None:
    client = WxCliClient(
        resolver=StaticResolver(["wx.exe"]),
        repository_root=tmp_path,
    )

    def invoke(args, **_kwargs):
        if args == ["--version"]:
            return _CommandResult(0, "wx 0.3.0", "", 0.1)
        if args[0] == "sessions":
            return _CommandResult(0, '{"sessions": []}', "", 0.1)
        return _CommandResult(1, "", "daemon unavailable", 0.1)

    client._invoke = MagicMock(side_effect=invoke)
    status = client.check_status()

    assert status.initialized is True
    assert status.sessions_available is True
    assert status.daemon_available is False
    assert status.failure_stage is None


def test_check_status_rejects_unsupported_version_before_sessions(tmp_path: Path) -> None:
    client = WxCliClient(
        resolver=StaticResolver(["wx.exe"]),
        repository_root=tmp_path,
    )
    client._invoke = MagicMock(
        return_value=_CommandResult(0, "wx 0.4.0", "", 0.1)
    )

    status = client.check_status()

    assert status.compatible is False
    assert status.error_code == "WX_CLI_VERSION_UNSUPPORTED"
    assert status.failure_stage == "version"
    client._invoke.assert_called_once()


def test_unknown_sessions_error_keeps_redacted_diagnostic(tmp_path: Path) -> None:
    client = WxCliClient(
        resolver=StaticResolver(["wx.exe"]),
        repository_root=tmp_path,
    )

    def invoke(args, **_kwargs):
        if args == ["--version"]:
            return _CommandResult(0, "wx 0.3.0", "", 0.1)
        if args[0] == "sessions":
            return _CommandResult(
                7,
                "",
                r"unexpected failure C:\Users\alice\db\session.db wxid_secret 0123456789abcdef0123456789abcdef",
                0.1,
            )
        return _CommandResult(1, "", "daemon unavailable", 0.1)

    client._invoke = MagicMock(side_effect=invoke)
    status = client.check_status()

    assert status.error_code == "WX_CLI_SESSIONS_FAILED"
    assert status.failure_stage == "sessions"
    assert status.return_code == 7
    assert "C:\\Users\\alice" not in (status.diagnostic or "")
    assert "wxid_secret" not in (status.diagnostic or "")
    assert "0123456789abcdef0123456789abcdef" not in (status.diagnostic or "")


def test_parse_history_wrapper_and_freshness_warning() -> None:
    result = WxCliClient._parse_history(
        {
            "chat": "项目群",
            "username": "group@chatroom",
            "is_group": True,
            "chat_type": "group",
            "messages": [
                {
                    "timestamp": 1780000000,
                    "time": "2026-06-01 09:20:00",
                    "sender": "张三",
                    "sender_username": "wxid_secret",
                    "sender_group_nickname": "老张",
                    "type": "text",
                    "content": "收到",
                    "local_id": 7,
                    "unknown_extra": "ignored",
                }
            ],
            "meta": {
                "status": "possibly_stale_unknown_shards",
                "unknown_shards": ["message_8.db"],
                "chat_latest_timestamp": 1780000000,
                "session_last_timestamp": 1780001000,
            },
        },
        WxHistoryQuery(chat_name="group@chatroom", limit=50),
    )

    assert result.chat_type == "group"
    assert result.messages[0].sender_group_nickname == "老张"
    assert result.meta == WxHistoryMeta(
        status="possibly_stale_unknown_shards",
        unknown_shards=("message_8.db",),
        chat_latest_timestamp=1780000000,
        session_last_timestamp=1780001000,
    )
    public_meta = result.meta.to_public_dict()
    assert public_meta["unknown_shards_count"] == 1
    assert "message_8.db" not in json.dumps(public_meta)
    assert any("部分消息可能缺失" in warning for warning in result.warnings)


def test_history_requires_wrapper_object_with_messages() -> None:
    with pytest.raises(WxCliError) as exc_info:
        WxCliClient._parse_history(
            {"results": []}, WxHistoryQuery(chat_name="张三")
        )
    assert exc_info.value.code == "WX_CLI_INVALID_JSON"


def test_query_normalization_clamps_limit_and_maps_dates_and_type() -> None:
    query, warnings = normalize_history_query(
        chat_name=" 张三 ",
        limit="900",
        offset="2",
        since="2026年7月1日",
        until="2026-07-15",
        message_type="文件",
        today=date(2026, 7, 15),
    )
    assert query == WxHistoryQuery(
        chat_name="张三",
        limit=500,
        offset=2,
        since="2026-07-01",
        until="2026-07-15",
        message_type="file",
    )
    assert warnings


def test_relative_dates_use_the_local_calendar() -> None:
    recent, _ = normalize_history_query(
        chat_name="张三",
        since="最近 7 天",
        today=date(2026, 7, 15),
    )
    yesterday, _ = normalize_history_query(
        chat_name="张三",
        until="昨天",
        today=date(2026, 7, 15),
    )
    assert recent.since == "2026-07-09"
    assert yesterday.until == "2026-07-14"


@pytest.mark.parametrize(
    ("kwargs", "code"),
    [
        ({"chat_name": ""}, "CHAT_NAME_REQUIRED"),
        ({"chat_name": "张三\n李四"}, "CHAT_NAME_REQUIRED"),
        ({"chat_name": "张三", "limit": 0}, "INVALID_LIMIT"),
        ({"chat_name": "张三", "offset": -1}, "INVALID_OFFSET"),
        ({"chat_name": "张三", "message_type": "document"}, "INVALID_MESSAGE_TYPE"),
        (
            {"chat_name": "张三", "since": "2026-07-20", "until": "2026-07-01"},
            "INVALID_DATE_RANGE",
        ),
    ],
)
def test_query_validation_errors(kwargs: dict, code: str) -> None:
    with pytest.raises(WxCliError) as exc_info:
        normalize_history_query(**kwargs)
    assert exc_info.value.code == code


def test_service_requires_selection_for_ambiguous_candidates() -> None:
    candidates = [
        WxChatCandidate("wxid_1", "张三", "private", True),
        WxChatCandidate("group@chatroom", "张三", "group", True),
    ]
    selected = WechatHistoryService._select_unambiguous_candidate(
        "张三", candidates, candidate_selector=lambda values: values[1]
    )
    assert selected.username == "group@chatroom"

    with pytest.raises(WxCliError) as exc_info:
        WechatHistoryService._select_unambiguous_candidate("张三", candidates)
    assert exc_info.value.code == "CHAT_AMBIGUOUS"

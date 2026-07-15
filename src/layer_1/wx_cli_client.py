"""Safe adapter for the project-local wx-cli runtime.

This module never invokes a shell and never logs wx-cli stdout. It exposes the
fixed initialization and read-only command surface required by WeChat tasks.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import unicodedata
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

from src.logging import get_logger

logger = get_logger(__name__)

MESSAGE_TYPES = {
    "text",
    "image",
    "voice",
    "video",
    "sticker",
    "location",
    "link",
    "file",
    "call",
    "system",
}
MESSAGE_TYPE_MAP = {
    "文字": "text",
    "文本": "text",
    "图片": "image",
    "语音": "voice",
    "视频": "video",
    "表情": "sticker",
    "位置": "location",
    "链接": "link",
    "文件": "file",
    "通话": "call",
    "系统": "system",
}
FRESHNESS_STATUSES = {
    "ok",
    "windowed",
    "possibly_stale",
    "possibly_stale_unknown_shards",
}
MAX_STDOUT_BYTES = 10 * 1024 * 1024
MAX_STDERR_BYTES = 1024 * 1024


class WxCliError(RuntimeError):
    def __init__(
        self,
        *,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
        retryable: bool = False,
        user_action_required: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}
        self.retryable = retryable
        self.user_action_required = user_action_required


@dataclass(frozen=True)
class WxHistoryQuery:
    chat_name: str
    limit: int = 50
    offset: int = 0
    since: str | None = None
    until: str | None = None
    message_type: str | None = None


@dataclass(frozen=True)
class WxHistoryMessage:
    timestamp: int | None
    time: str
    sender: str
    content: str
    type: str
    local_id: int | str | None
    url: str | None = None
    sender_username: str | None = None
    sender_contact_display: str | None = None
    sender_group_nickname: str | None = None

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "time": self.time,
            "sender": self.sender,
            "content": self.content,
            "type": self.type,
            "local_id": self.local_id,
            "url": self.url,
            "sender_username": self.sender_username,
            "sender_contact_display": self.sender_contact_display,
            "sender_group_nickname": self.sender_group_nickname,
        }


@dataclass(frozen=True)
class WxHistoryMeta:
    status: str = "unknown"
    unknown_shards: tuple[str, ...] = ()
    chat_latest_timestamp: int | None = None
    session_last_timestamp: int | None = None

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "unknown_shards_count": len(self.unknown_shards),
            "chat_latest_timestamp": self.chat_latest_timestamp,
            "session_last_timestamp": self.session_last_timestamp,
        }


@dataclass(frozen=True)
class WxHistoryResult:
    chat: str
    username: str | None
    is_group: bool
    chat_type: str
    count: int
    messages: tuple[WxHistoryMessage, ...]
    meta: WxHistoryMeta
    warnings: tuple[str, ...] = ()

    def to_sensitive_payload(self) -> dict[str, Any]:
        return {
            "chat": self.chat,
            "is_group": self.is_group,
            "chat_type": self.chat_type,
            "count": self.count,
            "messages": [message.to_public_dict() for message in self.messages],
            "meta": self.meta.to_public_dict(),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class WxChatCandidate:
    username: str
    display_name: str
    chat_type: str
    exact_match: bool

    @property
    def is_group(self) -> bool:
        return self.chat_type == "group" or self.username.endswith("@chatroom")


@dataclass(frozen=True)
class WxCliStatus:
    installed: bool
    executable: str | None
    version: str | None
    compatible: bool
    initialized: bool
    daemon_available: bool
    sessions_available: bool
    error_code: str | None
    message: str


@dataclass(frozen=True)
class _CommandResult:
    returncode: int
    stdout: str
    stderr: str
    duration_seconds: float


class _PipeCollector(threading.Thread):
    def __init__(self, stream: Any, limit: int) -> None:
        super().__init__(daemon=True)
        self._stream = stream
        self._limit = limit
        self._chunks: list[bytes] = []
        self.size = 0
        self.too_large = threading.Event()

    def run(self) -> None:
        try:
            while True:
                chunk = self._stream.read(8192)
                if not chunk:
                    return
                self.size += len(chunk)
                if self.size > self._limit:
                    self.too_large.set()
                    return
                self._chunks.append(chunk)
        finally:
            try:
                self._stream.close()
            except Exception:
                pass

    def text(self) -> str:
        return b"".join(self._chunks).decode("utf-8", errors="replace")


class WxCliExecutableResolver:
    """Resolve wx-cli without relying on a global installation."""

    def __init__(self, repository_root: str | Path | None = None) -> None:
        self.repository_root = (
            Path(repository_root).resolve()
            if repository_root is not None
            else Path(__file__).resolve().parents[2]
        )

    def resolve(self) -> list[str]:
        explicit = os.getenv("WX_CLI_PATH", "").strip()
        if explicit:
            return self._validated_command(Path(explicit), explicit=True)

        resources = os.getenv("AGENT_DESKTOP_RESOURCES_PATH", "").strip()
        candidates: list[Path] = []
        if resources:
            candidates.append(Path(resources) / "tools" / "wx-cli" / "wx.exe")

        module_root = self.repository_root / "tools" / "wx-cli" / "node_modules"
        candidates.extend(
            [
                module_root
                / "@jackwener"
                / "wx-cli-win32-x64"
                / "bin"
                / "wx.exe",
                module_root / ".bin" / "wx.exe",
            ]
        )
        candidates.extend(sorted(module_root.glob("@jackwener/wx-cli-*/bin/wx.exe")))
        for candidate in candidates:
            if candidate.is_file():
                return [str(candidate.resolve())]

        shim = module_root / ".bin" / "wx.cmd"
        if shim.is_file():
            return self._validated_command(shim)

        found = shutil.which("wx") or shutil.which("wx.exe")
        if found:
            return [str(Path(found).resolve())]

        raise WxCliError(
            code="WX_CLI_NOT_INSTALLED",
            message=(
                "项目内 wx-cli 尚未安装。请在仓库根目录运行："
                "npm.cmd install --prefix tools/wx-cli"
            ),
            user_action_required=True,
        )

    def _validated_command(self, path: Path, *, explicit: bool = False) -> list[str]:
        candidate = path.expanduser().resolve()
        if not candidate.is_file():
            raise WxCliError(
                code="WX_CLI_NOT_INSTALLED",
                message="配置的 wx-cli 可执行文件不存在。",
                user_action_required=True,
            )
        if candidate.name.lower() not in {"wx", "wx.exe", "wx.cmd"}:
            raise WxCliError(
                code="WX_CLI_NOT_INSTALLED",
                message="WX_CLI_PATH 必须指向 wx、wx.exe 或经过验证的 wx.cmd。",
                user_action_required=True,
            )
        if candidate.suffix.lower() != ".cmd":
            return [str(candidate)]

        # Do not pass user data through cmd.exe. Translate the known npm shim
        # into a direct node invocation of the package launcher.
        package_launcher = (
            candidate.parent.parent / "@jackwener" / "wx-cli" / "bin" / "wx.js"
        )
        node = shutil.which("node") or shutil.which("node.exe")
        if package_launcher.is_file() and node:
            return [str(Path(node).resolve()), str(package_launcher.resolve())]
        reason = "显式配置的" if explicit else "项目内"
        raise WxCliError(
            code="WX_CLI_NOT_INSTALLED",
            message=f"{reason} wx.cmd 无法安全解析为原生 wx.exe。",
            user_action_required=True,
        )


class WxCliClient:
    def __init__(
        self,
        *,
        resolver: WxCliExecutableResolver | None = None,
        repository_root: str | Path | None = None,
        max_stdout_bytes: int = MAX_STDOUT_BYTES,
    ) -> None:
        self.repository_root = (
            Path(repository_root).resolve()
            if repository_root is not None
            else Path(__file__).resolve().parents[2]
        )
        self.resolver = resolver or WxCliExecutableResolver(self.repository_root)
        self.max_stdout_bytes = max_stdout_bytes

    def initialize(
        self,
        *,
        cancel_event: threading.Event | None = None,
        timeout: float = 120,
    ) -> WxCliStatus:
        """Run ``wx init`` before a WeChat task and verify the resulting state."""

        command = self.resolver.resolve()
        elevated_force_used = False
        result = self._invoke(
            ["init"], timeout=timeout, cancel_event=cancel_event, command=command
        )
        if result.returncode != 0:
            error = self._error_from_command(result)
            if sys.platform != "win32" or error.code not in {
                "WX_CLI_COMMAND_FAILED",
                "WX_CLI_DECRYPT_FAILED",
                "WX_CLI_NOT_INITIALIZED",
                "WX_CLI_PERMISSION_DENIED",
            }:
                raise error
            result = self._invoke_elevated_windows(
                command,
                ["init", "--force"],
                timeout=timeout,
                cancel_event=cancel_event,
            )
            elevated_force_used = True
            if result.returncode != 0:
                raise WxCliError(
                    code="WX_CLI_INIT_FAILED",
                    message=(
                        "wx-cli 自动初始化失败。请确认微信已登录，并允许 Windows "
                        "管理员权限提示后重试。"
                    ),
                    details={"returncode": result.returncode},
                    retryable=True,
                    user_action_required=True,
                )

        status = self.check_status(cancel_event=cancel_event)
        if (
            not status.initialized
            and sys.platform == "win32"
            and not elevated_force_used
            and status.error_code
            in {
                "WX_CLI_COMMAND_FAILED",
                "WX_CLI_DECRYPT_FAILED",
                "WX_CLI_NOT_INITIALIZED",
                "WX_CLI_PERMISSION_DENIED",
            }
        ):
            result = self._invoke_elevated_windows(
                command,
                ["init", "--force"],
                timeout=timeout,
                cancel_event=cancel_event,
            )
            if result.returncode != 0:
                raise WxCliError(
                    code="WX_CLI_INIT_FAILED",
                    message=(
                        "wx-cli 管理员强制初始化失败。请确认微信已登录，"
                        "并允许 Windows 管理员权限提示后重试。"
                    ),
                    details={"returncode": result.returncode},
                    retryable=True,
                    user_action_required=True,
                )
            status = self.check_status(cancel_event=cancel_event)
        if not status.initialized:
            raise WxCliError(
                code=status.error_code or "WX_CLI_INIT_FAILED",
                message=(
                    f"wx-cli 自动初始化后仍无法读取微信会话：{status.message}"
                ),
                retryable=True,
                user_action_required=True,
            )
        logger.info("wx-cli automatic initialization completed version=%s", status.version)
        return status

    def check_status(self, *, cancel_event: threading.Event | None = None) -> WxCliStatus:
        try:
            command = self.resolver.resolve()
        except WxCliError as exc:
            return WxCliStatus(
                installed=False,
                executable=None,
                version=None,
                compatible=False,
                initialized=False,
                daemon_available=False,
                sessions_available=False,
                error_code=exc.code,
                message=exc.message,
            )

        version_result = self._invoke(
            ["--version"], timeout=10, cancel_event=cancel_event, command=command
        )
        if version_result.returncode != 0:
            return WxCliStatus(
                installed=True,
                executable=command[-1],
                version=None,
                compatible=False,
                initialized=False,
                daemon_available=False,
                sessions_available=False,
                error_code="WX_CLI_COMMAND_FAILED",
                message="无法读取 wx-cli 版本。",
            )
        version_match = re.search(r"(\d+\.\d+\.\d+)", version_result.stdout)
        version = version_match.group(1) if version_match else None
        compatible = bool(version and version.startswith("0.3."))
        if not compatible:
            return WxCliStatus(
                installed=True,
                executable=command[-1],
                version=version,
                compatible=False,
                initialized=False,
                daemon_available=False,
                sessions_available=False,
                error_code="WX_CLI_VERSION_UNSUPPORTED",
                message=(
                    f"检测到 wx-cli 版本 {version or 'unknown'}，当前仅支持 0.3.x。"
                ),
            )

        daemon = self._invoke(
            ["daemon", "status"], timeout=10, cancel_event=cancel_event, command=command
        )
        sessions = self._invoke(
            ["sessions", "--json", "--limit", "1"],
            timeout=20,
            cancel_event=cancel_event,
            command=command,
        )
        if sessions.returncode != 0:
            error = self._error_from_command(sessions)
            return WxCliStatus(
                installed=True,
                executable=command[-1],
                version=version,
                compatible=True,
                initialized=False,
                daemon_available=daemon.returncode == 0,
                sessions_available=False,
                error_code=error.code,
                message=error.message,
            )
        try:
            self._parse_json_object(sessions.stdout)
        except WxCliError as exc:
            return WxCliStatus(
                installed=True,
                executable=command[-1],
                version=version,
                compatible=True,
                initialized=False,
                daemon_available=daemon.returncode == 0,
                sessions_available=False,
                error_code=exc.code,
                message=exc.message,
            )
        return WxCliStatus(
            installed=True,
            executable=command[-1],
            version=version,
            compatible=True,
            initialized=True,
            daemon_available=daemon.returncode == 0,
            sessions_available=True,
            error_code=None,
            message="wx-cli 已安装并完成初始化。",
        )

    def find_chat_candidates(
        self,
        requested_name: str,
        *,
        cancel_event: threading.Event | None = None,
    ) -> list[WxChatCandidate]:
        requested = _normalize_name(requested_name)
        command = self.resolver.resolve()
        sessions = self._invoke(
            ["sessions", "--json", "--limit", "500"],
            timeout=20,
            cancel_event=cancel_event,
            command=command,
        )
        if sessions.returncode != 0:
            raise self._error_from_command(sessions)
        candidates = self._candidate_items(
            self._parse_json_object(sessions.stdout), requested, source="sessions"
        )
        if any(candidate.exact_match for candidate in candidates):
            return _dedupe_candidates(candidates)

        contacts = self._invoke(
            ["contacts", "--query", requested_name, "--json", "--limit", "200"],
            timeout=20,
            cancel_event=cancel_event,
            command=command,
        )
        if contacts.returncode == 0:
            candidates.extend(
                self._candidate_items(
                    self._parse_json_object(contacts.stdout),
                    requested,
                    source="contacts",
                )
            )
        return _dedupe_candidates(candidates)

    def history(
        self,
        query: WxHistoryQuery,
        *,
        cancel_event: threading.Event | None = None,
    ) -> WxHistoryResult:
        command_args = [
            "history",
            query.chat_name,
            "--json",
            "--limit",
            str(query.limit),
            "--offset",
            str(query.offset),
        ]
        if query.since:
            command_args.extend(["--since", query.since])
        if query.until:
            command_args.extend(["--until", query.until])
        if query.message_type:
            command_args.extend(["--type", query.message_type])

        started = time.monotonic()
        result = self._invoke(command_args, timeout=60, cancel_event=cancel_event)
        if result.returncode != 0:
            raise self._error_from_command(result)
        parsed = self._parse_history(self._parse_json_object(result.stdout), query)
        logger.info(
            "wx-cli history completed count=%d chat_type=%s meta_status=%s duration_ms=%d",
            parsed.count,
            parsed.chat_type,
            parsed.meta.status,
            int((time.monotonic() - started) * 1000),
        )
        return parsed

    def _invoke(
        self,
        args: list[str],
        *,
        timeout: float,
        cancel_event: threading.Event | None = None,
        command: list[str] | None = None,
    ) -> _CommandResult:
        prefix = list(command or self.resolver.resolve())
        full_command = [*prefix, *args]
        creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        started = time.monotonic()
        try:
            process = subprocess.Popen(
                full_command,
                cwd=self.repository_root,
                env={
                    **os.environ,
                    "PYTHONUTF8": "1",
                    "PYTHONIOENCODING": "utf-8",
                },
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                creationflags=creation_flags,
            )
        except OSError as exc:
            raise WxCliError(
                code="WX_CLI_COMMAND_FAILED",
                message="无法启动项目内 wx-cli。",
                details={"exception_type": type(exc).__name__},
                retryable=True,
            ) from exc

        assert process.stdout is not None
        assert process.stderr is not None
        stdout = _PipeCollector(process.stdout, self.max_stdout_bytes)
        stderr = _PipeCollector(process.stderr, MAX_STDERR_BYTES)
        stdout.start()
        stderr.start()
        deadline = started + max(5.0, min(float(timeout), 180.0))
        while process.poll() is None:
            if cancel_event is not None and cancel_event.is_set():
                self._terminate_process_tree(process)
                raise WxCliError(
                    code="WX_CLI_CANCELLED",
                    message="微信历史记录读取任务已取消。",
                )
            if stdout.too_large.is_set() or stderr.too_large.is_set():
                self._terminate_process_tree(process)
                raise WxCliError(
                    code="WX_CLI_OUTPUT_TOO_LARGE",
                    message="wx-cli 返回内容超过安全上限，请缩小读取数量或时间范围。",
                )
            if time.monotonic() >= deadline:
                self._terminate_process_tree(process)
                raise WxCliError(
                    code="WX_CLI_TIMEOUT",
                    message="wx-cli 读取超时，请稍后重试。",
                    retryable=True,
                )
            time.sleep(0.05)

        stdout.join(timeout=2)
        stderr.join(timeout=2)
        if stdout.too_large.is_set() or stderr.too_large.is_set():
            raise WxCliError(
                code="WX_CLI_OUTPUT_TOO_LARGE",
                message="wx-cli 返回内容超过安全上限，请缩小读取数量或时间范围。",
            )
        return _CommandResult(
            returncode=int(process.returncode or 0),
            stdout=stdout.text(),
            stderr=stderr.text(),
            duration_seconds=time.monotonic() - started,
        )

    def _invoke_elevated_windows(
        self,
        command: list[str],
        args: list[str],
        *,
        timeout: float,
        cancel_event: threading.Event | None = None,
    ) -> _CommandResult:
        """Run a fixed wx-cli command through the Windows UAC boundary."""

        if sys.platform != "win32":
            raise WxCliError(
                code="WX_CLI_PERMISSION_DENIED",
                message="当前平台不支持 Windows 管理员权限初始化。",
                user_action_required=True,
            )

        import ctypes
        from ctypes import wintypes

        class ShellExecuteInfo(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("fMask", ctypes.c_ulong),
                ("hwnd", wintypes.HWND),
                ("lpVerb", wintypes.LPCWSTR),
                ("lpFile", wintypes.LPCWSTR),
                ("lpParameters", wintypes.LPCWSTR),
                ("lpDirectory", wintypes.LPCWSTR),
                ("nShow", ctypes.c_int),
                ("hInstApp", wintypes.HINSTANCE),
                ("lpIDList", ctypes.c_void_p),
                ("lpClass", wintypes.LPCWSTR),
                ("hkeyClass", wintypes.HKEY),
                ("dwHotKey", wintypes.DWORD),
                ("hIconOrMonitor", wintypes.HANDLE),
                ("hProcess", wintypes.HANDLE),
            ]

        executable = str(Path(command[0]).resolve())
        parameters = subprocess.list2cmdline([*command[1:], *args])
        info = ShellExecuteInfo()
        info.cbSize = ctypes.sizeof(info)
        info.fMask = 0x00000040  # SEE_MASK_NOCLOSEPROCESS
        info.lpVerb = "runas"
        info.lpFile = executable
        info.lpParameters = parameters
        info.lpDirectory = str(self.repository_root)
        info.nShow = 0

        started = time.monotonic()
        if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(info)):
            error_code = int(ctypes.windll.kernel32.GetLastError())
            if error_code == 1223:
                raise WxCliError(
                    code="WX_CLI_INIT_CANCELLED",
                    message="已取消 wx-cli 管理员权限初始化。",
                    user_action_required=True,
                )
            raise WxCliError(
                code="WX_CLI_PERMISSION_DENIED",
                message="无法请求 Windows 管理员权限来初始化 wx-cli。",
                details={"windows_error": error_code},
                user_action_required=True,
            )

        handle = info.hProcess
        try:
            deadline = started + max(5.0, min(float(timeout), 180.0))
            while True:
                wait_result = ctypes.windll.kernel32.WaitForSingleObject(handle, 50)
                if wait_result == 0:
                    break
                if wait_result == 0xFFFFFFFF:
                    raise WxCliError(
                        code="WX_CLI_COMMAND_FAILED",
                        message="等待 wx-cli 管理员初始化进程时发生错误。",
                        retryable=True,
                    )
                if cancel_event is not None and cancel_event.is_set():
                    ctypes.windll.kernel32.TerminateProcess(handle, 1)
                    raise WxCliError(
                        code="WX_CLI_CANCELLED",
                        message="微信任务已取消，wx-cli 初始化已终止。",
                    )
                if time.monotonic() >= deadline:
                    ctypes.windll.kernel32.TerminateProcess(handle, 1)
                    raise WxCliError(
                        code="WX_CLI_TIMEOUT",
                        message="wx-cli 自动初始化超时，请稍后重试。",
                        retryable=True,
                    )

            exit_code = wintypes.DWORD()
            if not ctypes.windll.kernel32.GetExitCodeProcess(
                handle, ctypes.byref(exit_code)
            ):
                raise WxCliError(
                    code="WX_CLI_COMMAND_FAILED",
                    message="无法获取 wx-cli 管理员初始化结果。",
                    retryable=True,
                )
            return _CommandResult(
                returncode=int(exit_code.value),
                stdout="",
                stderr="",
                duration_seconds=time.monotonic() - started,
            )
        finally:
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)

    @staticmethod
    def _terminate_process_tree(process: subprocess.Popen[bytes]) -> None:
        if process.poll() is not None:
            return
        try:
            process.terminate()
            process.wait(timeout=1)
            return
        except Exception:
            pass
        if sys.platform == "win32":
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    shell=False,
                    timeout=5,
                    check=False,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                return
            except Exception:
                pass
        try:
            process.kill()
        except Exception:
            pass

    @staticmethod
    def _parse_json_object(stdout: str) -> dict[str, Any]:
        decoder = json.JSONDecoder()
        for index, character in enumerate(stdout):
            if character != "{":
                continue
            try:
                value, _ = decoder.raw_decode(stdout[index:])
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                return value
        raise WxCliError(
            code="WX_CLI_INVALID_JSON",
            message="wx-cli 返回了无法识别的 JSON。",
            retryable=True,
        )

    @staticmethod
    def _candidate_items(
        data: dict[str, Any], requested: str, *, source: str
    ) -> list[WxChatCandidate]:
        items = _find_list(data, (source, "results", "items", "data"))
        candidates: list[WxChatCandidate] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            username = _first_string(
                item, "username", "chat_username", "user_name", "wxid"
            )
            display = _first_string(
                item,
                "display_name",
                "display",
                "name",
                "remark",
                "nickname",
                "chat",
            )
            if not username and not display:
                continue
            username = username or display
            display = display or username
            display_normalized = _normalize_name(display)
            username_normalized = _normalize_name(username)
            exact = requested in {display_normalized, username_normalized}
            if not exact and requested not in display_normalized:
                continue
            chat_type = _first_string(item, "chat_type", "type") or (
                "group" if username.endswith("@chatroom") else "private"
            )
            candidates.append(
                WxChatCandidate(
                    username=username,
                    display_name=display,
                    chat_type=chat_type,
                    exact_match=exact,
                )
            )
        return candidates

    @staticmethod
    def _parse_history(data: dict[str, Any], query: WxHistoryQuery) -> WxHistoryResult:
        raw_messages = data.get("messages")
        if not isinstance(raw_messages, list):
            raise WxCliError(
                code="WX_CLI_INVALID_JSON",
                message="wx-cli history JSON 缺少 messages 数组。",
                retryable=True,
            )
        warnings: list[str] = []
        if len(raw_messages) > query.limit:
            raw_messages = raw_messages[: query.limit]
            warnings.append("wx-cli 返回数量超过请求上限，结果已截断。")

        messages: list[WxHistoryMessage] = []
        for raw in raw_messages:
            if not isinstance(raw, dict):
                continue
            message_type = _first_string(raw, "type", "message_type") or "unknown"
            messages.append(
                WxHistoryMessage(
                    timestamp=_optional_int(raw.get("timestamp")),
                    time=_first_string(raw, "time", "datetime", "created_at"),
                    sender=_first_string(raw, "sender", "from", "display_name"),
                    content=_safe_text(raw.get("content", raw.get("text", ""))),
                    type=message_type,
                    local_id=raw.get("local_id", raw.get("id")),
                    url=_optional_string(raw.get("url")),
                    sender_username=_optional_string(raw.get("sender_username")),
                    sender_contact_display=_optional_string(
                        raw.get("sender_contact_display")
                    ),
                    sender_group_nickname=_optional_string(
                        raw.get("sender_group_nickname")
                    ),
                )
            )

        raw_meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
        status = _safe_text(raw_meta.get("status", "unknown")) or "unknown"
        unknown_shards = raw_meta.get("unknown_shards")
        if not isinstance(unknown_shards, list):
            unknown_shards = []
        meta = WxHistoryMeta(
            status=status,
            unknown_shards=tuple(_safe_text(value) for value in unknown_shards),
            chat_latest_timestamp=_optional_int(raw_meta.get("chat_latest_timestamp")),
            session_last_timestamp=_optional_int(raw_meta.get("session_last_timestamp")),
        )
        warnings.extend(_freshness_warnings(meta))
        chat_type = _first_string(data, "chat_type") or "unknown"
        return WxHistoryResult(
            chat=_first_string(data, "chat", "display_name", "name") or query.chat_name,
            username=_optional_string(data.get("username")),
            is_group=bool(data.get("is_group", chat_type == "group")),
            chat_type=chat_type,
            count=len(messages),
            messages=tuple(messages),
            meta=meta,
            warnings=tuple(dict.fromkeys(warnings)),
        )

    @staticmethod
    def _error_from_command(result: _CommandResult) -> WxCliError:
        text = f"{result.stderr}\n{result.stdout}".lower()
        if any(token in text for token in ("无法解密", "decrypt", "session.db")):
            return WxCliError(
                code="WX_CLI_DECRYPT_FAILED",
                message=(
                    "wx-cli 无法解密 session.db，当前数据库密钥可能为空或已经失效。"
                ),
                user_action_required=True,
            )
        if any(token in text for token in ("未初始化", "not initialized", "all_keys")):
            return WxCliError(
                code="WX_CLI_NOT_INITIALIZED",
                message=(
                    "wx-cli 尚未初始化。系统将在微信任务开始时自动执行 wx init；"
                    "请保持微信已登录并允许 Windows 管理员权限提示。"
                ),
                user_action_required=True,
            )
        if any(token in text for token in ("access denied", "permission denied", "权限")):
            return WxCliError(
                code="WX_CLI_PERMISSION_DENIED",
                message="wx-cli 无权读取本机微信数据，请检查初始化权限。",
                user_action_required=True,
            )
        if any(token in text for token in ("wechat not running", "微信未运行")):
            return WxCliError(
                code="WECHAT_NOT_RUNNING",
                message="微信客户端未运行，请登录微信后重试。",
                user_action_required=True,
            )
        if any(token in text for token in ("not found", "未找到", "no chat")):
            return WxCliError(
                code="CHAT_NOT_FOUND",
                message="没有找到指定的微信会话，请检查联系人备注名或群聊全名。",
                user_action_required=True,
            )
        return WxCliError(
            code="WX_CLI_COMMAND_FAILED",
            message="wx-cli 命令执行失败。",
            details={"returncode": result.returncode},
            retryable=True,
        )


def normalize_history_query(
    *,
    chat_name: Any,
    limit: Any = 50,
    offset: Any = 0,
    since: Any = None,
    until: Any = None,
    message_type: Any = None,
    today: date | None = None,
) -> tuple[WxHistoryQuery, tuple[str, ...]]:
    chat = str(chat_name or "").strip()
    if not chat or chat == "-1":
        raise WxCliError(
            code="CHAT_NAME_REQUIRED",
            message=(
                "需要指定要读取的微信联系人或群聊。例如："
                "读取我和张三最近 50 条微信聊天记录。"
            ),
            user_action_required=True,
        )
    if len(chat) > 128 or "\n" in chat or "\r" in chat:
        raise WxCliError(
            code="CHAT_NAME_REQUIRED",
            message="微信联系人或群聊名称必须为 1 到 128 个字符且不能包含换行。",
        )

    parsed_limit = _parse_integer(limit, default=50, code="INVALID_LIMIT")
    warnings: list[str] = []
    if parsed_limit < 1:
        raise WxCliError(code="INVALID_LIMIT", message="读取数量必须大于 0。")
    if parsed_limit > 500:
        parsed_limit = 500
        warnings.append("单次最多读取 500 条，本次已调整为 500 条。")

    parsed_offset = _parse_integer(offset, default=0, code="INVALID_OFFSET")
    if not 0 <= parsed_offset <= 1_000_000:
        raise WxCliError(
            code="INVALID_OFFSET", message="分页偏移量必须在 0 到 1000000 之间。"
        )

    local_today = today or datetime.now().astimezone().date()
    normalized_since = _normalize_date_value(since, today=local_today, is_until=False)
    normalized_until = _normalize_date_value(until, today=local_today, is_until=True)
    if normalized_since and normalized_until:
        if _parse_date_for_compare(normalized_since) > _parse_date_for_compare(normalized_until):
            raise WxCliError(
                code="INVALID_DATE_RANGE", message="开始时间不能晚于结束时间。"
            )

    normalized_type = str(message_type or "").strip().lower()
    if normalized_type in {"", "-1", "none", "all", "全部"}:
        normalized_type = ""
    normalized_type = MESSAGE_TYPE_MAP.get(normalized_type, normalized_type)
    if normalized_type and normalized_type not in MESSAGE_TYPES:
        raise WxCliError(
            code="INVALID_MESSAGE_TYPE",
            message="不支持该消息类型。",
        )
    return (
        WxHistoryQuery(
            chat_name=chat,
            limit=parsed_limit,
            offset=parsed_offset,
            since=normalized_since,
            until=normalized_until,
            message_type=normalized_type or None,
        ),
        tuple(warnings),
    )


def query_with_chat(query: WxHistoryQuery, chat_name: str) -> WxHistoryQuery:
    return replace(query, chat_name=chat_name)


def _parse_integer(value: Any, *, default: int, code: str) -> int:
    if value is None or str(value).strip() in {"", "None", "none"}:
        return default
    try:
        return int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise WxCliError(code=code, message="数量或分页参数必须为整数。") from exc


def _normalize_date_value(value: Any, *, today: date, is_until: bool) -> str | None:
    text = str(value or "").strip()
    if text in {"", "-1", "None", "none"}:
        return None
    text = re.sub(
        r"^(\d{4})年(\d{1,2})月(\d{1,2})日$",
        lambda match: f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}",
        text,
    )
    if text == "今天":
        return today.isoformat()
    if text == "昨天":
        day = today - timedelta(days=1)
        return day.isoformat()
    relative = re.fullmatch(r"最近\s*(\d{1,3})\s*天", text)
    if relative:
        return (today if is_until else today - timedelta(days=int(relative.group(1)) - 1)).isoformat()
    if text == "最近一周":
        return (today if is_until else today - timedelta(days=6)).isoformat()
    if text in {"最近一个月", "最近30天"}:
        return (today if is_until else today - timedelta(days=29)).isoformat()
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed.strftime(fmt)
        except ValueError:
            continue
    raise WxCliError(
        code="INVALID_DATE_RANGE",
        message="时间格式必须为 YYYY-MM-DD、YYYY-MM-DD HH:MM 或 YYYY-MM-DD HH:MM:SS。",
    )


def _parse_date_for_compare(value: str) -> datetime:
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise ValueError(value)


def _normalize_name(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip().casefold()


def _dedupe_candidates(candidates: Iterable[WxChatCandidate]) -> list[WxChatCandidate]:
    deduped: dict[tuple[str, str], WxChatCandidate] = {}
    for candidate in candidates:
        key = (candidate.username, candidate.chat_type)
        current = deduped.get(key)
        if current is None or (candidate.exact_match and not current.exact_match):
            deduped[key] = candidate
    return sorted(
        deduped.values(),
        key=lambda candidate: (not candidate.exact_match, candidate.display_name.casefold()),
    )


def _find_list(data: dict[str, Any], keys: Iterable[str]) -> list[Any]:
    for key in keys:
        value = data.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            nested = _find_list(value, ("items", "results", "data"))
            if nested:
                return nested
    return []


def _first_string(data: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = data.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return str(value)


def _optional_string(value: Any) -> str | None:
    text = _safe_text(value).strip()
    return text or None


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _freshness_warnings(meta: WxHistoryMeta) -> list[str]:
    if meta.status == "ok":
        return []
    if meta.status == "windowed":
        return ["当前结果是按数量或时间范围筛选后的局部记录。"]
    if meta.status == "possibly_stale_unknown_shards" or meta.unknown_shards:
        return [
            "检测到尚未解密的新微信数据分片，部分消息可能缺失。请以管理员身份执行 wx init --force。"
        ]
    if meta.status == "possibly_stale":
        return ["这些记录可能不是最新的，wx-cli 缓存可能尚未同步。"]
    return ["无法确认这些微信记录是否完整。"]

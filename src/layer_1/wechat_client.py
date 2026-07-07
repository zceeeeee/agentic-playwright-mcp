"""Local WeChat desktop automation helpers."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any


WECHAT_EXE_CANDIDATES = (
    r"C:\Program Files\Tencent\WeChat\WeChat.exe",
    r"C:\Program Files (x86)\Tencent\WeChat\WeChat.exe",
)
WECHAT_PROCESS_NAMES = {"wechat.exe", "wechatappex.exe"}
DEFAULT_WINDOW_RECT = (80, 60, 1200, 820)
DEFAULT_APPEX_RECT = (120, 70, 1100, 820)
CHAT_INPUT_REL = (0.58, 0.88)


class WeChatWindowManager:
    """Manage the WeChat desktop window family, including WeChatAppEx windows."""

    MAIN_CLASS = "WeChatMainWndForPC"

    def __init__(self, desktop: Any) -> None:
        self.desktop = desktop

    def list_windows(self, title_hint: str | None = None) -> list[Any]:
        return PywinautoWechatAutomation._iter_wechat_windows(
            self.desktop,
            title_hint=title_hint,
        )

    def snapshot_handles(self) -> set[int]:
        return {
            PywinautoWechatAutomation._window_handle(window)
            for window in self.list_windows()
        }

    def find_main_window(self) -> Any | None:
        windows = self.list_windows()
        for window in windows:
            try:
                if window.element_info.class_name == self.MAIN_CLASS:
                    return window
            except Exception:
                pass

        for window in windows:
            process_name = PywinautoWechatAutomation._window_process_name(window)
            title = PywinautoWechatAutomation._element_text(window)
            if process_name == "wechat.exe" and ("微信" in title or "WeChat" in title):
                return window

        return PywinautoWechatAutomation._find_window(self.desktop)

    def latest_new_appex(
        self,
        before_handles: set[int],
        *,
        title_hint: str | None = None,
        timeout: float = 6.0,
    ) -> Any | None:
        deadline = time.time() + timeout
        fallback: Any | None = None
        while time.time() < deadline:
            for window in self.list_windows(title_hint=title_hint):
                process_name = PywinautoWechatAutomation._window_process_name(window)
                if process_name != "wechatappex.exe":
                    continue
                handle = PywinautoWechatAutomation._window_handle(window)
                if handle not in before_handles:
                    return window
                if title_hint and self._window_contains(window, title_hint):
                    fallback = window
            if fallback is not None:
                return fallback
            time.sleep(0.25)
        return fallback

    def normalize(self, window: Any, *, app_ex: bool = False) -> Any:
        x, y, width, height = DEFAULT_APPEX_RECT if app_ex else DEFAULT_WINDOW_RECT
        try:
            window.restore()
        except Exception:
            pass
        try:
            window.move_window(x=x, y=y, width=width, height=height, repaint=True)
        except Exception:
            pass
        try:
            window.set_focus()
        except Exception:
            pass
        time.sleep(0.2)
        return window

    @staticmethod
    def _window_contains(window: Any, text: str) -> bool:
        if not text:
            return False
        title = PywinautoWechatAutomation._element_text(window)
        if text in title:
            return True
        try:
            descendants = window.descendants()
        except Exception:
            descendants = []
        return any(text in PywinautoWechatAutomation._element_text(item) for item in descendants[:120])


class ElementLocator:
    """Small UIA-first locator with click and relative-coordinate fallbacks."""

    def __init__(self, timeout: float = 8.0) -> None:
        self.timeout = timeout

    def descendants(self, root: Any, *, control_type: str | None = None) -> list[Any]:
        try:
            if control_type:
                return list(root.descendants(control_type=control_type))
            return list(root.descendants())
        except Exception:
            return []

    def find_by_name(
        self,
        root: Any,
        names: str | tuple[str, ...] | list[str],
        *,
        control_types: tuple[str, ...] | list[str] | None = None,
        exact: bool = False,
        timeout: float | None = None,
    ) -> Any | None:
        if isinstance(names, str):
            names = (names,)
        deadline = time.time() + (timeout if timeout is not None else self.timeout)
        while time.time() < deadline:
            for item in self.descendants(root):
                title = PywinautoWechatAutomation._element_text(item)
                if not title:
                    continue
                if control_types:
                    control_type = PywinautoWechatAutomation._element_control_type(item)
                    if control_type not in control_types:
                        continue
                for name in names:
                    if (title == name) if exact else (name in title):
                        return item
            time.sleep(0.2)
        return None

    @staticmethod
    def click(item: Any) -> None:
        last_exc: Exception | None = None
        for method_name in ("invoke", "click_input", "select"):
            try:
                getattr(item, method_name)()
                return
            except Exception as exc:
                last_exc = exc
        if last_exc:
            raise last_exc
        raise RuntimeError("Unable to click WeChat UI element")


class PywinautoWechatAutomation:
    """Small UI Automation adapter for the Windows WeChat client."""

    def __init__(self, launch_path: str | None = None, wait_timeout: float = 20.0) -> None:
        self.launch_path = launch_path
        self.wait_timeout = wait_timeout
        self.app: Any = None
        self.desktop: Any = None
        self.window: Any = None
        self.window_manager: WeChatWindowManager | None = None
        self.locator = ElementLocator(timeout=8.0)

    def open(self) -> None:
        try:
            from pywinauto import Application, Desktop  # type: ignore[import-not-found]
        except Exception as exc:  # pragma: no cover - depends on local desktop env
            raise RuntimeError(
                "WeChat desktop automation requires pywinauto. "
                "Install it in the current environment before using this skill."
            ) from exc

        self.desktop = Desktop(backend="uia")
        self.window_manager = WeChatWindowManager(self.desktop)
        self.window = self.window_manager.find_main_window()
        if self.window is not None:
            self.window = self.window_manager.normalize(self.window)
            return

        exe_path = self._resolve_executable()
        self.app = Application(backend="uia").start(str(exe_path))
        deadline = time.time() + self.wait_timeout
        while time.time() < deadline:
            self.window = self.window_manager.find_main_window()
            if self.window is not None:
                self.window = self.window_manager.normalize(self.window)
                return
            time.sleep(0.5)
        raise RuntimeError("Unable to find WeChat window after launch")

    def search_official_account(self, account_name: str) -> None:
        self._require_window()
        self._normalize_current_window()
        before_handles = self._snapshot_window_handles()
        self._send_keys("^f")
        time.sleep(0.2)
        self._send_keys("^a")
        self._paste_or_type(account_name)
        self._send_keys("{ENTER}")
        time.sleep(1.5)
        self._click_service_account_result(account_name, before_handles=before_handles)

    def search_contact(self, contact_name: str) -> None:
        self._require_window()
        self._normalize_current_window()
        self._send_keys("^f")
        time.sleep(0.2)
        self._send_keys("^a")
        self._paste_or_type(contact_name)
        time.sleep(1.2)
        self._click_contact_result(contact_name)

    def follow_current_account(self) -> bool:
        self._require_window()
        self._normalize_current_window()
        target = self._wait_for_text_target(
            title_patterns=(
                r".*关注.*",
                r".*Follow.*",
                r".*Subscribe.*",
            ),
            timeout=10.0,
        )
        clicked_follow = False
        if target is None:
            clicked_follow = False
        else:
            self._click_element_or_parent(target)
            clicked_follow = True
            time.sleep(0.8)

        enter_target = self._wait_for_text_target(
            title_patterns=(
                r".*进入公众号.*",
                r".*发消息.*",
                r".*发送消息.*",
                r".*Message.*",
            ),
            timeout=1.0,
        )
        if enter_target is not None:
            self._click_element_or_parent(enter_target)
            time.sleep(0.8)
        return clicked_follow

    def send_message(self, message: str) -> None:
        self._require_window()
        self._normalize_current_window()
        edit = self._find_message_edit()
        if edit is not None:
            edit.click_input()
        else:
            self._click_relative(self.window, *CHAT_INPUT_REL)
        self._paste_or_type(message)
        self._send_keys("{ENTER}")
        time.sleep(0.5)

    def _resolve_executable(self) -> Path:
        if self.launch_path:
            path = Path(self.launch_path).expanduser()
            if path.exists():
                return path
        for candidate in WECHAT_EXE_CANDIDATES:
            path = Path(candidate)
            if path.exists():
                return path
        raise FileNotFoundError("Unable to locate WeChat.exe")

    @classmethod
    def _find_window(
        cls,
        desktop: Any,
        title_hint: str | None = None,
        *,
        prefer_app_ex: bool = False,
    ) -> Any | None:
        candidates: list[tuple[int, int, Any]] = []
        for index, window in enumerate(cls._iter_wechat_windows(desktop, title_hint=title_hint)):
            score = 0
            title = cls._element_text(window)
            process_name = cls._window_process_name(window)
            if process_name == "wechatappex.exe" and (prefer_app_ex or title_hint):
                score += 20
            elif process_name == "wechat.exe":
                score += 6
            if title_hint and title_hint in title:
                score += 10
            if "WeChat" in title or "微信" in title:
                score += 4
            try:
                if window.is_active():
                    score += 2
            except Exception:
                pass
            candidates.append((score, index, window))

        if candidates:
            candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
            return candidates[0][2]

        return None

    @classmethod
    def _iter_wechat_windows(
        cls,
        desktop: Any,
        *,
        title_hint: str | None = None,
    ) -> list[Any]:
        if desktop is None:
            return []
        try:
            windows = desktop.windows()
        except Exception:
            return []

        result = []
        for window in windows:
            if cls._is_wechat_window(window, title_hint=title_hint):
                result.append(window)
        return result

    @classmethod
    def _is_wechat_window(cls, window: Any, title_hint: str | None = None) -> bool:
        process_name = cls._window_process_name(window)
        if process_name:
            return process_name in WECHAT_PROCESS_NAMES

        title = cls._element_text(window)
        return "微信" in title or "WeChat" in title

    @staticmethod
    def _window_process_name(window: Any) -> str:
        fake_process_name = getattr(window, "process_name", "")
        if fake_process_name:
            return str(fake_process_name).lower()

        pid = None
        try:
            pid = window.process_id()
        except Exception:
            pass
        if pid is None:
            try:
                pid = window.element_info.process_id
            except Exception:
                pid = None
        if pid is None:
            return ""
        return PywinautoWechatAutomation._process_name(int(pid))

    @staticmethod
    def _window_handle(window: Any) -> int:
        for attr in ("handle",):
            try:
                value = getattr(window, attr)
                if callable(value):
                    value = value()
                if value:
                    return int(value)
            except Exception:
                pass
        try:
            value = window.element_info.handle
            if value:
                return int(value)
        except Exception:
            pass
        return id(window)

    @staticmethod
    def _process_name(pid: int) -> str:
        try:
            import psutil  # type: ignore[import-not-found]

            return psutil.Process(pid).name().lower()
        except Exception:
            pass

        try:
            import ctypes
            from ctypes import wintypes
        except Exception:
            return ""

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        process_query_limited_information = 0x1000
        handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
        if not handle:
            return ""
        try:
            buffer = ctypes.create_unicode_buffer(32768)
            size = wintypes.DWORD(len(buffer))
            if not kernel32.QueryFullProcessImageNameW(
                handle,
                0,
                buffer,
                ctypes.byref(size),
            ):
                return ""
            return Path(buffer.value).name.lower()
        finally:
            kernel32.CloseHandle(handle)

    def _require_window(self) -> None:
        if self.window is None:
            raise RuntimeError("WeChat window is not open")

    def _normalize_current_window(self) -> None:
        self._require_window()
        manager = self._get_window_manager(create=False)
        if manager is None:
            try:
                self.window.set_focus()
            except Exception:
                pass
            return
        self.window = manager.normalize(
            self.window,
            app_ex=self._window_process_name(self.window) == "wechatappex.exe",
        )

    def _get_window_manager(self, *, create: bool = True) -> WeChatWindowManager | None:
        if self.window_manager is not None:
            return self.window_manager
        desktop = self._get_desktop(create=create)
        if desktop is None:
            return None
        self.window_manager = WeChatWindowManager(desktop)
        return self.window_manager

    def _snapshot_window_handles(self) -> set[int]:
        manager = self._get_window_manager(create=False)
        if manager is not None:
            return manager.snapshot_handles()
        return {
            self._window_handle(window)
            for window in self._windows_to_scan()
        }

    def _send_keys(self, keys: str) -> None:
        from pywinauto.keyboard import send_keys  # type: ignore[import-not-found]

        send_keys(keys, pause=0.03)

    def _paste_or_type(self, text: str) -> None:
        try:
            import pyperclip  # type: ignore[import-not-found]

            pyperclip.copy(text)
            self._send_keys("^v")
            return
        except Exception:
            pass

        from pywinauto.keyboard import send_keys  # type: ignore[import-not-found]

        send_keys(text, with_spaces=True, pause=0.03)

    def _find_first(
        self,
        *,
        control_type: str,
        title_patterns: tuple[str, ...],
    ) -> Any | None:
        import re

        self._require_window()
        try:
            descendants = self.window.descendants(control_type=control_type)
        except Exception:
            return None
        for item in descendants:
            try:
                title = item.window_text()
            except Exception:
                continue
            if any(re.search(pattern, title, re.IGNORECASE) for pattern in title_patterns):
                return item
        return None

    def _click_service_account_result(
        self,
        account_name: str,
        before_handles: set[int] | None = None,
    ) -> None:
        self._require_window()
        before_handles = before_handles or self._snapshot_window_handles()
        deadline = time.time() + 10.0
        fallback = None
        while time.time() < deadline:
            target, fallback = self._find_service_account_result(account_name)
            if target is not None:
                self._click_element_or_parent(target)
                time.sleep(1.2)
                self._switch_to_account_window(account_name, before_handles=before_handles)
                return
            time.sleep(0.4)

        if fallback is not None:
            self._click_element_or_parent(fallback)
            time.sleep(1.2)
            self._switch_to_account_window(account_name, before_handles=before_handles)
            return

        self._send_keys("{ENTER}")
        time.sleep(1.0)
        self._switch_to_account_window(account_name, before_handles=before_handles)

    def _click_contact_result(self, contact_name: str) -> None:
        self._require_window()
        deadline = time.time() + 10.0
        fallback = None
        while time.time() < deadline:
            target, fallback = self._find_contact_result(contact_name)
            if target is not None:
                self._click_element_or_parent(target)
                if self._wait_for_message_edit(timeout=2.0) is not None:
                    return
                self._send_keys("{ENTER}")
                time.sleep(0.8)
                return
            time.sleep(0.4)

        if fallback is not None:
            self._click_element_or_parent(fallback)
            if self._wait_for_message_edit(timeout=2.0) is not None:
                return
            self._send_keys("{ENTER}")
            time.sleep(0.8)
            return

        self._send_keys("{ENTER}")
        time.sleep(0.8)

    def _find_service_account_result(self, account_name: str) -> tuple[Any | None, Any | None]:
        import re

        try:
            items = self.window.descendants()
        except Exception:
            return None, None

        service_pattern = re.compile(
            r"(服务号|公众号|Official Account|Service Account)",
            re.IGNORECASE,
        )
        name_pattern = re.compile(re.escape(account_name), re.IGNORECASE)
        fallback: Any | None = None
        service_items: list[Any] = []
        name_items: list[Any] = []
        for item in items:
            title = self._element_text(item)
            if not title:
                continue
            if service_pattern.search(title):
                service_items.append(item)
            if name_pattern.search(title):
                name_items.append(item)
                fallback = fallback or self._nearest_click_target(item)

        for item in name_items:
            for container in self._candidate_containers(item):
                combined = self._combined_text(container)
                if name_pattern.search(combined) and service_pattern.search(combined):
                    return container, fallback

        for item in service_items:
            for container in self._candidate_containers(item):
                combined = self._combined_text(container)
                if name_pattern.search(combined) and service_pattern.search(combined):
                    return container, fallback

        return None, fallback

    def _find_contact_result(self, contact_name: str) -> tuple[Any | None, Any | None]:
        import re

        try:
            items = self.window.descendants()
        except Exception:
            return None, None

        name_pattern = re.compile(re.escape(contact_name), re.IGNORECASE)
        official_pattern = re.compile(
            r"(服务号|公众号|Official Account|Service Account)",
            re.IGNORECASE,
        )
        fallback: Any | None = None
        for item in items:
            if self._is_search_input(item):
                continue
            title = self._element_text(item)
            if not title or not name_pattern.search(title):
                continue
            containers = self._candidate_containers(item)
            combined_by_container = [
                (container, self._combined_text(container)) for container in containers
            ]
            if any(self._looks_like_search_container(combined) for _, combined in combined_by_container):
                continue
            if any(
                name_pattern.search(combined)
                and official_pattern.search(combined)
                for _, combined in combined_by_container
            ):
                continue
            fallback = fallback or self._nearest_click_target(item)
            for container, combined in reversed(combined_by_container):
                if name_pattern.search(combined):
                    return container, fallback

        return None, fallback

    def _wait_for_message_edit(self, timeout: float) -> Any | None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            edit = self._find_message_edit()
            if edit is not None:
                return edit
            time.sleep(0.2)
        return None

    def _wait_for_text_target(
        self,
        *,
        title_patterns: tuple[str, ...],
        timeout: float,
    ) -> Any | None:
        import re

        deadline = time.time() + timeout
        while time.time() < deadline:
            self._require_window()
            for window in self._windows_to_scan():
                try:
                    items = window.descendants()
                except Exception:
                    items = []
                for item in items:
                    title = self._element_text(item)
                    if any(
                        re.search(pattern, title, re.IGNORECASE)
                        for pattern in title_patterns
                    ):
                        self.window = window
                        try:
                            self.window.set_focus()
                        except Exception:
                            pass
                        return item
            time.sleep(0.4)
        return None

    def _switch_to_account_window(
        self,
        account_name: str,
        timeout: float = 6.0,
        before_handles: set[int] | None = None,
    ) -> bool:
        manager = self._get_window_manager(create=False)
        if manager is not None:
            new_appex = manager.latest_new_appex(
                before_handles or set(),
                title_hint=account_name,
                timeout=min(timeout, 1.5),
            )
            if new_appex is not None:
                self.window = manager.normalize(new_appex, app_ex=True)
                return True

        desktop = self._get_desktop(create=False)
        if desktop is None:
            return False
        deadline = time.time() + timeout
        fallback = None
        while time.time() < deadline:
            for window in self._iter_wechat_windows(desktop, title_hint=account_name):
                process_name = self._window_process_name(window)
                title = self._element_text(window)
                has_account_hint = bool(account_name and account_name in title)
                if not has_account_hint:
                    combined = self._combined_text(window)
                    has_account_hint = account_name in combined
                if process_name == "wechatappex.exe":
                    self.window = (
                        manager.normalize(window, app_ex=True)
                        if manager is not None
                        else window
                    )
                    return True
                if has_account_hint:
                    fallback = window
            if fallback is not None and time.time() + 0.3 >= deadline:
                self.window = (
                    manager.normalize(fallback)
                    if manager is not None
                    else fallback
                )
                return True
            time.sleep(0.3)
        if fallback is not None:
            self.window = (
                manager.normalize(fallback)
                if manager is not None
                else fallback
            )
            return True
        return False

    def _get_desktop(self, *, create: bool = True) -> Any:
        if self.desktop is not None:
            return self.desktop
        if not create:
            return None
        try:
            from pywinauto import Desktop  # type: ignore[import-not-found]
        except Exception:
            return None
        self.desktop = Desktop(backend="uia")
        return self.desktop

    def _windows_to_scan(self) -> list[Any]:
        windows: list[Any] = []
        if self.window is not None:
            windows.append(self.window)
        desktop = self._get_desktop(create=False)
        for window in self._iter_wechat_windows(desktop):
            if all(window is not existing for existing in windows):
                windows.append(window)
        return windows

    @staticmethod
    def _element_text(item: Any) -> str:
        try:
            text = item.window_text()
        except Exception:
            text = ""
        if text:
            return str(text)
        try:
            text = item.element_info.name
        except Exception:
            text = ""
        return str(text or "")

    @staticmethod
    def _element_control_type(item: Any) -> str:
        try:
            return str(item.element_info.control_type or "")
        except Exception:
            pass
        try:
            return str(item.friendly_class_name() or "")
        except Exception:
            return ""

    def _is_search_input(self, item: Any) -> bool:
        if self._element_control_type(item).lower() != "edit":
            return False
        combined = " ".join(
            self._combined_text(container) for container in self._candidate_containers(item)
        )
        if self._looks_like_search_container(combined):
            return True
        try:
            rect = item.rectangle()
            return rect.height() <= 40
        except Exception:
            return False

    @staticmethod
    def _looks_like_search_container(text: str) -> bool:
        return any(marker in text for marker in ("搜索", "Search", "search"))

    def _candidate_containers(self, item: Any, max_depth: int = 4) -> list[Any]:
        containers = [item]
        current = item
        for _ in range(max_depth):
            try:
                parent = current.parent()
            except Exception:
                break
            if parent is None:
                break
            try:
                grandparent = parent.parent()
            except Exception:
                grandparent = None
            # Avoid treating the root WeChat window as a search result row.
            if grandparent is None:
                break
            containers.append(parent)
            current = parent
        return containers

    def _combined_text(self, item: Any) -> str:
        parts = [self._element_text(item)]
        try:
            descendants = item.descendants()
        except Exception:
            descendants = []
        for descendant in descendants[:80]:
            text = self._element_text(descendant)
            if text:
                parts.append(text)
        return " ".join(parts)

    def _nearest_click_target(self, item: Any) -> Any:
        candidates = self._candidate_containers(item)
        try:
            has_children = bool(item.descendants())
        except Exception:
            has_children = False
        if not has_children and len(candidates) > 1:
            candidates = [candidates[1], *candidates]
        for candidate in candidates:
            try:
                rect = candidate.rectangle()
                if rect.width() > 20 and rect.height() > 10:
                    return candidate
            except Exception:
                continue
        return item

    def _click_element_or_parent(self, item: Any) -> None:
        last_exc: Exception | None = None
        candidates = [self._nearest_click_target(item), *self._candidate_containers(item)]
        seen: set[int] = set()
        for candidate in candidates:
            identity = id(candidate)
            if identity in seen:
                continue
            seen.add(identity)
            try:
                candidate.click_input()
                return
            except Exception as exc:
                last_exc = exc
            try:
                candidate.invoke()
                return
            except Exception as exc:
                last_exc = exc
            try:
                candidate.select()
                return
            except Exception as exc:
                last_exc = exc
        if last_exc:
            raise last_exc
        raise RuntimeError("Unable to click WeChat UI element")

    def _click_relative(self, window: Any, rx: float, ry: float) -> None:
        try:
            rect = window.rectangle()
            x = rect.left + int(rect.width() * rx)
            y = rect.top + int(rect.height() * ry)
        except Exception as exc:
            raise RuntimeError("Unable to calculate WeChat relative click point") from exc

        try:
            from pywinauto.mouse import click  # type: ignore[import-not-found]

            click(button="left", coords=(x, y))
            return
        except Exception:
            pass

        try:
            window.click_input(coords=(x, y))
        except Exception as exc:
            raise RuntimeError("Unable to click WeChat relative input area") from exc

    def _find_message_edit(self) -> Any | None:
        self._require_window()
        candidates = []
        for window in self._windows_to_scan():
            controls = []
            for control_type in ("Edit", "Document"):
                try:
                    controls.extend(window.descendants(control_type=control_type))
                except Exception:
                    continue
            for edit in controls:
                if self._is_search_input(edit):
                    continue
                score = 0
                try:
                    rect = edit.rectangle()
                    if rect.height() >= 60:
                        score += 5
                    if rect.width() >= 200:
                        score += 2
                except Exception:
                    pass
                text = self._combined_text(edit)
                if any(marker in text for marker in ("输入", "发送", "Message", "message")):
                    score += 2
                candidates.append((score, window, edit))
        if candidates:
            candidates.sort(key=lambda item: item[0], reverse=True)
            self.window = candidates[0][1]
            return candidates[0][2]
        return None


def _clean_required(value: str | None, label: str) -> str:
    text = str(value or "").strip()
    if not text or text == "-1":
        raise ValueError(f"WeChat {label} is required")
    return text


def follow_official_account(
    account_name: str,
    *,
    message: str | None = None,
    launch_path: str | None = None,
    automation: Any | None = None,
) -> dict[str, Any]:
    account = _clean_required(account_name, "official account name")
    client = automation or PywinautoWechatAutomation(launch_path=launch_path)
    client.open()
    client.search_official_account(account)
    followed = client.follow_current_account()
    sent_message = None
    if message:
        client.send_message(message)
        sent_message = message
    return {
        "success": True,
        "account_name": account,
        "follow_clicked": followed,
        "message": sent_message,
    }


def send_official_account_message(
    account_name: str,
    message: str,
    *,
    launch_path: str | None = None,
    automation: Any | None = None,
) -> dict[str, Any]:
    account = _clean_required(account_name, "official account name")
    text = _clean_required(message, "message")
    client = automation or PywinautoWechatAutomation(launch_path=launch_path)
    client.open()
    client.search_official_account(account)
    client.follow_current_account()
    client.send_message(text)
    return {"success": True, "account_name": account, "message": text}


def send_contact_message(
    contact_name: str,
    message: str,
    *,
    launch_path: str | None = None,
    automation: Any | None = None,
) -> dict[str, Any]:
    contact = _clean_required(contact_name, "contact name")
    text = _clean_required(message, "message")
    client = automation or PywinautoWechatAutomation(launch_path=launch_path)
    client.open()
    client.search_contact(contact)
    client.send_message(text)
    return {"success": True, "contact_name": contact, "message": text}

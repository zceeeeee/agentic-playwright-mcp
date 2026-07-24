"""
脚本执行引擎 —— 在受限命名空间中安全执行 AI 生成的 Python 脚本。

设计原则:
- 脚本只能调用我们显式注入的函数（控件层 + 原语层）
- 禁止 import、文件系统访问、网络请求等危险操作
- 捕获 print 输出和截图路径，返回结构化结果
"""

from __future__ import annotations

import io
import sys
import traceback
from dataclasses import dataclass, field
from functools import wraps
from typing import Any, Callable
from urllib.parse import quote_plus

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from src.core.browser_manager import get_browser_manager
from src.core.event_bus import EVENT_SCRIPT_EXECUTE, Event, Phase, get_event_bus
from src.core.login_guard import GenericLoginGuard
from src.layer_1.actions import do_click, do_fill, do_goto, do_screenshot

# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------


@dataclass
class ScriptResult:
    """脚本执行结果。"""

    success: bool
    output: str = ""
    error: str | None = None
    screenshots: list[str] = field(default_factory=list)
    return_value: Any = None


# ---------------------------------------------------------------------------
# 安全的内置函数白名单
# ---------------------------------------------------------------------------

# 只暴露安全的内置函数，移除所有危险操作
_SAFE_BUILTINS: dict[str, Any] = {
    "True": True,
    "False": False,
    "None": None,
    "bool": bool,
    "int": int,
    "float": float,
    "str": str,
    "list": list,
    "dict": dict,
    "tuple": tuple,
    "set": set,
    "len": len,
    "range": range,
    "enumerate": enumerate,
    "zip": zip,
    "map": map,
    "filter": filter,
    "sorted": sorted,
    "reversed": reversed,
    "min": min,
    "max": max,
    "sum": sum,
    "abs": abs,
    "round": round,
    "isinstance": isinstance,
    "hasattr": hasattr,
    "getattr": getattr,
    "setattr": setattr,
    "type": type,
    "ValueError": ValueError,
    "TypeError": TypeError,
    "KeyError": KeyError,
    "IndexError": IndexError,
    "Exception": Exception,
    "RuntimeError": RuntimeError,
}


# ---------------------------------------------------------------------------
# 脚本引擎
# ---------------------------------------------------------------------------


class ScriptEngine:
    """在受限命名空间中执行 AI 生成的 Python 脚本。"""

    def __init__(self, browser_manager: Any | None = None) -> None:
        self._browser_manager = browser_manager
        self._extra_globals: dict[str, Any] = {}
        self._cancel_check: Callable[[], bool] | None = None

    def register_cancel_check(self, cancel_check: Callable[[], bool] | None) -> None:
        """注册取消检查回调。"""
        self._cancel_check = cancel_check

    def _raise_if_cancelled(self) -> None:
        """检查取消信号，若已取消则抛出 TaskCancelledError。"""
        if self._cancel_check is not None and self._cancel_check():
            raise RuntimeError("任务已取消")

    def register_function(self, name: str, func: Callable) -> None:
        """注册一个函数到脚本命名空间。

        Args:
            name: 脚本中可用的函数名。
            func: 实际的函数对象。
        """
        self._extra_globals[name] = func

    def register_functions(self, functions: dict[str, Callable]) -> None:
        """批量注册函数到脚本命名空间。"""
        self._extra_globals.update(functions)

    def _get_browser_manager(self):
        if self._browser_manager is not None:
            return self._browser_manager
        return get_browser_manager()

    def execute(self, script_code: str) -> ScriptResult:
        """在受限命名空间中执行脚本。

        Args:
            script_code: Python 脚本源码。

        Returns:
            ScriptResult 包含执行状态、输出、错误信息和截图路径。
        """
        bus = get_event_bus()
        before_event = Event(
            name=EVENT_SCRIPT_EXECUTE,
            phase=Phase.BEFORE,
            data={"code": script_code},
        )
        bus.emit(before_event)
        if before_event.cancelled:
            return ScriptResult(
                success=False,
                error=f"脚本执行已取消: {before_event.metadata.get('cancel_reason', '')}",
            )

        # Allow hooks to modify the script code
        script_code = before_event.data.get("code", script_code)

        # 捕获 print 输出
        output_buffer = io.StringIO()
        old_stdout = sys.stdout

        # 收集截图路径
        screenshots: list[str] = []

        # 构建受限命名空间
        namespace = self._build_namespace(output_buffer, screenshots, script_code)

        try:
            sys.stdout = output_buffer
            self._raise_if_cancelled()
            exec(script_code, namespace)  # noqa: S102

            # 尝试获取脚本的返回值（如果有 return 语句，exec 不会捕获）
            result = ScriptResult(
                success=True,
                output=output_buffer.getvalue(),
                screenshots=screenshots,
                return_value=namespace.get("__result__", namespace.get("result")),
            )

        except Exception as exc:
            result = ScriptResult(
                success=False,
                output=output_buffer.getvalue(),
                error=f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}",
                screenshots=screenshots,
            )

        finally:
            sys.stdout = old_stdout

        bus.emit(
            Event(
                name=EVENT_SCRIPT_EXECUTE,
                phase=Phase.AFTER,
                data={"code": script_code},
                result=result,
                error=result.error if not result.success else None,
            )
        )
        return result

    def _build_namespace(
        self,
        output_buffer: io.StringIO,
        screenshots: list[str],
        script_code: str = "",
    ) -> dict[str, Any]:
        """构建受限命名空间。

        Args:
            output_buffer: 用于捕获 print 输出的 StringIO。
            screenshots: 收集截图路径的列表。

        Returns:
            受限的命名空间字典。
        """

        # 安全的 print（写入 buffer 而非 stdout）
        def safe_print(*args, **kwargs):
            kwargs["file"] = output_buffer
            print(*args, **kwargs)

        # 安全的 log（写入 buffer）
        def log(message: str):
            output_buffer.write(f"[LOG] {message}\n")

        # 安全的 screenshot（自动收集路径）
        def safe_screenshot(path: str) -> str:
            page = self._get_browser_manager().get_page()
            result = do_screenshot(page, path)
            screenshots.append(result)
            return result

        # 安全的 goto
        def safe_goto(url: str) -> str:
            page = self._get_browser_manager().get_page()
            return do_goto(page, url)

        # 安全的 click（支持选择器列表）
        def safe_click(selector: str, *fallbacks: str) -> dict:
            page = self._get_browser_manager().get_page()
            selector_list = [selector] + list(fallbacks)
            return do_click(page, selector_list)

        def safe_mouse_click(x: float, y: float) -> dict:
            page = self._get_browser_manager().get_page()
            page.mouse.move(float(x), float(y))
            page.mouse.down()
            page.mouse.up()
            return {"success": True, "x": float(x), "y": float(y)}

        def safe_mouse_move(x: float, y: float, steps: int = 1) -> dict:
            page = self._get_browser_manager().get_page()
            move_steps = max(1, int(steps))
            page.mouse.move(float(x), float(y), steps=move_steps)
            return {
                "success": True,
                "x": float(x),
                "y": float(y),
                "steps": move_steps,
            }

        def safe_hover(selector: str, *fallbacks: str) -> dict:
            page = self._get_browser_manager().get_page()
            selector_list = [selector] + list(fallbacks)
            last_error: Exception | None = None
            for item in selector_list:
                try:
                    page.locator(item).first.hover(timeout=10000)
                    return {"success": True, "selector": item}
                except Exception as exc:
                    last_error = exc
            raise RuntimeError(f"hover failed: {last_error}")

        # 安全的 fill（支持选择器列表）
        def safe_fill(selector: str, value: str, *fallbacks: str) -> dict:
            page = self._get_browser_manager().get_page()
            selector_list = [selector] + list(fallbacks)
            return do_fill(page, selector_list, value)

        # 安全的 close browser
        def safe_close_browser() -> None:
            self._get_browser_manager().close()


        # 构建命名空间
        ns: dict[str, Any] = {"__builtins__": _SAFE_BUILTINS}

        # 注入原语层函数
        ns["goto"] = safe_goto
        ns["click"] = safe_click
        ns["mouse_click"] = safe_mouse_click
        ns["mouse_move"] = safe_mouse_move
        ns["hover"] = safe_hover
        ns["fill"] = safe_fill
        ns["screenshot"] = safe_screenshot
        ns["close_browser"] = safe_close_browser

        # 注入工具函数
        ns["print"] = safe_print
        ns["log"] = log
        ns["url_quote"] = quote_plus

        # 注入页面状态函数
        ns["get_url"] = lambda: self._get_browser_manager().get_page().url
        ns["get_title"] = lambda: self._get_browser_manager().get_page().title()

        # 注入面板交互函数
        from src.panel import get_panel_manager
        _pm = get_panel_manager()

        def panel_log(message: str) -> None:
            """向桌面交互面板写入日志。"""
            _pm.log(None, str(message))

        def panel_prompt(question: str) -> str:
            """向用户提问并等待回答。"""
            return _pm.prompt(None, str(question))

        def panel_offer(
            question: str,
            on_resolve: Callable[[dict[str, Any]], None] | None = None,
        ) -> str | None:
            """Show a desktop confirmation without pausing script execution."""
            return _pm.offer(
                None,
                str(question),
                on_resolve=on_resolve,
            )

        def panel_read() -> dict:
            """读取用户通过面板输入的最新数据。"""
            return _pm.read_data(None) or {}

        def panel_read_events() -> list:
            """读取并清空面板事件队列。"""
            return _pm.read_events(None)

        def panel_show() -> None:
            """显示面板。"""
            _pm.toggle(None, True)

        def panel_hide() -> None:
            """隐藏面板。"""
            _pm.toggle(None, False)

        def panel_set_title(text: str) -> None:
            """设置面板标题。"""
            _pm.set_title(None, str(text))

        def panel_set_fields(fields: list) -> None:
            """动态更新面板表单字段。"""
            _pm.set_fields(None, fields)

        def llm_generate_text(prompt: str) -> str:
            """Generate free-form text with the configured LLM."""
            from src.core.llm_client import get_llm_client

            client = get_llm_client()
            if not client.available:
                raise RuntimeError("LLM API key is not configured")
            text = client.chat(str(prompt), temperature=0.7, max_tokens=4096)
            text = str(text or "").strip()
            if not text:
                raise RuntimeError("LLM returned empty text")
            return text

        def _storage_state_logged_in(domain: str) -> bool:
            bm = self._get_browser_manager()
            if bm._context is None:
                return False
            state = bm._context.storage_state()
            cookies = {
                str(cookie.get("name", "")).lower(): str(cookie.get("value", "")).strip()
                for cookie in state.get("cookies", [])
            }
            domain = domain.lower()
            if domain == "zhihu":
                return bool(cookies.get("z_c0"))
            if domain == "xiaohongshu":
                return bool(
                    cookies.get("web_session")
                    and cookies.get("id_token")
                    and cookies.get("x-rednote-datactry")
                    and cookies.get("x-rednote-holderctry")
                )
            if domain == "taobao":
                has_identity = bool(
                    cookies.get("tracknick")
                    or cookies.get("_nk_")
                    or cookies.get("lgc")
                )
                has_session = bool(cookies.get("cookie2") or cookies.get("unb"))
                return has_identity and has_session
            if domain == "boss":
                # wt2 = 用户会话, wbp_cst = 认证 token
                return bool(cookies.get("wt2") or cookies.get("wbp_cst"))
            auth_words = (
                "auth",
                "login",
                "session",
                "token",
                "uid",
                "user",
                "account",
                "passport",
                "sso",
            )
            if any(any(word in name for word in auth_words) for name in cookies):
                return True
            for origin in state.get("origins", []):
                for item in origin.get("localStorage", []):
                    name = str(item.get("name", "")).lower()
                    if any(word in name for word in auth_words):
                        return True
            return False

        login_guard = GenericLoginGuard(
            self._get_browser_manager().get_page,
            browser_manager=self._get_browser_manager(),
            log_fn=log,
            panel_manager_getter=lambda: _pm,
            enabled=not GenericLoginGuard.script_has_explicit_login_flow(script_code),
        )
        auth_decisions: dict[str, str] = {}

        def _guarded_browser_action(action_name: str, func: Callable) -> Callable:
            @wraps(func)
            def wrapper(*args, **kwargs):
                if action_name not in {"goto", "go_back", "go_forward", "reload"}:
                    login_guard.maybe_wait(f"before_{action_name}")
                result = func(*args, **kwargs)
                login_guard.maybe_wait(f"after_{action_name}")
                return result

            return wrapper

        def _wait_for_manual_login(domain: str, target_url: str | None = None) -> bool:
            bm = self._get_browser_manager()
            page = bm.get_page()
            if target_url:
                log(f"Open {target_url} and wait for {domain} login")
                try:
                    page.goto(target_url, wait_until="domcontentloaded", timeout=10000)
                except PlaywrightTimeoutError:
                    log(f"Navigation to {target_url} timed out; keep waiting for login")
            else:
                log(f"Wait for {domain} login on current page")

            while True:
                self._raise_if_cancelled()
                if _storage_state_logged_in(domain):
                    log(f"{domain} login detected")
                    return True
                page.wait_for_timeout(1000)

        def _offer_to_save_manual_login(domain: str) -> None:
            """Capture auth now and offer to persist it without blocking the task."""
            bm = self._get_browser_manager()
            try:
                if bm._context is None:
                    raise RuntimeError("no active browser context")
                state = bm._context.storage_state()
            except Exception as exc:
                log(f"Failed to capture login information for {domain}: {exc}")
                return

            def save_if_approved(resolution: dict[str, Any]) -> None:
                answer = str(resolution.get("value") or "").strip().lower()
                wants_save = bool(resolution.get("approved")) and answer in {
                    "yes",
                    "y",
                    "1",
                    "true",
                    "是",
                }
                if not wants_save:
                    log(f"User chose not to save login for {domain}")
                    return
                try:
                    from src.core.auth_manager import get_auth_manager

                    get_auth_manager().save_state(domain, state)
                    log(f"Saved login information for {domain}")
                except Exception as exc:
                    log(f"Failed to save login information for {domain}: {exc}")

            confirmation_id = panel_offer(
                f"检测到 {domain} 已完成手动登录。"
                "是否保存这次登录信息，供后续任务使用？[yes] [no]",
                save_if_approved,
            )
            if confirmation_id is None:
                log(f"Skipped login save prompt for {domain}: desktop UI is unavailable")
                return
            auth_decisions[domain] = "manual_save_pending"
            log(f"Login save choice for {domain} is waiting in the background")

        def ensure_auth(
            domain: str,
            target_url: str | None = None,
            wait_for_manual: bool = True,
        ) -> bool:
            """Prepare auth once, and defer manual-login waiting when requested."""
            domain = str(domain or "").strip().lower()
            target_url = str(target_url or "").strip() or None
            if not domain:
                log("ensure_auth skipped: empty domain")
                return False

            from src.core.auth_manager import get_auth_manager

            am = get_auth_manager()

            bm = self._get_browser_manager()
            decision = auth_decisions.get(domain)
            if decision is None and am.has_auth(domain):
                answer = panel_prompt(
                    f"Load saved login for {domain} before continuing? [yes] [no]"
                )
                if str(answer or "").strip().lower() in {"yes", "y", "1", "true", "\u662f"}:
                    if not _storage_state_logged_in(domain):
                        bm.apply_auth_to_current_context(domain=domain)
                    if _storage_state_logged_in(domain):
                        auth_decisions[domain] = "loaded"
                        log(f"Loaded saved login for {domain}")
                        return True
                    log(
                        f"Saved login for {domain} was loaded but login state was not confirmed"
                    )
                    auth_decisions[domain] = "manual"
                else:
                    auth_decisions[domain] = "manual"
                    bm.start_clean_context()
                    log(f"User skipped saved login for {domain}")
            elif decision is None:
                if _storage_state_logged_in(domain):
                    auth_decisions[domain] = "logged_in"
                    log(f"{domain} login already loaded")
                    return True
                auth_decisions[domain] = "manual"
                log(f"No saved login info for {domain}")
            elif _storage_state_logged_in(domain):
                log(f"{domain} manual login detected")
                return True

            if not wait_for_manual:
                return False
            logged_in = _wait_for_manual_login(domain, target_url)
            if logged_in:
                _offer_to_save_manual_login(domain)
            return logged_in

        ns["panel_log"] = panel_log
        ns["panel_prompt"] = panel_prompt
        ns["panel_offer"] = panel_offer
        ns["panel_read"] = panel_read
        ns["panel_read_events"] = panel_read_events
        ns["panel_show"] = panel_show
        ns["panel_hide"] = panel_hide
        ns["panel_set_title"] = panel_set_title
        ns["panel_set_fields"] = panel_set_fields
        ns["ensure_auth"] = ensure_auth
        ns["llm_generate_text"] = llm_generate_text

        # 注册用户自定义函数（控件层等）
        ns.update(self._extra_globals)

        guarded_action_names = {
            "goto",
            "click",
            "fill",
            "go_back",
            "go_forward",
            "reload",
            "smart_click",
            "smart_fill",
            "smart_login",
            "smart_search",
            "smart_fill_form",
            "wait_for_navigation",
            "wait_for_element",
            "mouse_click",
            "mouse_move",
            "hover",
            "type_text",
            "press_key",
            "taobao_collect_products",
            "upload_file",
        }
        for action_name in guarded_action_names:
            func = ns.get(action_name)
            if callable(func):
                ns[action_name] = _guarded_browser_action(action_name, func)

        return ns


# ---------------------------------------------------------------------------
# 全局单例
# ---------------------------------------------------------------------------

_instance: ScriptEngine | None = None


def get_script_engine() -> ScriptEngine:
    """获取全局单例 ScriptEngine 实例。"""
    global _instance
    if _instance is None:
        _instance = ScriptEngine()
    return _instance


def reset_script_engine() -> None:
    """重置全局单例（用于测试）。"""
    global _instance
    _instance = None

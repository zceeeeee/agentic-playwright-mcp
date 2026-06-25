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
from typing import Any, Callable
from urllib.parse import quote_plus

from src.core.browser_manager import get_browser_manager
from src.core.event_bus import EVENT_SCRIPT_EXECUTE, Event, Phase, get_event_bus
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

    def __init__(self) -> None:
        self._extra_globals: dict[str, Any] = {}

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
        namespace = self._build_namespace(output_buffer, screenshots)

        try:
            sys.stdout = output_buffer
            exec(script_code, namespace)  # noqa: S102

            # 尝试获取脚本的返回值（如果有 return 语句，exec 不会捕获）
            result = ScriptResult(
                success=True,
                output=output_buffer.getvalue(),
                screenshots=screenshots,
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
            page = get_browser_manager().get_page()
            result = do_screenshot(page, path)
            screenshots.append(result)
            return result

        # 安全的 goto
        def safe_goto(url: str) -> str:
            page = get_browser_manager().get_page()
            return do_goto(page, url)

        # 安全的 click（支持选择器列表）
        def safe_click(selector: str, *fallbacks: str) -> dict:
            page = get_browser_manager().get_page()
            selector_list = [selector] + list(fallbacks)
            return do_click(page, selector_list)

        # 安全的 fill（支持选择器列表）
        def safe_fill(selector: str, value: str, *fallbacks: str) -> dict:
            page = get_browser_manager().get_page()
            selector_list = [selector] + list(fallbacks)
            return do_fill(page, selector_list, value)

        # 构建命名空间
        ns: dict[str, Any] = {"__builtins__": _SAFE_BUILTINS}

        # 注入原语层函数
        ns["goto"] = safe_goto
        ns["click"] = safe_click
        ns["fill"] = safe_fill
        ns["screenshot"] = safe_screenshot

        # 注入工具函数
        ns["print"] = safe_print
        ns["log"] = log
        ns["url_quote"] = quote_plus

        # 注入页面状态函数
        ns["get_url"] = lambda: get_browser_manager().get_page().url
        ns["get_title"] = lambda: get_browser_manager().get_page().title()

        # 注册用户自定义函数（控件层等）
        ns.update(self._extra_globals)

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

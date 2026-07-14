"""
Layer 2 — 控件层（Controls）。

提供高级浏览器操作函数，供脚本引擎注入到受限命名空间。
每个函数内部组合 Layer 1 原语 + Layer 3 域配置，对脚本作者透明。

所有函数从脚本中直接调用，不需要关心底层实现。
"""

from __future__ import annotations

import time

# ---------------------------------------------------------------------------
# 路径常量
# ---------------------------------------------------------------------------
from pathlib import Path
from typing import Any, Dict

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from src.core.browser_manager import get_browser_manager
from src.core.event_bus import (
    EVENT_GO_BACK,
    EVENT_GO_FORWARD,
    EVENT_RELOAD,
    EVENT_SMART_CLICK,
    EVENT_SMART_FILL,
    Event,
    Phase,
    get_event_bus,
)
from src.layer_1.actions import do_click, do_fill, do_goto, do_screenshot
from src.layer_3.config_updater import update_selector_priority
from src.layer_3.domain_loader import get_element_selectors, load_domain

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_DOMAINS_DIR = str(_PROJECT_ROOT / "domains")


# ---------------------------------------------------------------------------
# 导航类
# ---------------------------------------------------------------------------


def goto(url: str) -> str:
    """导航到指定 URL。

    Args:
        url: 目标网址。

    Returns:
        导航结果描述。
    """
    page = get_browser_manager().get_page()
    return do_goto(page, url)


def go_back() -> str:
    """浏览器后退。

    Returns:
        操作结果描述。
    """
    bus = get_event_bus()
    page = get_browser_manager().get_page()
    event = Event(name=EVENT_GO_BACK, phase=Phase.BEFORE, data={"page_url": page.url})
    bus.emit(event)
    if event.cancelled:
        return f"后退已取消: {event.metadata.get('cancel_reason', '')}"
    try:
        page.go_back(wait_until="domcontentloaded")
        result = f"后退成功: {page.url}"
    except Exception as exc:
        result = f"后退失败: {exc}"
    bus.emit(
        Event(
            name=EVENT_GO_BACK,
            phase=Phase.AFTER,
            data={"page_url": page.url},
            result=result,
        )
    )
    return result


def go_forward() -> str:
    """浏览器前进。

    Returns:
        操作结果描述。
    """
    bus = get_event_bus()
    page = get_browser_manager().get_page()
    event = Event(
        name=EVENT_GO_FORWARD, phase=Phase.BEFORE, data={"page_url": page.url}
    )
    bus.emit(event)
    if event.cancelled:
        return f"前进已取消: {event.metadata.get('cancel_reason', '')}"
    try:
        page.go_forward(wait_until="domcontentloaded")
        result = f"前进成功: {page.url}"
    except Exception as exc:
        result = f"前进失败: {exc}"
    bus.emit(
        Event(
            name=EVENT_GO_FORWARD,
            phase=Phase.AFTER,
            data={"page_url": page.url},
            result=result,
        )
    )
    return result


def reload_page() -> str:
    """刷新当前页面。

    Returns:
        操作结果描述。
    """
    bus = get_event_bus()
    page = get_browser_manager().get_page()
    event = Event(name=EVENT_RELOAD, phase=Phase.BEFORE, data={"page_url": page.url})
    bus.emit(event)
    if event.cancelled:
        return f"刷新已取消: {event.metadata.get('cancel_reason', '')}"
    try:
        page.reload(wait_until="domcontentloaded")
        result = f"刷新成功: {page.url}"
    except Exception as exc:
        result = f"刷新失败: {exc}"
    bus.emit(
        Event(
            name=EVENT_RELOAD,
            phase=Phase.AFTER,
            data={"page_url": page.url},
            result=result,
        )
    )
    return result


# ---------------------------------------------------------------------------
# 元素操作类（域配置驱动）
# ---------------------------------------------------------------------------


def smart_click(
    element_name: str,
    domain: str = "default",
) -> dict:
    """通过域配置点击元素（自愈机制）。

    加载 domains/{domain}.yaml，按优先级尝试选择器。
    如果备用选择器成功，自动提升优先级。

    Args:
        element_name: 域配置中的元素名，如 'search_button'。
        domain: 域配置文件名（不含 .yaml）。

    Returns:
        dict: success, used_selector, index, healed。
    """
    bus = get_event_bus()
    before_event = Event(
        name=EVENT_SMART_CLICK,
        phase=Phase.BEFORE,
        data={"element_name": element_name, "domain": domain},
    )
    bus.emit(before_event)
    if before_event.cancelled:
        return {
            "success": False,
            "error": f"smart_click 已取消: {before_event.metadata.get('cancel_reason', '')}",
        }

    # Allow hooks to modify element_name and domain
    element_name = before_event.data.get("element_name", element_name)
    domain = before_event.data.get("domain", domain)

    page = get_browser_manager().get_page()

    try:
        domain_config = load_domain(domain, domains_dir=_DOMAINS_DIR)
    except FileNotFoundError as exc:
        return {"success": False, "error": f"域配置加载失败: {exc}"}
    except Exception as exc:
        return {"success": False, "error": f"域配置解析错误: {exc}"}

    try:
        selector_list = get_element_selectors(domain_config, element_name)
    except ValueError as exc:
        return {"success": False, "error": str(exc)}

    if not selector_list:
        return {"success": False, "error": f"元素 '{element_name}' 选择器列表为空"}

    result = do_click(page, selector_list)

    if not result.get("success"):
        final = {"success": False, "error": result.get("error", "未知错误")}
        bus.emit(
            Event(
                name=EVENT_SMART_CLICK,
                phase=Phase.AFTER,
                data=before_event.data,
                result=final,
            )
        )
        return final

    # 自愈：提升备用选择器优先级
    healed = False
    if result["index"] > 0:
        healed = update_selector_priority(
            domain_name=domain,
            element_name=element_name,
            successful_selector=result["used_selector"],
            domains_dir=_DOMAINS_DIR,
        )

    final = {
        "success": True,
        "used_selector": result["used_selector"],
        "index": result["index"],
        "healed": healed,
    }
    bus.emit(
        Event(
            name=EVENT_SMART_CLICK,
            phase=Phase.AFTER,
            data=before_event.data,
            result=final,
        )
    )
    return final


def smart_fill(
    element_name: str,
    value: str,
    domain: str = "default",
) -> dict:
    """通过域配置填写输入框（自愈机制）。

    Args:
        element_name: 域配置中的元素名。
        value: 要填写的文本。
        domain: 域配置文件名（不含 .yaml）。

    Returns:
        dict: success, used_selector, index, healed。
    """
    bus = get_event_bus()
    before_event = Event(
        name=EVENT_SMART_FILL,
        phase=Phase.BEFORE,
        data={"element_name": element_name, "value": value, "domain": domain},
    )
    bus.emit(before_event)
    if before_event.cancelled:
        return {
            "success": False,
            "error": f"smart_fill 已取消: {before_event.metadata.get('cancel_reason', '')}",
        }

    # Allow hooks to modify parameters
    element_name = before_event.data.get("element_name", element_name)
    value = before_event.data.get("value", value)
    domain = before_event.data.get("domain", domain)

    page = get_browser_manager().get_page()

    try:
        domain_config = load_domain(domain, domains_dir=_DOMAINS_DIR)
    except FileNotFoundError as exc:
        return {"success": False, "error": f"域配置加载失败: {exc}"}
    except Exception as exc:
        return {"success": False, "error": f"域配置解析错误: {exc}"}

    try:
        selector_list = get_element_selectors(domain_config, element_name)
    except ValueError as exc:
        return {"success": False, "error": str(exc)}

    if not selector_list:
        return {"success": False, "error": f"元素 '{element_name}' 选择器列表为空"}

    result = do_fill(page, selector_list, value)

    if not result.get("success"):
        final = {"success": False, "error": result.get("error", "未知错误")}
        bus.emit(
            Event(
                name=EVENT_SMART_FILL,
                phase=Phase.AFTER,
                data=before_event.data,
                result=final,
            )
        )
        return final

    healed = False
    if result["index"] > 0:
        healed = update_selector_priority(
            domain_name=domain,
            element_name=element_name,
            successful_selector=result["used_selector"],
            domains_dir=_DOMAINS_DIR,
        )

    final = {
        "success": True,
        "used_selector": result["used_selector"],
        "index": result["index"],
        "healed": healed,
    }
    bus.emit(
        Event(
            name=EVENT_SMART_FILL,
            phase=Phase.AFTER,
            data=before_event.data,
            result=final,
        )
    )
    return final


# ---------------------------------------------------------------------------
# 组合操作类
# ---------------------------------------------------------------------------


def smart_login(
    domain: str,
    username: str,
    password: str,
    username_field: str = "username",
    password_field: str = "password",
    submit_field: str = "submit",
) -> dict:
    """自动登录流程：填写用户名密码并提交。

    Args:
        domain: 域配置文件名。
        username: 用户名。
        password: 密码。
        username_field: 用户名输入框的域配置元素名。
        password_field: 密码输入框的域配置元素名。
        submit_field: 提交按钮的域配置元素名。

    Returns:
        dict: success, steps（每步结果列表）。
    """
    steps = []

    # 1. 导航到 base_url
    try:
        domain_config = load_domain(domain, domains_dir=_DOMAINS_DIR)
    except Exception as exc:
        return {"success": False, "error": f"域配置加载失败: {exc}", "steps": steps}

    if domain_config.base_url:
        nav_result = goto(domain_config.base_url)
        steps.append({"step": "navigate", "result": nav_result})

    # 2. 填写用户名
    username_result = smart_fill(username_field, username, domain)
    steps.append({"step": "fill_username", "result": username_result})
    if not username_result.get("success"):
        return {"success": False, "error": "填写用户名失败", "steps": steps}

    # 3. 填写密码
    password_result = smart_fill(password_field, password, domain)
    steps.append({"step": "fill_password", "result": password_result})
    if not password_result.get("success"):
        return {"success": False, "error": "填写密码失败", "steps": steps}

    # 4. 点击提交
    submit_result = smart_click(submit_field, domain)
    steps.append({"step": "click_submit", "result": submit_result})
    if not submit_result.get("success"):
        return {"success": False, "error": "点击提交失败", "steps": steps}

    # 5. 等待页面跳转
    wait_result = wait_for_navigation()
    steps.append({"step": "wait_navigation", "result": wait_result})

    # 6. 登录成功，自动保存 cookie
    try:
        from src.core.auth_manager import get_auth_manager

        bm = get_browser_manager()
        if bm._context is not None:
            am = get_auth_manager()
            am.save_auth(domain, bm._context)
            steps.append(
                {"step": "save_cookies", "result": f"已保存 {domain} 的登录状态"}
            )
    except Exception as exc:
        steps.append({"step": "save_cookies", "result": f"保存失败: {exc}"})

    return {"success": True, "steps": steps}


def smart_search(
    domain: str,
    keyword: str,
    input_field: str = "search_input",
    submit_field: str = "search_button",
) -> dict:
    """自动搜索流程：在搜索框输入关键词并点击搜索。

    Args:
        domain: 域配置文件名。
        keyword: 搜索关键词。
        input_field: 搜索框的域配置元素名。
        submit_field: 搜索按钮的域配置元素名。

    Returns:
        dict: success, steps。
    """
    steps = []

    # 1. 导航到 base_url
    try:
        domain_config = load_domain(domain, domains_dir=_DOMAINS_DIR)
    except Exception as exc:
        return {"success": False, "error": f"域配置加载失败: {exc}", "steps": steps}

    if domain_config.base_url:
        nav_result = goto(domain_config.base_url)
        steps.append({"step": "navigate", "result": nav_result})

    # 2. 填写搜索框
    fill_result = smart_fill(input_field, keyword, domain)
    steps.append({"step": "fill_search", "result": fill_result})
    if not fill_result.get("success"):
        return {"success": False, "error": "填写搜索框失败", "steps": steps}

    # 3. 点击搜索按钮
    click_result = smart_click(submit_field, domain)
    steps.append({"step": "click_search", "result": click_result})
    if not click_result.get("success"):
        return {"success": False, "error": "点击搜索按钮失败", "steps": steps}

    # 4. 等待页面跳转
    wait_result = wait_for_navigation()
    steps.append({"step": "wait_navigation", "result": wait_result})

    return {"success": True, "steps": steps}


def smart_fill_form(
    domain: str,
    field_values: Dict[str, str],
) -> dict:
    """批量填写表单。

    Args:
        domain: 域配置文件名。
        field_values: {元素名: 值} 字典，如 {"username": "admin", "password": "123"}。

    Returns:
        dict: success, results（每个字段的填写结果）。
    """
    results = {}

    for element_name, value in field_values.items():
        fill_result = smart_fill(element_name, value, domain)
        results[element_name] = fill_result
        if not fill_result.get("success"):
            return {
                "success": False,
                "error": f"填写 '{element_name}' 失败",
                "results": results,
            }

    return {"success": True, "results": results}


# ---------------------------------------------------------------------------
# 等待类
# ---------------------------------------------------------------------------


def wait_for_navigation(timeout: int = 10) -> str:
    """等待页面导航完成。

    Args:
        timeout: 超时秒数。

    Returns:
        操作结果描述。
    """
    page = get_browser_manager().get_page()
    try:
        page.wait_for_load_state("domcontentloaded", timeout=timeout * 1000)
        return f"页面加载完成: {page.url}"
    except PlaywrightTimeoutError:
        return f"等待超时 ({timeout}s)"
    except Exception as exc:
        return f"等待失败: {exc}"


def wait_for_element(
    selector: str,
    timeout: int = 10,
    state: str = "visible",
) -> str:
    """等待元素出现。

    Args:
        selector: CSS 或 XPath 选择器。
        timeout: 超时秒数。
        state: 等待状态 ('visible', 'hidden', 'attached', 'detached')。

    Returns:
        操作结果描述。
    """
    page = get_browser_manager().get_page()
    try:
        page.wait_for_selector(selector, state=state, timeout=timeout * 1000)
        return f"元素已出现: {selector}"
    except PlaywrightTimeoutError:
        return f"等待元素超时 ({timeout}s): {selector}"
    except Exception as exc:
        return f"等待元素失败: {exc}"


def wait(seconds: float) -> str:
    """等待指定秒数。

    Args:
        seconds: 等待秒数。

    Returns:
        操作结果描述。
    """
    time.sleep(seconds)
    return f"已等待 {seconds} 秒"


# ---------------------------------------------------------------------------
# 页面信息类
# ---------------------------------------------------------------------------

def run_js(code: str) -> Any:
    """在页面中执行 JavaScript 代码。

    Args:
        code: JavaScript 代码字符串。

    Returns:
        JavaScript 执行结果。
    """
    page = get_browser_manager().get_page()
    return page.evaluate(code)


def mouse_click(x: float, y: float) -> dict:
    """Click the current page at viewport coordinates."""
    page = get_browser_manager().get_page()
    try:
        click_x = float(x)
        click_y = float(y)
        page.mouse.click(click_x, click_y)
        return {"success": True, "x": click_x, "y": click_y}
    except Exception as exc:
        return {"success": False, "error": f"{type(exc).__name__}: {exc}"}


def type_text(text: str) -> dict:
    """Type text into the currently focused element using browser keyboard events."""
    page = get_browser_manager().get_page()
    try:
        value = str(text)
        page.keyboard.type(value)
        return {"success": True, "text_length": len(value)}
    except Exception as exc:
        return {"success": False, "error": f"{type(exc).__name__}: {exc}"}


def press_key(key: str) -> dict:
    """Press a keyboard key in the current page."""
    page = get_browser_manager().get_page()
    try:
        page.keyboard.press(str(key))
        return {"success": True, "key": str(key)}
    except Exception as exc:
        return {"success": False, "error": f"{type(exc).__name__}: {exc}"}


def upload_file(selector: str, file_path: str) -> dict:
    """Set a local file path on a file input in the current page."""
    page = get_browser_manager().get_page()
    try:
        path = Path(file_path).expanduser()
        if not path.is_absolute():
            path = (_PROJECT_ROOT / path).resolve()
        else:
            path = path.resolve()
        if not path.exists():
            return {
                "success": False,
                "error": f"File not found: {path}",
                "selector": selector,
                "file_path": str(path),
            }
        page.set_input_files(selector, str(path))
        return {"success": True, "selector": selector, "file_path": str(path)}
    except Exception as exc:
        return {
            "success": False,
            "error": f"{type(exc).__name__}: {exc}",
            "selector": selector,
            "file_path": file_path,
        }


def get_page_url() -> str:
    """获取当前页面 URL。"""
    return get_browser_manager().get_page().url


def get_page_title() -> str:
    """获取当前页面标题。"""
    return get_browser_manager().get_page().title()


def get_page_text() -> str:
    """提取页面可见文本内容。

    Returns:
        页面 body 的 innerText。
    """
    page = get_browser_manager().get_page()
    try:
        return page.evaluate("document.body.innerText")
    except Exception as exc:
        return f"提取文本失败: {exc}"


def screenshot(path: str) -> str:
    """对当前页面截图。

    Args:
        path: 截图保存路径。

    Returns:
        保存的文件路径。
    """
    page = get_browser_manager().get_page()
    return do_screenshot(page, path)


# ---------------------------------------------------------------------------
# Cookie 持久化（供脚本引擎调用）
# ---------------------------------------------------------------------------


def save_cookies(domain: str) -> str:
    """保存当前站点的 cookie / localStorage。

    Args:
        domain: 站点名（对应 domains/{domain}.yaml）。

    Returns:
        操作结果描述。
    """
    from src.core.auth_manager import get_auth_manager

    bm = get_browser_manager()
    if bm._context is None:
        return "保存失败: 浏览器未启动"

    am = get_auth_manager()
    am.save_auth(domain, bm._context)
    return f"已保存 {domain} 的登录状态"


def load_cookies(domain: str) -> str:
    """加载指定站点的 cookie / localStorage（需重启 context）。

    Args:
        domain: 站点名（对应 domains/{domain}.yaml）。

    Returns:
        操作结果描述。
    """
    from src.core.auth_manager import get_auth_manager

    am = get_auth_manager()
    if not am.has_auth(domain):
        return f"未找到 {domain} 的登录状态"

    bm = get_browser_manager()
    if not bm.is_alive():
        return "加载失败: 浏览器未启动"

    bm.launch_with_domain(domain)
    return f"已加载 {domain} 的登录状态"


# ---------------------------------------------------------------------------
# 导出函数列表（供脚本引擎注入）
# ---------------------------------------------------------------------------


def wps_writer_export(
    title: str,
    body: str,
    output_dir: str | None = None,
    docx_path: str | None = None,
    pdf_path: str | None = None,
    file_name: str | None = None,
    markdown_path: str | None = None,
    font_name: str | None = None,
    font_size: int | str | None = None,
    font_color: int | str | None = None,
    italic: bool | str | None = None,
    image_path: str | None = None,
    keep_open: bool = True,
) -> dict:
    """Create a WPS Writer/Word document and export it as PDF."""
    from src.layer_1.wps_writer import export_article_to_pdf

    return export_article_to_pdf(
        title=title,
        body=body,
        output_dir=output_dir,
        docx_path=docx_path,
        pdf_path=pdf_path,
        file_name=file_name,
        markdown_path=markdown_path,
        font_name=font_name,
        font_size=font_size,
        font_color=font_color,
        italic=italic,
        image_path=image_path,
        keep_open=keep_open,
    )


def wechat_follow_official_account(
    account_name: str,
    message: str | None = None,
    launch_path: str | None = None,
) -> dict:
    """Search and follow a WeChat official/service account in the desktop client."""
    from src.layer_1.wechat_client import follow_official_account

    return follow_official_account(
        account_name=account_name,
        message=message,
        launch_path=launch_path,
    )


def wechat_send_official_account_message(
    account_name: str,
    message: str,
    launch_path: str | None = None,
) -> dict:
    """Send a private message to a WeChat official/service account."""
    from src.layer_1.wechat_client import send_official_account_message

    return send_official_account_message(
        account_name=account_name,
        message=message,
        launch_path=launch_path,
    )


def wechat_send_contact_message(
    contact_name: str,
    message: str,
    launch_path: str | None = None,
) -> dict:
    """Send a message to a WeChat contact in the desktop client."""
    from src.layer_1.wechat_client import send_contact_message

    return send_contact_message(
        contact_name=contact_name,
        message=message,
        launch_path=launch_path,
    )


def wechat_send_contact_file(
    recipient_name: str,
    file_path: str,
    launch_path: str | None = None,
) -> dict:
    """Send one local file to a verified WeChat contact or group."""
    from src.core.user_interaction import get_user_interaction_broker
    from src.layer_1.wechat_client import send_contact_file

    return send_contact_file(
        recipient_name=recipient_name,
        file_path=file_path,
        launch_path=launch_path,
        log_fn=get_user_interaction_broker().log,
    )


def get_controls_exports() -> Dict[str, Any]:
    """返回控件层所有可导出的函数。

    Returns:
        {函数名: 函数对象} 字典，用于注入脚本引擎命名空间。
    """
    return {
        # 导航
        "goto": goto,
        "go_back": go_back,
        "go_forward": go_forward,
        "reload": reload_page,
        # 元素操作（域配置驱动）
        "smart_click": smart_click,
        "smart_fill": smart_fill,
        # 组合操作
        "smart_login": smart_login,
        "smart_search": smart_search,
        "smart_fill_form": smart_fill_form,
        # 等待
        "wait_for_navigation": wait_for_navigation,
        "wait_for_element": wait_for_element,
        "wait": wait,
        # 页面信息
        "get_url": get_page_url,
        "get_title": get_page_title,
        "get_text": get_page_text,
        "screenshot": screenshot,
        # JavaScript
        "run_js": run_js,
        "mouse_click": mouse_click,
        "type_text": type_text,
        "press_key": press_key,
        "upload_file": upload_file,
        "wps_writer_export": wps_writer_export,
        "wechat_follow_official_account": wechat_follow_official_account,
        "wechat_send_official_account_message": wechat_send_official_account_message,
        "wechat_send_contact_message": wechat_send_contact_message,
        "wechat_send_contact_file": wechat_send_contact_file,
        # Cookie 持久化
        "save_cookies": save_cookies,
        "load_cookies": load_cookies,
    }

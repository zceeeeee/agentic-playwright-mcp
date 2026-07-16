"""
Layer 1 — 基础原语（Helpers）。

提供页面导航、元素点击、文本填充、截图等原子操作。
所有选择器通过列表传入，按顺序尝试，实现自愈逻辑。
严禁在本模块中硬编码任何 XPath / CSS 选择器。
"""

import os
import time
from typing import List
from urllib.parse import urlparse

from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from src.core.event_bus import (
    EVENT_CLICK,
    EVENT_FILL,
    EVENT_GOTO,
    EVENT_SCREENSHOT,
    Event,
    Phase,
    get_event_bus,
)


def _extract_site(url: str) -> str:
    """从 URL 提取站点名（去掉 www.，取第一段域名）。"""
    try:
        hostname = urlparse(url).hostname or ""
        return hostname.removeprefix("www.").split(".")[0]
    except Exception:
        return ""


def _reorder_by_experience(selector_list: List[str], page_url: str) -> List[str]:
    """按历史可靠性重排选择器列表。出错时静默返回原列表。"""
    if len(selector_list) <= 1:
        return selector_list
    try:
        from src.core.experience import get_experience_manager
        exp = get_experience_manager()
        site = _extract_site(page_url)
        if not site:
            return selector_list
        best = exp.get_best_selectors(site, element=selector_list[0])
        if not best:
            return selector_list
        reliable = [s for s in best if s in selector_list]
        rest = [s for s in selector_list if s not in reliable]
        return reliable + rest
    except Exception:
        return selector_list


def _record_selector_result(
    page_url: str, element: str, selector: str, success: bool
) -> None:
    """记录选择器成功/失败。出错时静默忽略。"""
    try:
        from src.core.experience import get_experience_manager
        exp = get_experience_manager()
        site = _extract_site(page_url)
        if not site:
            return
        if success:
            exp.record_selector_success(site, element, selector)
        else:
            exp.record_selector_failure(site, element, selector)
    except Exception:
        pass


def do_goto(page: Page, url: str) -> str:
    """导航到指定 URL。

    Args:
        page: Playwright 页面实例。
        url: 目标 URL。

    Returns:
        描述导航结果的状态字符串。
    """
    bus = get_event_bus()
    event = Event(
        name=EVENT_GOTO,
        phase=Phase.BEFORE,
        data={"url": url, "page_url": page.url},
    )
    bus.emit(event)
    if event.cancelled:
        return f"导航已取消: {event.metadata.get('cancel_reason', '')}"

    # Allow hooks to modify the URL
    url = event.data.get("url", url)

    try:
        response = page.goto(url, wait_until="domcontentloaded")
        status = response.status if response else "unknown"
        result = f"导航成功: {url} (HTTP {status})"
    except PlaywrightTimeoutError:
        result = f"导航超时: {url}"
    except Exception as exc:
        result = f"导航失败: {url} — {exc}"

    after_event = Event(
        name=EVENT_GOTO,
        phase=Phase.AFTER,
        data={"url": url, "page_url": page.url},
        result=result,
    )
    bus.emit(after_event)
    return result


def do_click(
    page: Page,
    selector_list: List[str],
    timeout: int = 5000,
) -> dict:
    """点击元素，支持多选择器自愈。

    按顺序尝试 selector_list 中的每个选择器：
    1. 先用 is_visible 短超时探测可见性
    2. 可见则执行 click 并立即返回成功
    3. 全部失败则截屏并返回错误信息

    Args:
        page: Playwright 页面实例。
        selector_list: 候选选择器列表（CSS / text= / role= 等）。
        timeout: 单次点击的超时时间（毫秒）。

    Returns:
        dict: 成功时含 success, used_selector, index；
              失败时含 success, error, screenshot。
    """
    bus = get_event_bus()
    event = Event(
        name=EVENT_CLICK,
        phase=Phase.BEFORE,
        data={
            "selector_list": list(selector_list),
            "timeout": timeout,
            "page_url": page.url,
        },
    )
    bus.emit(event)
    if event.cancelled:
        return {
            "success": False,
            "error": f"点击已取消: {event.metadata.get('cancel_reason', '')}",
        }

    # Allow hooks to modify selector list
    selector_list = event.data.get("selector_list", selector_list)

    # 按历史可靠性重排选择器
    selector_list = _reorder_by_experience(selector_list, page.url)

    for i, selector in enumerate(selector_list):
        try:
            if page.is_visible(selector, timeout=1000):
                page.click(selector, timeout=timeout)
                _record_selector_result(page.url, selector_list[0], selector, True)
                result = {
                    "success": True,
                    "used_selector": selector,
                    "index": i,
                }
                bus.emit(
                    Event(
                        name=EVENT_CLICK,
                        phase=Phase.AFTER,
                        data={
                            "selector_list": list(selector_list),
                            "page_url": page.url,
                        },
                        result=result,
                    )
                )
                return result
        except PlaywrightTimeoutError:
            continue
        except Exception:
            continue

    # 所有选择器均失败 — 截屏留证
    for sel in selector_list:
        _record_selector_result(page.url, selector_list[0], sel, False)
    screenshot_path = _save_error_screenshot(page, "click")
    result = {
        "success": False,
        "error": f"所有选择器均不可用: {selector_list}",
        "screenshot": screenshot_path,
    }
    bus.emit(
        Event(
            name=EVENT_CLICK,
            phase=Phase.AFTER,
            data={"selector_list": list(selector_list), "page_url": page.url},
            result=result,
        )
    )
    return result


def do_fill(
    page: Page,
    selector_list: List[str],
    value: str,
    timeout: int = 5000,
) -> dict:
    """填充文本到输入框，支持多选择器自愈。

    自愈逻辑与 do_click 一致：按顺序尝试选择器列表，
    找到可见目标后执行 fill 操作。

    Args:
        page: Playwright 页面实例。
        selector_list: 候选选择器列表。
        value: 要填入的文本内容。
        timeout: 单次填充的超时时间（毫秒）。

    Returns:
        dict: 成功时含 success, used_selector, index；
              失败时含 success, error, screenshot。
    """
    bus = get_event_bus()
    event = Event(
        name=EVENT_FILL,
        phase=Phase.BEFORE,
        data={
            "selector_list": list(selector_list),
            "value": value,
            "timeout": timeout,
            "page_url": page.url,
        },
    )
    bus.emit(event)
    if event.cancelled:
        return {
            "success": False,
            "error": f"填充已取消: {event.metadata.get('cancel_reason', '')}",
        }

    # Allow hooks to modify selector list and value
    selector_list = event.data.get("selector_list", selector_list)
    value = event.data.get("value", value)

    # 按历史可靠性重排选择器
    selector_list = _reorder_by_experience(selector_list, page.url)

    for i, selector in enumerate(selector_list):
        try:
            if page.is_visible(selector, timeout=1000):
                page.fill(selector, value, timeout=timeout)
                _record_selector_result(page.url, selector_list[0], selector, True)
                result = {
                    "success": True,
                    "used_selector": selector,
                    "index": i,
                }
                bus.emit(
                    Event(
                        name=EVENT_FILL,
                        phase=Phase.AFTER,
                        data={
                            "selector_list": list(selector_list),
                            "value": value,
                            "page_url": page.url,
                        },
                        result=result,
                    )
                )
                return result
        except PlaywrightTimeoutError:
            continue
        except Exception:
            continue

    for sel in selector_list:
        _record_selector_result(page.url, selector_list[0], sel, False)
    screenshot_path = _save_error_screenshot(page, "fill")
    result = {
        "success": False,
        "error": f"所有选择器均不可用: {selector_list}",
        "screenshot": screenshot_path,
    }
    bus.emit(
        Event(
            name=EVENT_FILL,
            phase=Phase.AFTER,
            data={
                "selector_list": list(selector_list),
                "value": value,
                "page_url": page.url,
            },
            result=result,
        )
    )
    return result


def do_screenshot(page: Page, path: str) -> str:
    """对当前页面截图并保存到指定路径。

    自动创建目标目录（如果不存在）。

    Args:
        page: Playwright 页面实例。
        path: 截图保存路径（PNG 格式）。

    Returns:
        实际保存的文件路径。
    """
    bus = get_event_bus()
    event = Event(
        name=EVENT_SCREENSHOT,
        phase=Phase.BEFORE,
        data={"path": path, "page_url": page.url},
    )
    bus.emit(event)
    if event.cancelled:
        return f"截图已取消: {event.metadata.get('cancel_reason', '')}"

    # Allow hooks to modify the path
    path = event.data.get("path", path)

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    page.screenshot(path=path, full_page=True)

    bus.emit(
        Event(
            name=EVENT_SCREENSHOT,
            phase=Phase.AFTER,
            data={"path": path, "page_url": page.url},
            result=path,
        )
    )
    return path


def _save_error_screenshot(page: Page, action: str) -> str:
    """保存错误截图到 logs/ 目录。

    文件名格式: logs/error_{action}_{timestamp}.png

    Args:
        page: Playwright 页面实例。
        action: 触发截图的操作名称（如 click, fill）。

    Returns:
        截图文件路径，截屏本身失败时返回空字符串。
    """
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    log_dir = "logs"
    os.makedirs(log_dir, exist_ok=True)
    path = os.path.join(log_dir, f"error_{action}_{timestamp}.png")
    try:
        page.screenshot(path=path, full_page=True)
        return path
    except Exception:
        return ""

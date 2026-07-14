"""Local WeChat desktop automation helpers."""

from __future__ import annotations

import ctypes
import logging
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from enum import Enum
from os import environ
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)


def _ensure_dpi_awareness() -> None:
    try:
        context = ctypes.c_void_p(-4)
        ctypes.windll.user32.SetProcessDpiAwarenessContext(context)
        return
    except Exception:
        pass

    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


_ensure_dpi_awareness()

PIC_DIR = Path(__file__).resolve().parents[2] / "pic"
WECHAT_APPEX_LOGO_TEMPLATE = "WeChatAppExLogo.png"
WECHAT_OFFICIAL_ACCOUNT_TEMPLATE = "公众号.png"
WECHAT_MESSAGE_BOX_TEMPLATE = "wechatSend.png"
WECHAT_SEND_BUTTON_TEMPLATE = "wechatSendGreen.png"
WECHAT_ATTACHMENT_TEMPLATE = "wechatAttachment.png"
WECHAT_TASKBAR_LOGO_TEMPLATE = "wechatLogo.png"
WECHAT_SEARCH_TEMPLATE = "搜一搜.png"
WECHAT_EXE_CANDIDATES = (
    r"C:\Program Files\Tencent\WeChat\WeChat.exe",
    r"C:\Program Files (x86)\Tencent\WeChat\WeChat.exe",
    r"C:\Program Files\Tencent\Weixin\Weixin.exe",
    r"C:\Program Files (x86)\Tencent\Weixin\Weixin.exe",
)
WECHAT_LAUNCH_NAMES = ("WeChat.exe", "Weixin.exe", "WeChat", "Weixin", "微信")
WECHAT_PROCESS_NAMES = {"wechat.exe", "wechatappex.exe", "weixin.exe"}
DEFAULT_WINDOW_RECT = (80, 60, 1200, 820)
DEFAULT_APPEX_RECT = DEFAULT_WINDOW_RECT
CHAT_INPUT_REL = (0.58, 0.88)
SEARCH_ACCOUNTS_TAB_REL = (0.24, 0.14)
SEARCH_RESULT_REGION_SIZE = (1120, 680)
SEARCH_RESULT_FIRST_ACCOUNT_OFFSET = (240, 240)
SEARCH_RESULT_WINDOW_DETECT_SECONDS = 5.0
SEARCH_ACCOUNTS_TAB_SETTLE_SECONDS = 5.0
FOLLOW_CONFIRM_SECONDS = 20.0
WECHAT_FOLLOW_BUTTON_RGB = (0x55, 0xBC, 0x7A)
ATTACHMENT_BUTTON_NAMES = ("发送文件", "文件", "添加", "更多", "Send file", "File")
FILE_DIALOG_TITLES = ("打开", "Open")
FILE_NAME_LABELS = ("文件名:", "文件名", "File name:", "File name")
OPEN_BUTTON_NAMES = ("打开", "打开(O)", "Open")
SEND_BUTTON_NAMES = ("发送", "Send")
ATTACHMENT_BUTTON_REL = (0.36, 0.72)
DEFAULT_WECHAT_FILE_SEND_MAX_BYTES = 100 * 1024 * 1024
DANGEROUS_EXTENSIONS = {
    ".exe",
    ".msi",
    ".bat",
    ".cmd",
    ".com",
    ".scr",
    ".ps1",
    ".vbs",
    ".js",
    ".jse",
    ".lnk",
}


class FileSendPhase(str, Enum):
    VALIDATED = "validated"
    CONTACT_SELECTED = "contact_selected"
    CONFIRMED = "confirmed"
    FILE_DIALOG_OPENED = "file_dialog_opened"
    FILE_SELECTED = "file_selected"
    SEND_TRIGGERED = "send_triggered"
    VERIFIED = "verified"


class WeChatFileSendError(RuntimeError):
    """Structured failure for a non-idempotent WeChat file send."""

    def __init__(
        self,
        *,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
        retryable: bool = False,
        send_may_have_started: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}
        self.retryable = retryable
        self.send_may_have_started = send_may_have_started

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "details": self.details,
            "retryable": self.retryable,
            "send_may_have_started": self.send_may_have_started,
        }


@dataclass(frozen=True)
class ValidatedLocalFile:
    path: Path
    name: str
    size_bytes: int
    modified_ns: int
    extension: str
    potentially_dangerous: bool


@dataclass(frozen=True)
class ContactSelectionResult:
    requested_name: str
    displayed_name: str | None
    exact_match: bool
    candidate_count: int | None
    verified: bool


@dataclass(frozen=True)
class WeChatFileSendResult:
    success: bool
    status: str
    method: str
    verified: bool
    phase: FileSendPhase


@dataclass(frozen=True)
class ClipboardTextSnapshot:
    text: str | None
    had_unicode_text: bool


def looks_like_windows_file_path(value: str | None) -> bool:
    return bool(re.search(r"(?:[A-Za-z]:[\\/]|\\\\)[^\r\n]+", str(value or "")))


def _configured_file_size_limit() -> int | None:
    raw = os.getenv("WECHAT_FILE_SEND_MAX_BYTES", "").strip()
    if not raw:
        return DEFAULT_WECHAT_FILE_SEND_MAX_BYTES
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_WECHAT_FILE_SEND_MAX_BYTES
    return value if value > 0 else None


def normalize_local_file_path(value: str) -> Path:
    if sys.platform != "win32":
        raise WeChatFileSendError(
            code="UNSUPPORTED_PLATFORM",
            message="微信桌面文件发送仅支持 Windows",
        )

    raw = str(value or "").strip()
    if not raw:
        raise WeChatFileSendError(
            code="FILE_PATH_REQUIRED",
            message="请提供需要发送的本地文件绝对路径",
        )
    if len(raw) >= 2 and raw[0] in {'"', "'", "“", "‘"} and raw[-1] in {'"', "'", "”", "’"}:
        raw = raw[1:-1].strip()
    if not raw or "*" in raw or "?" in raw or re.match(r"^https?://", raw, re.IGNORECASE):
        raise WeChatFileSendError(
            code="PATH_NOT_ABSOLUTE",
            message="请提供不含通配符的本地文件绝对路径",
        )

    raw = os.path.expandvars(os.path.expanduser(raw))
    path = Path(raw)
    if not path.is_absolute():
        raise WeChatFileSendError(
            code="PATH_NOT_ABSOLUTE",
            message="请提供本地文件的绝对路径",
        )
    try:
        resolved = path.resolve(strict=True)
    except FileNotFoundError as exc:
        raise WeChatFileSendError(
            code="FILE_NOT_FOUND",
            message=f"找不到文件：{path.name}",
            retryable=True,
        ) from exc
    except OSError as exc:
        raise WeChatFileSendError(
            code="FILE_NOT_FOUND",
            message=f"无法访问文件：{path.name}",
            details={"error_type": type(exc).__name__},
            retryable=True,
        ) from exc
    if not resolved.is_file():
        raise WeChatFileSendError(
            code="NOT_A_FILE",
            message="指定路径不是普通文件",
        )
    return resolved


def validate_local_file(
    file_path: str,
    *,
    max_size_bytes: int | None = None,
) -> ValidatedLocalFile:
    path = normalize_local_file_path(file_path)
    try:
        stat = path.stat()
    except OSError as exc:
        raise WeChatFileSendError(
            code="FILE_NOT_FOUND",
            message=f"无法读取文件信息：{path.name}",
            details={"error_type": type(exc).__name__},
            retryable=True,
        ) from exc

    limit = _configured_file_size_limit() if max_size_bytes is None else max_size_bytes
    if limit is not None and limit > 0 and stat.st_size > limit:
        raise WeChatFileSendError(
            code="FILE_TOO_LARGE",
            message=(
                f"文件大小为 {stat.st_size / 1024 / 1024:.1f} MB，"
                f"超过当前应用设置的 {limit / 1024 / 1024:.1f} MB 上限"
            ),
            details={"size_bytes": stat.st_size, "max_size_bytes": limit},
        )
    extension = path.suffix.lower()
    return ValidatedLocalFile(
        path=path,
        name=path.name,
        size_bytes=stat.st_size,
        modified_ns=stat.st_mtime_ns,
        extension=extension,
        potentially_dangerous=extension in DANGEROUS_EXTENSIONS,
    )


def revalidate_local_file(validated: ValidatedLocalFile) -> None:
    try:
        stat = validated.path.stat()
    except OSError as exc:
        raise WeChatFileSendError(
            code="FILE_CHANGED_AFTER_CONFIRMATION",
            message="文件在确认后已无法访问，请重新确认",
        ) from exc
    if stat.st_size != validated.size_bytes or stat.st_mtime_ns != validated.modified_ns:
        raise WeChatFileSendError(
            code="FILE_CHANGED_AFTER_CONFIRMATION",
            message="文件在确认后发生了变化，请重新确认",
            details={"file_name": validated.name},
        )


@dataclass(frozen=True)
class ImageMatch:
    """A screen-space template match."""

    x: int
    y: int
    score: float
    template_name: str


class ScreenImageLocator:
    """Locate and click WeChat UI targets from screenshots using OpenCV templates."""

    def __init__(self, pic_dir: str | Path = PIC_DIR) -> None:
        self.pic_dir = Path(pic_dir)

    def find(
        self,
        template_name: str,
        *,
        region: tuple[int, int, int, int] | str | None = None,
        threshold: float = 0.78,
    ) -> ImageMatch | None:
        cv2 = self._load_cv2()
        np = self._load_numpy()
        if cv2 is None or np is None:
            return None

        template_path = self.pic_dir / template_name
        if not template_path.exists():
            return None

        capture = self._capture_region(region)
        if capture is None:
            return None
        crop, left, top = capture
        if crop.size == 0:
            return None

        try:
            template_bytes = np.frombuffer(template_path.read_bytes(), dtype=np.uint8)
            template = cv2.imdecode(template_bytes, cv2.IMREAD_COLOR)
        except Exception:
            return None
        if template is None:
            return None

        template_h, template_w = template.shape[:2]
        if crop.shape[0] < template_h or crop.shape[1] < template_w:
            return None

        try:
            crop_gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
            template_gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
            result = cv2.matchTemplate(crop_gray, template_gray, cv2.TM_CCOEFF_NORMED)
            _, max_score, _, max_loc = cv2.minMaxLoc(result)
        except Exception:
            return None

        if max_score < threshold:
            return None

        return ImageMatch(
            x=left + int(max_loc[0] + template_w / 2),
            y=top + int(max_loc[1] + template_h / 2),
            score=float(max_score),
            template_name=template_name,
        )

    def click(
        self,
        template_name: str,
        *,
        region: tuple[int, int, int, int] | str | None = None,
        threshold: float = 0.78,
    ) -> ImageMatch | None:
        match = self.find(template_name, region=region, threshold=threshold)
        if match is None:
            return None
        self._click_xy(match.x, match.y)
        return match

    def click_green_button(
        self,
        *,
        region: tuple[int, int, int, int] | str | None = None,
        min_area: int = 900,
    ) -> ImageMatch | None:
        match = self.find_green_button(region=region, min_area=min_area)
        if match is None:
            return None
        self._click_xy(match.x, match.y)
        return match

    def click_green_text(
        self,
        *,
        region: tuple[int, int, int, int] | str | None = None,
        text: str = "",
    ) -> ImageMatch | None:
        match = self.find_green_text(region=region, text=text)
        if match is None:
            return None
        self._click_xy(match.x, match.y)
        return match

    def click_first_result_green_text(
        self,
        *,
        region: tuple[int, int, int, int] | str | None = None,
        text: str = "",
    ) -> ImageMatch | None:
        match = self.find_first_result_green_text(region=region, text=text)
        if match is None:
            return None
        self._click_xy(match.x, match.y)
        return match

    def find_green_text(
        self,
        *,
        region: tuple[int, int, int, int] | str | None = None,
        text: str = "",
    ) -> ImageMatch | None:
        cv2 = self._load_cv2()
        np = self._load_numpy()
        if cv2 is None or np is None:
            return None

        capture = self._capture_region(region)
        if capture is None:
            return None
        crop, left, top = capture
        if crop.size == 0:
            return None

        try:
            candidates = self._green_text_candidates(cv2, np, crop)
        except Exception:
            return None

        if not candidates:
            return None

        candidates.sort(key=lambda item: (item[1], item[0]))
        x, y, w, h, density = candidates[0]
        template_name = f"green_text:{text}" if text else "green_text"
        return ImageMatch(
            x=left + x + w // 2,
            y=top + y + h // 2,
            score=float(density),
            template_name=template_name,
        )

    def find_first_result_green_text(
        self,
        *,
        region: tuple[int, int, int, int] | str | None = None,
        text: str = "",
    ) -> ImageMatch | None:
        cv2 = self._load_cv2()
        np = self._load_numpy()
        if cv2 is None or np is None:
            return None

        capture = self._capture_region(region)
        if capture is None:
            return None
        crop, left, top = capture
        if crop.size == 0:
            return None

        try:
            candidates = self._green_text_candidates(cv2, np, crop)
            cards = self._result_card_candidates(cv2, np, crop)
        except Exception:
            return None

        for card_x, card_y, card_w, card_h in cards:
            min_y = card_y + max(48, int(card_h * 0.28))
            min_x = card_x + max(80, min(170, int(card_w * 0.12)))
            max_y = card_y + int(card_h * 0.82)
            in_card = [
                item
                for item in candidates
                if item[0] >= min_x
                and item[1] >= min_y
                and item[1] <= max_y
                and item[0] + item[2] <= card_x + card_w
            ]
            if not in_card:
                continue
            in_card.sort(key=lambda item: (item[1], item[0]))
            x, y, w, h, density = in_card[0]
            template_name = f"first_result_green_text:{text}" if text else "first_result_green_text"
            return ImageMatch(
                x=left + x + w // 2,
                y=top + y + h // 2,
                score=float(density),
                template_name=template_name,
            )

        return self.find_green_text(region=region, text=text)

    def find_green_button(
        self,
        *,
        region: tuple[int, int, int, int] | str | None = None,
        min_area: int = 900,
    ) -> ImageMatch | None:
        cv2 = self._load_cv2()
        np = self._load_numpy()
        if cv2 is None or np is None:
            return None

        capture = self._capture_region(region)
        if capture is None:
            return None
        crop, left, top = capture
        if crop.size == 0:
            return None

        try:
            theme_rgb = np.array(WECHAT_FOLLOW_BUTTON_RGB, dtype=np.int16)
            lower_rgb = np.array([45, 145, 85], dtype=np.uint8)
            upper_rgb = np.array([135, 225, 170], dtype=np.uint8)
            channel_mask = cv2.inRange(crop, lower_rgb, upper_rgb)
            diff = crop.astype(np.int16) - theme_rgb
            distance = np.sqrt(np.sum(diff * diff, axis=2))
            theme_mask = (distance <= 65).astype(np.uint8) * 255
            mask = cv2.bitwise_and(channel_mask, theme_mask)
            raw_mask = mask.copy()
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7))
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
            mask = cv2.dilate(mask, kernel, iterations=1)
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        except Exception:
            return None

        candidates: list[tuple[float, int, int, int, int, int]] = []
        for contour in contours:
            area = int(cv2.contourArea(contour))
            if area < min_area:
                continue
            x, y, w, h = cv2.boundingRect(contour)
            if w < 48 or h < 20:
                continue
            ratio = w / max(1, h)
            if ratio < 1.5 or ratio > 8:
                continue
            raw_roi = raw_mask[y : y + h, x : x + w]
            density = cv2.countNonZero(raw_roi) / max(1, w * h)
            if density < 0.45:
                continue
            candidates.append((density * area, area, x, y, w, h))

        if not candidates:
            return None
        score, area, x, y, w, h = max(candidates, key=lambda item: (item[0], item[1]))
        return ImageMatch(
            x=left + x + w // 2,
            y=top + y + h // 2,
            score=float(score),
            template_name="green_button",
        )

    @staticmethod
    def _green_text_candidates(cv2: Any, np: Any, crop: Any) -> list[tuple[int, int, int, int, float]]:
        hsv = cv2.cvtColor(crop, cv2.COLOR_RGB2HSV)
        lower = np.array([35, 35, 65])
        upper = np.array([95, 255, 255])
        mask = cv2.inRange(hsv, lower, upper)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (9, 3))
        grouped = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        grouped = cv2.dilate(grouped, kernel, iterations=1)
        contours, _ = cv2.findContours(
            grouped,
            cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_SIMPLE,
        )

        candidates: list[tuple[int, int, int, int, float]] = []
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            if w < 24 or h < 10 or h > 46:
                continue
            ratio = w / max(1, h)
            if ratio < 1.2 or ratio > 12:
                continue
            raw_pixels = int(cv2.countNonZero(mask[y : y + h, x : x + w]))
            density = raw_pixels / max(1, w * h)
            # Text has sparse green pixels; solid green buttons are dense.
            if density < 0.03 or density > 0.62:
                continue
            candidates.append((x, y, w, h, density))
        return candidates

    @staticmethod
    def _result_card_candidates(cv2: Any, np: Any, crop: Any) -> list[tuple[int, int, int, int]]:
        gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
        card_mask = cv2.inRange(gray, 18, 42)
        crop_h, crop_w = gray.shape[:2]
        min_row_pixels = max(240, int(crop_w * 0.35))
        rows = np.where(np.count_nonzero(card_mask, axis=1) >= min_row_pixels)[0]
        if rows.size == 0:
            return []

        bands: list[tuple[int, int]] = []
        start = prev = int(rows[0])
        for row in rows[1:]:
            current = int(row)
            if current > prev + 4:
                if prev - start >= 70:
                    bands.append((start, prev))
                start = current
            prev = current
        if prev - start >= 70:
            bands.append((start, prev))

        cards: list[tuple[int, int, int, int]] = []
        for band_top, band_bottom in bands:
            band_height = band_bottom - band_top + 1
            if band_top < 36 and band_height < 90:
                continue
            band = card_mask[band_top : band_bottom + 1]
            col_counts = np.count_nonzero(band, axis=0)
            cols = np.where(col_counts >= max(20, int(band_height * 0.35)))[0]
            if cols.size == 0:
                continue
            left = int(cols[0])
            right = int(cols[-1])
            width = right - left + 1
            if width < 240:
                continue
            cards.append((left, band_top, width, band_height))
        return sorted(cards, key=lambda item: (item[1], item[0]))

    def click_xy(self, x: int, y: int) -> None:
        self._click_xy(x, y)

    def click_relative(
        self,
        region: tuple[int, int, int, int],
        rx: float,
        ry: float,
    ) -> bool:
        normalized = self._coerce_region(region)
        if normalized is None:
            return False
        left, top, width, height = normalized
        self._click_xy(left + int(width * rx), top + int(height * ry))
        return True

    @staticmethod
    def taskbar_region_for_size(width: int, height: int) -> tuple[int, int, int, int]:
        top = max(0, int(height * 0.72))
        return (0, top, width, height - top)

    def _resolve_region(
        self,
        region: tuple[int, int, int, int] | str | None,
        screen_w: int,
        screen_h: int,
    ) -> tuple[int, int, int, int]:
        if region == "taskbar":
            return self.taskbar_region_for_size(screen_w, screen_h)
        if region is None:
            return (0, 0, screen_w, screen_h)

        left, top, width, height = region
        left = max(0, min(screen_w, int(left)))
        top = max(0, min(screen_h, int(top)))
        width = max(0, min(screen_w - left, int(width)))
        height = max(0, min(screen_h - top, int(height)))
        return (left, top, width, height)

    def _capture_region(
        self,
        region: tuple[int, int, int, int] | str | None,
    ) -> tuple[Any, int, int] | None:
        if isinstance(region, tuple):
            normalized = self._coerce_region(region)
            if normalized is None:
                return None
            left, top, _width, _height = normalized
            screenshot = self._screenshot_array(normalized)
            if screenshot is None:
                return None
            return screenshot, left, top

        screenshot = self._screenshot_array()
        if screenshot is None:
            return None

        screen_h, screen_w = screenshot.shape[:2]
        left, top, width, height = self._resolve_region(region, screen_w, screen_h)
        crop = screenshot[top : top + height, left : left + width]
        return crop, left, top

    @staticmethod
    def _coerce_region(
        region: tuple[int, int, int, int] | None,
    ) -> tuple[int, int, int, int] | None:
        if region is None:
            return None
        try:
            left, top, width, height = (int(value) for value in region)
        except Exception:
            return None
        if width <= 0 or height <= 0:
            return None
        return max(0, left), max(0, top), width, height

    @staticmethod
    def _load_cv2() -> Any | None:
        try:
            import cv2  # type: ignore[import-not-found]

            return cv2
        except Exception:
            return None

    @staticmethod
    def _load_numpy() -> Any | None:
        try:
            import numpy as np  # type: ignore[import-not-found]

            return np
        except Exception:
            return None

    def _screenshot_array(
        self,
        region: tuple[int, int, int, int] | None = None,
    ) -> Any | None:
        np = self._load_numpy()
        if np is None:
            return None

        normalized_region = self._coerce_region(region)
        bbox = None
        if region is not None:
            if normalized_region is None:
                return None
            left, top, width, height = normalized_region
            bbox = (left, top, left + width, top + height)

        image = None
        try:
            from PIL import ImageGrab  # type: ignore[import-not-found]

            image = ImageGrab.grab(bbox=bbox)
        except Exception:
            try:
                import pyautogui  # type: ignore[import-not-found]

                if normalized_region is None:
                    image = pyautogui.screenshot()
                else:
                    image = pyautogui.screenshot(region=normalized_region)
            except Exception:
                return None

        try:
            return np.array(image.convert("RGB"))
        except Exception:
            return None

    @staticmethod
    def _click_xy(x: int, y: int) -> None:
        try:
            from pywinauto.mouse import click  # type: ignore[import-not-found]

            click(button="left", coords=(x, y))
            return
        except Exception:
            pass

        try:
            import pyautogui  # type: ignore[import-not-found]

            pyautogui.click(x, y)
            return
        except Exception:
            pass

        try:
            import ctypes

            user32 = ctypes.windll.user32
            user32.SetCursorPos(int(x), int(y))
            user32.mouse_event(0x0002, 0, 0, 0, 0)
            user32.mouse_event(0x0004, 0, 0, 0, 0)
        except Exception as exc:
            raise RuntimeError("Unable to click matched screen image") from exc


class WeChatWindowManager:
    """Manage the WeChat desktop window family, including WeChatAppEx windows."""

    MAIN_CLASS = "WeChatMainWndForPC"

    def __init__(self, desktop: Any, window_rect_provider: Any | None = None) -> None:
        self.desktop = desktop
        self.window_rect_provider = window_rect_provider or self._left_half_work_area_rect

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
                self.normalize(window, app_ex=True, focus=False)
                handle = PywinautoWechatAutomation._window_handle(window)
                if handle not in before_handles:
                    return window
                if title_hint and self._window_contains(window, title_hint):
                    fallback = window
            if fallback is not None:
                return fallback
            time.sleep(0.25)
        return fallback

    def normalize(self, window: Any, *, app_ex: bool = False, focus: bool = True) -> Any:
        x, y, width, height = self._target_rect(app_ex=app_ex)
        move_error: Exception | None = None
        moved = self._set_window_pos(window, x, y, width, height)
        if not moved:
            try:
                window.restore()
            except Exception:
                pass
            try:
                window.move_window(x=x, y=y, width=width, height=height, repaint=True)
                moved = True
            except Exception as exc:
                move_error = exc
        if not moved:
            logger.warning(
                "Failed to move WeChat window to left half "
                "title=%r process=%r rect=(%s,%s,%s,%s): %s",
                PywinautoWechatAutomation._element_text(window),
                PywinautoWechatAutomation._window_process_name(window),
                x,
                y,
                width,
                height,
                move_error or "SetWindowPos returned false",
            )
        if focus:
            try:
                window.set_focus()
            except Exception:
                pass
        time.sleep(0.2)
        return window

    def normalize_all(self, *, active_window: Any | None = None) -> None:
        for window in self.list_windows():
            process_name = PywinautoWechatAutomation._window_process_name(window)
            self.normalize(
                window,
                app_ex=process_name == "wechatappex.exe",
                focus=active_window is not None and window is active_window,
            )

    @staticmethod
    def _set_window_pos(window: Any, x: int, y: int, width: int, height: int) -> bool:
        hwnd = PywinautoWechatAutomation._window_handle(window)
        if not hwnd:
            return False
        try:
            user32 = ctypes.windll.user32
            sw_restore = 9
            swp_nozorder = 0x0004
            swp_noactivate = 0x0010
            user32.ShowWindow(int(hwnd), sw_restore)
            return bool(
                user32.SetWindowPos(
                    int(hwnd),
                    0,
                    int(x),
                    int(y),
                    int(width),
                    int(height),
                    swp_nozorder | swp_noactivate,
                )
            )
        except Exception:
            return False

    def _target_rect(self, *, app_ex: bool = False) -> tuple[int, int, int, int]:
        try:
            rect = self.window_rect_provider(app_ex=app_ex)
        except TypeError:
            rect = self.window_rect_provider()
        except Exception:
            rect = None

        coerced = self._coerce_rect(rect)
        if coerced is not None:
            return coerced
        return DEFAULT_APPEX_RECT if app_ex else DEFAULT_WINDOW_RECT

    @staticmethod
    def _coerce_rect(rect: Any) -> tuple[int, int, int, int] | None:
        if rect is None:
            return None
        try:
            x, y, width, height = (int(value) for value in rect)
        except Exception:
            return None
        if width <= 0 or height <= 0:
            return None
        return x, y, width, height

    @staticmethod
    def _left_half_work_area_rect(*, app_ex: bool = False) -> tuple[int, int, int, int] | None:
        try:
            import ctypes
            from ctypes import wintypes
        except Exception:
            return None

        class Rect(ctypes.Structure):
            _fields_ = [
                ("left", wintypes.LONG),
                ("top", wintypes.LONG),
                ("right", wintypes.LONG),
                ("bottom", wintypes.LONG),
            ]

        rect = Rect()
        spi_get_work_area = 0x0030
        try:
            ok = ctypes.windll.user32.SystemParametersInfoW(
                spi_get_work_area,
                0,
                ctypes.byref(rect),
                0,
            )
        except Exception:
            return None
        if not ok:
            return None

        work_width = int(rect.right - rect.left)
        work_height = int(rect.bottom - rect.top)
        if work_width <= 0 or work_height <= 0:
            return None
        return int(rect.left), int(rect.top), max(1, work_width // 2), work_height

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

    def __init__(
        self,
        launch_path: str | None = None,
        wait_timeout: float = 20.0,
        image_locator: Any | None = None,
    ) -> None:
        self.launch_path = launch_path
        self.wait_timeout = wait_timeout
        self.app: Any = None
        self.desktop: Any = None
        self.window: Any = None
        self.window_manager: WeChatWindowManager | None = None
        self.locator = ElementLocator(timeout=8.0)
        self.image_locator = image_locator or ScreenImageLocator()
        self._last_search_result_anchor: ImageMatch | None = None

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
            self._normalize_current_window()
            return

        if self._launch_wechat_by_name(Application):
            return

        exe_path = self._resolve_executable()
        self.app = Application(backend="uia").start(str(exe_path))
        if self._wait_for_main_window(timeout=self.wait_timeout):
            return
        raise RuntimeError("Unable to find WeChat window after launch")

    def search_official_account(self, account_name: str) -> None:
        self._require_window()
        self._normalize_current_window()
        before_handles = self._snapshot_window_handles()
        self._send_keys("^f")
        time.sleep(0.2)
        self._send_keys("^a")
        self._paste_or_type(account_name)
        clicked_global_search = self._click_souyisou_if_visible(timeout=0.8)
        if not clicked_global_search:
            self._send_keys("{ENTER}")
            clicked_global_search = self._click_souyisou_if_visible(timeout=1.2)
        if clicked_global_search:
            if not self._wait_for_search_result_window(
                account_name,
                before_handles=before_handles,
                wait_seconds=SEARCH_RESULT_WINDOW_DETECT_SECONDS,
            ):
                raise RuntimeError("Unable to activate WeChatAppEx search result window")
            self._click_search_accounts_tab(timeout=3.0)
            if self._click_first_account_result_after_tab(
                account_name,
                before_handles=before_handles,
            ):
                return
        else:
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
        if self._needs_official_account_home_confirmation() and not self._wait_for_official_account_home(timeout=8.0):
            return False
        deadline = time.time() + FOLLOW_CONFIRM_SECONDS
        clicked_follow = False
        while time.time() < deadline:
            if self._is_followed_state():
                return True
            if self._click_follow_button_visual(timeout=1.0):
                clicked_follow = True
                time.sleep(1.0)
                continue
            time.sleep(0.5)
        return clicked_follow and self._is_followed_state()

    def send_message(self, message: str) -> None:
        self._require_window()
        self._normalize_current_window()
        self._focus_message_input()
        self._paste_or_type(message)
        time.sleep(0.2)
        self._send_keys("{ENTER}")
        time.sleep(0.5)

    def _focus_message_input(self) -> str:
        """Focus the active chat input using the normal message-send strategy."""

        edit = self._find_message_edit()
        if edit is not None:
            edit.click_input()
            return "uia"
        elif self._click_message_box_visual(timeout=2.0):
            return "image"
        else:
            if not self._click_window_relative(*CHAT_INPUT_REL):
                self._click_relative(self.window, *CHAT_INPUT_REL)
            return "relative"

    def search_contact_verified(self, recipient_name: str) -> ContactSelectionResult:
        """Use the same contact-search flow as normal text messages."""

        recipient = _clean_required(recipient_name, "recipient name")
        self.search_contact(recipient)
        return ContactSelectionResult(
            requested_name=recipient,
            displayed_name=recipient,
            exact_match=True,
            candidate_count=None,
            verified=True,
        )

    def send_file(self, file_path: str | Path) -> WeChatFileSendResult:
        """Paste one validated file into the active chat, then send it once."""

        validated = validate_local_file(str(file_path))
        self._require_window()
        self._normalize_current_window()
        self._focus_message_input()
        baseline = self._snapshot_file_markers(validated.name)

        try:
            return self._send_file_via_chat_input(validated, baseline)
        except WeChatFileSendError as exc:
            if exc.code != "FILE_CLIPBOARD_FAILED":
                raise
            logger.warning(
                "WeChat file clipboard paste unavailable; falling back to native dialog: %s",
                exc.message,
            )
        return self._send_file_via_native_dialog(validated, baseline)

    def _send_file_via_chat_input(
        self,
        validated: ValidatedLocalFile,
        baseline: set[tuple[int, int, int, int, int]],
    ) -> WeChatFileSendResult:
        snapshot = self._set_file_drop_clipboard(validated.path)
        try:
            revalidate_local_file(validated)
            self._send_keys("^v")
            time.sleep(1.5)
            self._send_keys("{ENTER}")
            time.sleep(0.8)
        finally:
            self._restore_clipboard_text(snapshot)

        verified = self._verify_outgoing_file(
            validated.name,
            baseline=baseline,
            timeout=10.0,
        )
        return WeChatFileSendResult(
            success=True,
            status="ui_verified" if verified else "submitted",
            method="clipboard_file_paste",
            verified=verified,
            phase=(FileSendPhase.VERIFIED if verified else FileSendPhase.SEND_TRIGGERED),
        )

    def _send_file_via_native_dialog(
        self,
        validated: ValidatedLocalFile,
        baseline: set[tuple[int, int, int, int, int]],
    ) -> WeChatFileSendResult:

        self._click_attachment_button()
        try:
            dialog = self._wait_for_native_file_dialog(timeout=4.0)
        except WeChatFileSendError:
            file_button = self._find_attachment_button(file_only=True)
            if file_button is None:
                raise
            self._click_element_or_parent(file_button)
            dialog = self._wait_for_native_file_dialog(timeout=5.0)

        self._set_file_dialog_path(dialog, validated.path)
        revalidate_local_file(validated)
        self._confirm_file_dialog(dialog)

        state = self._wait_for_file_preview_or_sent(
            validated.name,
            baseline=baseline,
            timeout=8.0,
        )
        return self._complete_file_send(
            validated.name,
            baseline=baseline,
            state=state,
            method="native_file_dialog",
        )

    def _complete_file_send(
        self,
        file_name: str,
        *,
        baseline: set[tuple[int, int, int, int, int]],
        state: str,
        method: str,
    ) -> WeChatFileSendResult:
        if state == "sent":
            return WeChatFileSendResult(
                success=True,
                status="ui_verified",
                method=method,
                verified=True,
                phase=FileSendPhase.VERIFIED,
            )
        if state != "preview":
            raise WeChatFileSendError(
                code="SEND_STATUS_UNKNOWN",
                message=(
                    "已在微信聊天中选择或粘贴文件，但无法确认是否已经发送。"
                    "请检查聊天记录，不要直接重试。"
                ),
                details={"method": method},
                send_may_have_started=True,
            )

        self._send_staged_file()
        if not self._verify_outgoing_file(
            file_name,
            baseline=baseline,
            timeout=10.0,
        ):
            raise WeChatFileSendError(
                code="SEND_STATUS_UNKNOWN",
                message=(
                    "已触发微信发送，但无法确认是否成功。"
                    "请检查聊天记录，不要直接重试。"
                ),
                details={"method": method},
                send_may_have_started=True,
            )
        return WeChatFileSendResult(
            success=True,
            status="ui_verified",
            method=method,
            verified=True,
            phase=FileSendPhase.VERIFIED,
        )

    def _set_file_drop_clipboard(self, file_path: Path) -> ClipboardTextSnapshot:
        if sys.platform != "win32":
            raise WeChatFileSendError(
                code="FILE_CLIPBOARD_FAILED",
                message="Windows 文件剪贴板仅支持 Windows",
                retryable=True,
            )

        snapshot: ClipboardTextSnapshot | None = None
        try:
            snapshot = self._capture_clipboard_text()
            self._write_file_drop_clipboard(file_path)
        except Exception as exc:
            if snapshot is not None:
                self._restore_clipboard_text(snapshot)
            raise WeChatFileSendError(
                code="FILE_CLIPBOARD_FAILED",
                message="无法把文件放入 Windows 文件剪贴板",
                details={"error_type": type(exc).__name__},
                retryable=True,
            ) from exc
        return snapshot

    @staticmethod
    def _open_windows_clipboard(timeout: float = 1.5) -> None:
        import win32clipboard  # type: ignore[import-not-found]

        deadline = time.time() + timeout
        while True:
            try:
                win32clipboard.OpenClipboard()
                return
            except Exception:
                if time.time() >= deadline:
                    raise
                time.sleep(0.05)

    def _capture_clipboard_text(self) -> ClipboardTextSnapshot:
        import win32clipboard  # type: ignore[import-not-found]
        import win32con  # type: ignore[import-not-found]

        self._open_windows_clipboard()
        try:
            has_text = bool(
                win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT)
            )
            text = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT) if has_text else None
            return ClipboardTextSnapshot(
                text=str(text) if text is not None else None,
                had_unicode_text=has_text,
            )
        finally:
            win32clipboard.CloseClipboard()

    def _write_file_drop_clipboard(self, file_path: Path) -> None:
        from ctypes import wintypes

        import win32clipboard  # type: ignore[import-not-found]
        import win32con  # type: ignore[import-not-found]

        class DROPFILES(ctypes.Structure):
            _fields_ = [
                ("pFiles", wintypes.DWORD),
                ("pt", wintypes.POINT),
                ("fNC", wintypes.BOOL),
                ("fWide", wintypes.BOOL),
            ]

        file_list = (str(file_path) + "\0\0").encode("utf-16le")
        header = DROPFILES()
        header.pFiles = ctypes.sizeof(DROPFILES)
        header.fWide = True
        payload_size = ctypes.sizeof(header) + len(file_list)

        kernel32 = ctypes.windll.kernel32
        user32 = ctypes.windll.user32
        kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
        kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
        kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalLock.restype = wintypes.LPVOID
        kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
        user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
        user32.SetClipboardData.restype = wintypes.HANDLE

        handle = kernel32.GlobalAlloc(0x0042, payload_size)
        if not handle:
            raise OSError("GlobalAlloc failed")
        transferred = False
        try:
            pointer = kernel32.GlobalLock(handle)
            if not pointer:
                raise OSError("GlobalLock failed")
            try:
                ctypes.memmove(pointer, ctypes.byref(header), ctypes.sizeof(header))
                ctypes.memmove(
                    pointer + ctypes.sizeof(header),
                    file_list,
                    len(file_list),
                )
            finally:
                kernel32.GlobalUnlock(handle)

            self._open_windows_clipboard()
            try:
                win32clipboard.EmptyClipboard()
                if not user32.SetClipboardData(win32con.CF_HDROP, handle):
                    raise OSError("SetClipboardData(CF_HDROP) failed")
                transferred = True
            finally:
                win32clipboard.CloseClipboard()
        finally:
            if not transferred:
                kernel32.GlobalFree(handle)

    def _restore_clipboard_text(self, snapshot: ClipboardTextSnapshot) -> None:
        import win32clipboard  # type: ignore[import-not-found]
        import win32con  # type: ignore[import-not-found]

        try:
            self._open_windows_clipboard()
            try:
                win32clipboard.EmptyClipboard()
                if snapshot.had_unicode_text:
                    win32clipboard.SetClipboardText(
                        snapshot.text or "",
                        win32con.CF_UNICODETEXT,
                    )
            finally:
                win32clipboard.CloseClipboard()
        except Exception as exc:
            logger.warning("Unable to restore clipboard text after WeChat file paste: %s", exc)

    def _find_attachment_button(self, *, file_only: bool = False) -> Any | None:
        self._require_window()
        names = ("发送文件", "文件", "Send file", "File") if file_only else ATTACHMENT_BUTTON_NAMES
        message_edit = self._find_message_edit()
        edit_top: int | None = None
        if message_edit is not None:
            try:
                edit_top = int(message_edit.rectangle().top)
            except Exception:
                pass
        candidates: list[tuple[int, Any]] = []
        for item in self.locator.descendants(self.window):
            text = self._element_text(item).strip()
            if not text or not any(name.casefold() in text.casefold() for name in names):
                continue
            control_type = self._element_control_type(item)
            if control_type not in {"Button", "Pane", "Image", "Text", "Custom"}:
                continue
            score = 5 if text.casefold() in {name.casefold() for name in names[:2]} else 1
            try:
                rect = item.rectangle()
                if edit_top is not None:
                    if not edit_top - 120 <= rect.top <= edit_top + 80:
                        continue
                    score += 5
            except Exception:
                if edit_top is not None:
                    continue
            candidates.append((score, item))
        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0][1]

    def _click_attachment_button(self) -> str:
        target = self._find_attachment_button()
        if target is not None:
            self._click_element_or_parent(target)
            return "uia"
        if self._click_template(
            WECHAT_ATTACHMENT_TEMPLATE,
            current_window_region=True,
            timeout=1.5,
        ):
            return "image"
        if self._click_window_relative(*ATTACHMENT_BUTTON_REL):
            return "relative"
        raise WeChatFileSendError(
            code="ATTACHMENT_BUTTON_NOT_FOUND",
            message="无法定位微信聊天窗口中的文件按钮",
            retryable=True,
        )

    def _wait_for_native_file_dialog(self, timeout: float) -> Any:
        desktop = self._get_desktop()
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                windows = desktop.windows()
            except Exception:
                windows = []
            for window in windows:
                title = self._element_text(window).strip()
                class_name = ""
                try:
                    class_name = str(window.element_info.class_name or "")
                except Exception:
                    pass
                if title not in FILE_DIALOG_TITLES and class_name != "#32770":
                    continue
                if self._find_file_name_edit(window) is not None:
                    try:
                        window.set_focus()
                    except Exception:
                        pass
                    return window
            time.sleep(0.2)
        raise WeChatFileSendError(
            code="FILE_DIALOG_NOT_FOUND",
            message="点击微信文件按钮后未出现 Windows 文件选择窗口",
            retryable=True,
        )

    def _find_file_name_edit(self, dialog: Any) -> Any | None:
        edits = self.locator.descendants(dialog, control_type="Edit")
        if not edits:
            return None
        for edit in edits:
            try:
                if str(edit.element_info.automation_id or "") == "1148":
                    return edit
            except Exception:
                pass
        labelled = self.locator.find_by_name(
            dialog,
            FILE_NAME_LABELS,
            control_types=("Text",),
            timeout=0.1,
        )
        if labelled is not None:
            try:
                label_top = labelled.rectangle().top
                edits.sort(key=lambda item: abs(item.rectangle().top - label_top))
                return edits[0]
            except Exception:
                pass

        def score(edit: Any) -> tuple[int, int]:
            try:
                rect = edit.rectangle()
                return int(rect.top), int(rect.width())
            except Exception:
                return 0, 0
        edits.sort(key=score, reverse=True)
        return edits[0]

    def _set_file_dialog_path(self, dialog: Any, file_path: Path) -> None:
        edit = self._find_file_name_edit(dialog)
        if edit is None:
            raise WeChatFileSendError(
                code="FILE_DIALOG_EDIT_NOT_FOUND",
                message="无法定位文件选择窗口的文件名输入框",
                retryable=True,
            )
        try:
            edit.click_input()
        except Exception:
            pass
        try:
            edit.set_edit_text(str(file_path))
            return
        except Exception:
            pass
        self._send_keys("^a")
        self._paste_text_preserving_clipboard(str(file_path))

    def _paste_text_preserving_clipboard(self, text: str) -> None:
        previous: str | None = None
        try:
            import pyperclip  # type: ignore[import-not-found]

            try:
                previous = pyperclip.paste()
            except Exception:
                previous = None
            pyperclip.copy(text)
            self._send_keys("^v")
        except Exception:
            from pywinauto.keyboard import send_keys  # type: ignore[import-not-found]

            send_keys(text, with_spaces=True, pause=0.02)
        finally:
            if previous is not None:
                try:
                    import pyperclip  # type: ignore[import-not-found]

                    pyperclip.copy(previous)
                except Exception:
                    pass

    def _confirm_file_dialog(self, dialog: Any) -> None:
        button = self.locator.find_by_name(
            dialog,
            OPEN_BUTTON_NAMES,
            control_types=("Button",),
            exact=True,
            timeout=1.5,
        )
        if button is None:
            raise WeChatFileSendError(
                code="FILE_DIALOG_OPEN_FAILED",
                message="无法定位文件选择窗口中的打开按钮",
                retryable=True,
            )
        self._click_element_or_parent(button)
        deadline = time.time() + 4.0
        while time.time() < deadline:
            if not self._dialog_is_visible(dialog):
                return
            time.sleep(0.2)
        raise WeChatFileSendError(
            code="FILE_DIALOG_OPEN_FAILED",
            message="选择文件后文件窗口仍未关闭，尚未触发发送",
            retryable=True,
        )

    @staticmethod
    def _dialog_is_visible(dialog: Any) -> bool:
        for method_name in ("is_visible", "exists"):
            try:
                method = getattr(dialog, method_name)
                return bool(method())
            except Exception:
                continue
        return False

    def _snapshot_file_markers(self, file_name: str) -> set[tuple[int, int, int, int, int]]:
        markers: set[tuple[int, int, int, int, int]] = set()
        try:
            items = self.window.descendants()
        except Exception:
            return markers
        for item in items:
            if file_name.casefold() not in self._element_text(item).casefold():
                continue
            try:
                rect = item.rectangle()
                markers.add(
                    (
                        self._window_handle(item),
                        int(rect.left),
                        int(rect.top),
                        int(rect.width()),
                        int(rect.height()),
                    )
                )
            except Exception:
                continue
        return markers

    def _file_marker_state(
        self,
        file_name: str,
        baseline: set[tuple[int, int, int, int, int]],
    ) -> str | None:
        edit = self._find_message_edit()
        edit_top: int | None = None
        if edit is not None:
            try:
                edit_top = int(edit.rectangle().top)
            except Exception:
                pass
        try:
            items = self.window.descendants()
        except Exception:
            return None
        states: list[str] = []
        for item in items:
            if file_name.casefold() not in self._element_text(item).casefold():
                continue
            try:
                rect = item.rectangle()
                marker = (
                    self._window_handle(item),
                    int(rect.left),
                    int(rect.top),
                    int(rect.width()),
                    int(rect.height()),
                )
            except Exception:
                continue
            if marker in baseline:
                continue
            if edit_top is None:
                continue
            states.append("preview" if rect.top >= edit_top - 30 else "sent")
        if "sent" in states:
            return "sent"
        if "preview" in states:
            return "preview"
        return None

    def _wait_for_file_preview_or_sent(
        self,
        file_name: str,
        *,
        baseline: set[tuple[int, int, int, int, int]],
        timeout: float,
    ) -> str:
        deadline = time.time() + timeout
        while time.time() < deadline:
            state = self._file_marker_state(file_name, baseline)
            if state is not None:
                return state
            time.sleep(0.25)
        return "unknown"

    def _find_send_button_near_input(self) -> Any | None:
        edit = self._find_message_edit()
        if edit is None:
            return None
        try:
            edit_rect = edit.rectangle()
        except Exception:
            return None
        candidates: list[Any] = []
        for item in self.locator.descendants(self.window, control_type="Button"):
            text = self._element_text(item).strip()
            if text not in SEND_BUTTON_NAMES:
                continue
            try:
                rect = item.rectangle()
                if rect.top >= edit_rect.top - 40 and rect.left >= edit_rect.left:
                    candidates.append(item)
            except Exception:
                continue
        return candidates[0] if candidates else None

    def _send_staged_file(self) -> str:
        button = self._find_send_button_near_input()
        if button is not None:
            self._click_element_or_parent(button)
            time.sleep(0.5)
            return "button"
        if self._click_send_button_visual(timeout=1.5):
            time.sleep(0.5)
            return "image"
        edit = self._find_message_edit()
        if edit is not None:
            try:
                edit.click_input()
            except Exception:
                pass
        self._send_keys("{ENTER}")
        time.sleep(0.5)
        return "enter"

    def _verify_outgoing_file(
        self,
        file_name: str,
        *,
        baseline: set[tuple[int, int, int, int, int]],
        timeout: float,
    ) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._file_marker_state(file_name, baseline) == "sent":
                return True
            time.sleep(0.25)
        return False

    def _resolve_executable(self) -> Path:
        if self.launch_path:
            path = Path(self.launch_path).expanduser()
            if path.exists():
                return path
        for candidate in self._candidate_executable_paths():
            path = Path(candidate)
            if path.exists():
                return path
        raise FileNotFoundError("Unable to locate WeChat.exe")

    def _launch_wechat_by_name(self, application_cls: Any) -> bool:
        for launch_name in WECHAT_LAUNCH_NAMES:
            try:
                self.app = application_cls(backend="uia").start(launch_name)
            except Exception:
                logger.debug(
                    "Failed to start WeChat by name with pywinauto: %s",
                    launch_name,
                    exc_info=True,
                )
            if self._wait_for_main_window(timeout=2.0):
                return True

            if self._shell_start_by_name(launch_name) and self._wait_for_main_window(timeout=2.0):
                return True
        return False

    @staticmethod
    def _shell_start_by_name(launch_name: str) -> bool:
        try:
            subprocess.Popen(  # noqa: S603,S607
                ["cmd", "/c", "start", "", launch_name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return True
        except Exception:
            logger.debug("Failed to shell-start WeChat by name: %s", launch_name, exc_info=True)
            return False

    def _wait_for_main_window(self, *, timeout: float) -> bool:
        deadline = time.time() + max(0.0, timeout)
        while time.time() < deadline:
            if self.window_manager is None:
                return False
            self.window = self.window_manager.find_main_window()
            if self.window is not None:
                self._normalize_current_window()
                return True
            time.sleep(0.5)
        return False

    def _candidate_executable_paths(self) -> list[Path]:
        candidates: list[Path] = [Path(candidate) for candidate in WECHAT_EXE_CANDIDATES]
        program_roots = [
            environ.get("ProgramFiles"),
            environ.get("ProgramFiles(x86)"),
            environ.get("LOCALAPPDATA"),
            environ.get("APPDATA"),
        ]
        relative_paths = (
            Path("Tencent") / "WeChat" / "WeChat.exe",
            Path("Tencent") / "Weixin" / "Weixin.exe",
            Path("Programs") / "Tencent" / "WeChat" / "WeChat.exe",
            Path("Programs") / "Tencent" / "Weixin" / "Weixin.exe",
        )
        for root in program_roots:
            if not root:
                continue
            root_path = Path(root)
            candidates.extend(root_path / relative for relative in relative_paths)
        candidates.extend(self._registry_executable_paths())

        unique: list[Path] = []
        seen: set[str] = set()
        for candidate in candidates:
            key = str(candidate).lower()
            if key in seen:
                continue
            seen.add(key)
            unique.append(candidate)
        return unique

    @staticmethod
    def _registry_executable_paths() -> list[Path]:
        try:
            import winreg
        except Exception:
            return []

        result: list[Path] = []
        app_paths = (
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\WeChat.exe",
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\Weixin.exe",
        )
        roots = (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE)
        for root in roots:
            for subkey in app_paths:
                try:
                    with winreg.OpenKey(root, subkey) as key:
                        value, _ = winreg.QueryValueEx(key, "")
                except Exception:
                    continue
                if value:
                    result.append(Path(str(value)))
        return result

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
        manager.normalize_all(active_window=self.window)

    def _normalize_windows_for_screenshot(self) -> None:
        manager = self._get_window_manager(create=False)
        if manager is not None:
            manager.normalize_all(active_window=self.window)
            return
        if self.window is None:
            return
        try:
            self.window.set_focus()
        except Exception:
            pass

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
        deadline = time.time() + 18.0
        fallback = None
        while time.time() < deadline:
            target, fallback = self._find_service_account_result(account_name)
            if target is not None:
                self._click_element_or_parent(target)
                if self._confirm_after_search_result_click(
                    account_name,
                    before_handles=before_handles,
                ):
                    return
            text_target = self._find_account_name_result(account_name)
            if text_target is not None:
                self._click_element_or_parent(text_target)
                if self._confirm_after_search_result_click(
                    account_name,
                    before_handles=before_handles,
                ):
                    return
            if self._click_green_account_text(account_name):
                if self._confirm_after_search_result_click(
                    account_name,
                    before_handles=before_handles,
                ):
                    return
            time.sleep(0.4)

        if fallback is not None:
            self._click_element_or_parent(fallback)
            if self._confirm_after_search_result_click(
                account_name,
                before_handles=before_handles,
            ):
                return

        if self._click_green_account_text(account_name):
            if self._confirm_after_search_result_click(
                account_name,
                before_handles=before_handles,
            ):
                return

        if self._click_first_search_result_visual():
            if self._confirm_after_search_result_click(
                account_name,
                before_handles=before_handles,
            ):
                return

        self._send_keys("{ENTER}")
        self._confirm_after_search_result_click(
            account_name,
            before_handles=before_handles,
        )

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

    def _find_account_name_result(self, account_name: str) -> Any | None:
        import re

        try:
            items = self.window.descendants()
        except Exception:
            return None

        name_pattern = re.compile(re.escape(account_name), re.IGNORECASE)
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
            for container, combined in reversed(combined_by_container):
                if name_pattern.search(combined):
                    return container
            return self._nearest_click_target(item)
        return None

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

    def _confirm_after_search_result_click(
        self,
        account_name: str,
        *,
        before_handles: set[int] | None,
    ) -> bool:
        time.sleep(1.2)
        self._switch_to_account_window(account_name, before_handles=before_handles)
        if not self._needs_official_account_home_confirmation():
            return True
        return self._wait_for_official_account_home(
            account_name=account_name,
            timeout=8.0,
        )

    def _needs_official_account_home_confirmation(self) -> bool:
        if self.desktop is not None:
            return True
        return self._window_process_name(self.window) == "wechatappex.exe"

    def _wait_for_official_account_home(
        self,
        account_name: str = "",
        *,
        timeout: float,
    ) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._has_official_account_home_marker(account_name):
                return True
            time.sleep(0.4)
        return False

    def _has_official_account_home_marker(self, account_name: str = "") -> bool:
        for window in self._windows_to_scan():
            process_name = self._window_process_name(window)
            combined = self._combined_text(window)
            has_service_title = "服务号" in combined or "Service Account" in combined
            has_account_hint = bool(account_name and account_name in combined)
            if has_service_title and (process_name == "wechatappex.exe" or has_account_hint):
                self.window = window
                try:
                    self.window.set_focus()
                except Exception:
                    pass
                return True

        if self._has_official_account_template():
            return True
        return False

    def _has_official_account_template(self) -> bool:
        locator = getattr(self, "image_locator", None)
        if locator is None or not hasattr(locator, "find"):
            return False
        try:
            self._normalize_windows_for_screenshot()
            match = locator.find(
                WECHAT_OFFICIAL_ACCOUNT_TEMPLATE,
                region=self._current_window_region(),
                threshold=0.72,
            )
        except Exception:
            return False
        return match is not None

    def _click_souyisou_if_visible(self, *, timeout: float = 1.5) -> bool:
        return self._click_screen_template(
            WECHAT_SEARCH_TEMPLATE,
            threshold=0.74,
            timeout=timeout,
        )

    def _activate_appex_from_taskbar(self, *, timeout: float = 2.0) -> bool:
        return self._click_screen_template(
            WECHAT_APPEX_LOGO_TEMPLATE,
            region="taskbar",
            threshold=0.72,
            timeout=timeout,
        )

    def _activate_main_from_taskbar(self, *, timeout: float = 2.0) -> bool:
        return self._click_screen_template(
            WECHAT_TASKBAR_LOGO_TEMPLATE,
            region="taskbar",
            threshold=0.72,
            timeout=timeout,
        )

    def _click_green_follow_button(self, *, timeout: float = 2.0) -> bool:
        locator = getattr(self, "image_locator", None)
        if locator is None or not hasattr(locator, "click_green_button"):
            return False

        deadline = time.time() + max(0.0, timeout)
        while True:
            try:
                self._normalize_windows_for_screenshot()
                match = locator.click_green_button(region=self._current_window_region())
            except Exception:
                return False
            if match is not None:
                time.sleep(0.8)
                return True
            if time.time() >= deadline:
                return False
            time.sleep(0.2)

    def _click_follow_button_visual(self, *, timeout: float = 2.0) -> bool:
        return self._click_green_follow_button(timeout=timeout)

    def _is_followed_state(self) -> bool:
        for window in self._windows_to_scan():
            combined = self._combined_text(window)
            if "已关注" in combined and any(
                marker in combined
                for marker in ("私信", "发消息", "发送消息", "Message")
            ):
                self.window = window
                return True
        return False

    def _find_follow_button_target(self) -> Any | None:
        self._require_window()
        for window in self._windows_to_scan():
            try:
                items = window.descendants()
            except Exception:
                items = []
            for item in items:
                title = self._element_text(item).strip()
                if not title or "已关注" in title:
                    continue
                if title in {"关注", "Follow", "Subscribe"}:
                    self.window = window
                    return item
        return None

    def _click_message_box_visual(self, *, timeout: float = 2.0) -> bool:
        return self._click_screen_template(
            WECHAT_MESSAGE_BOX_TEMPLATE,
            current_window_region=True,
            threshold=0.72,
            timeout=timeout,
        )

    def _click_send_button_visual(self, *, timeout: float = 1.5) -> bool:
        return self._click_screen_template(
            WECHAT_SEND_BUTTON_TEMPLATE,
            current_window_region=True,
            threshold=0.74,
            timeout=timeout,
        )

    def _click_green_account_text(self, account_name: str, *, timeout: float = 0.8) -> bool:
        locator = getattr(self, "image_locator", None)
        if locator is None or not (
            hasattr(locator, "click_green_text") or hasattr(locator, "click_first_result_green_text")
        ):
            return False

        deadline = time.time() + max(0.0, timeout)
        while True:
            try:
                self._normalize_windows_for_screenshot()
                region = self._search_result_region() or self._current_window_region()
                if hasattr(locator, "click_first_result_green_text"):
                    match = locator.click_first_result_green_text(
                        region=region,
                        text=account_name,
                    )
                else:
                    match = locator.click_green_text(
                        region=region,
                        text=account_name,
                    )
            except Exception:
                return False
            if match is not None:
                time.sleep(0.35)
                return True
            if time.time() >= deadline:
                return False
            time.sleep(0.2)

    def _click_search_accounts_tab(self, *, timeout: float = 3.0) -> bool:
        deadline = time.time() + max(0.0, timeout)
        while True:
            target = self._find_search_accounts_tab()
            if target is not None:
                self._click_element_or_parent(target)
                time.sleep(SEARCH_ACCOUNTS_TAB_SETTLE_SECONDS)
                return True
            if time.time() >= deadline:
                break
            time.sleep(0.2)
        clicked = self._click_window_relative(*SEARCH_ACCOUNTS_TAB_REL)
        if clicked:
            time.sleep(SEARCH_ACCOUNTS_TAB_SETTLE_SECONDS)
        return clicked

    def _find_search_accounts_tab(self) -> Any | None:
        self._require_window()
        try:
            items = self.window.descendants()
        except Exception:
            return None
        for item in items:
            title = self._element_text(item).strip()
            if title in {"账号", "Account", "Accounts"}:
                return item
        return None

    def _click_first_account_result_after_tab(
        self,
        account_name: str,
        *,
        before_handles: set[int] | None,
    ) -> bool:
        if self._click_green_account_text(account_name, timeout=1.2):
            if self._confirm_after_search_result_click(
                account_name,
                before_handles=before_handles,
            ):
                return True

        text_target = self._find_account_name_result(account_name)
        if text_target is not None:
            self._click_element_or_parent(text_target)
            if self._confirm_after_search_result_click(
                account_name,
                before_handles=before_handles,
            ):
                return True

        if self._click_first_search_result_visual():
            return self._confirm_after_search_result_click(
                account_name,
                before_handles=before_handles,
            )
        return False

    def _find_search_result_anchor(self, *, timeout: float = 0.8) -> ImageMatch | None:
        locator = getattr(self, "image_locator", None)
        if locator is None or not hasattr(locator, "find"):
            return self._last_search_result_anchor

        deadline = time.time() + max(0.0, timeout)
        while True:
            try:
                self._normalize_windows_for_screenshot()
                match = locator.find(
                    WECHAT_SEARCH_TEMPLATE,
                    region=None,
                    threshold=0.72,
                )
            except Exception:
                match = None
            if match is not None and hasattr(match, "x") and hasattr(match, "y"):
                self._last_search_result_anchor = match
                return match
            if time.time() >= deadline:
                return self._last_search_result_anchor
            time.sleep(0.2)

    def _search_result_region(self) -> tuple[int, int, int, int] | None:
        anchor = self._find_search_result_anchor(timeout=0.3)
        if anchor is None:
            return None
        width, height = SEARCH_RESULT_REGION_SIZE
        left = max(0, int(anchor.x - 70))
        top = max(0, int(anchor.y - 70))
        return left, top, width, height

    def _click_screen_template(
        self,
        template_name: str,
        *,
        region: tuple[int, int, int, int] | str | None = None,
        current_window_region: bool = False,
        threshold: float = 0.78,
        timeout: float = 1.5,
    ) -> bool:
        locator = getattr(self, "image_locator", None)
        if locator is None:
            return False

        deadline = time.time() + max(0.0, timeout)
        while True:
            try:
                self._normalize_windows_for_screenshot()
                target_region = self._current_window_region() if current_window_region else region
                match = locator.click(
                    template_name,
                    region=target_region,
                    threshold=threshold,
                )
            except Exception:
                return False
            if match is not None:
                time.sleep(0.35)
                return True
            if time.time() >= deadline:
                return False
            time.sleep(0.2)

    def _click_first_search_result_visual(self) -> bool:
        locator = getattr(self, "image_locator", None)
        if locator is None or not hasattr(locator, "click_xy"):
            return False

        anchor = self._find_search_result_anchor(timeout=0.5)
        if anchor is not None:
            offset_x, offset_y = SEARCH_RESULT_FIRST_ACCOUNT_OFFSET
            x = int(anchor.x + offset_x)
            y = int(anchor.y + offset_y)
            try:
                locator.click_xy(x, y)
            except Exception:
                return False
            time.sleep(0.35)
            return True
        return self._click_window_relative(0.19, 0.39)

    def _click_window_relative(self, rx: float, ry: float) -> bool:
        self._normalize_windows_for_screenshot()
        region = self._current_window_region()
        if region is None:
            return False
        locator = getattr(self, "image_locator", None)
        if locator is not None and hasattr(locator, "click_relative"):
            try:
                if locator.click_relative(region, rx, ry):
                    time.sleep(0.35)
                    return True
            except Exception:
                pass
        try:
            self._click_relative(self.window, rx, ry)
        except Exception:
            return False
        time.sleep(0.35)
        return True

    def _wait_for_search_result_window(
        self,
        account_name: str,
        *,
        before_handles: set[int] | None,
        wait_seconds: float,
    ) -> bool:
        deadline = time.time() + max(0.0, wait_seconds)
        while True:
            remaining = max(0.0, deadline - time.time())
            if self._switch_to_account_window(
                account_name,
                timeout=min(1.0, max(0.1, remaining)),
                before_handles=before_handles,
            ):
                return True
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            time.sleep(min(0.5, remaining))
        return False

    def _current_window_region(self) -> tuple[int, int, int, int] | None:
        try:
            rect = self.window.rectangle()
            return int(rect.left), int(rect.top), int(rect.width()), int(rect.height())
        except Exception:
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
                manager.normalize_all(active_window=self.window)
                return True

        desktop = self._get_desktop(create=False)
        if desktop is None:
            return False

        if self._activate_appex_from_taskbar(timeout=min(2.0, timeout)):
            manager = self._get_window_manager(create=False)
            if manager is not None:
                new_appex = manager.latest_new_appex(
                    before_handles or set(),
                    title_hint=account_name,
                    timeout=min(timeout, 1.0),
                )
                if new_appex is not None:
                    self.window = manager.normalize(new_appex, app_ex=True)
                    manager.normalize_all(active_window=self.window)
                    return True

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
                    if manager is not None:
                        manager.normalize_all(active_window=self.window)
                    return True
                if has_account_hint:
                    fallback = window
            if fallback is not None and time.time() + 0.3 >= deadline:
                self.window = (
                    manager.normalize(fallback)
                    if manager is not None
                    else fallback
                )
                if manager is not None:
                    manager.normalize_all(active_window=self.window)
                return True
            time.sleep(0.3)
        if fallback is not None:
            self.window = (
                manager.normalize(fallback)
                if manager is not None
                else fallback
            )
            if manager is not None:
                manager.normalize_all(active_window=self.window)
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


def _format_file_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / 1024 / 1024:.1f} MB"


def _default_file_send_confirmation(
    *,
    recipient: str,
    file: ValidatedLocalFile,
) -> bool:
    from src.core.user_interaction import get_user_interaction_broker

    broker = get_user_interaction_broker()
    broker.set_title("确认发送微信文件")
    warning = (
        "\n\n警告：该文件可能包含可执行内容。确认收件人和文件来源后再发送。"
        if file.potentially_dangerous
        else ""
    )
    answer = broker.prompt(
        "准备通过微信发送文件\n\n"
        f"发送对象：{recipient}\n"
        f"文件名称：{file.name}\n"
        f"文件大小：{_format_file_size(file.size_bytes)}\n"
        f"文件路径：{file.path}"
        f"{warning}\n\n"
        "[确认发送] [取消]"
    )
    normalized = str(answer or "").strip().lower()
    return normalized in {
        "确认发送",
        "确认",
        "发送",
        "approve",
        "yes",
        "y",
        "true",
        "1",
        "是",
    }


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
    if looks_like_windows_file_path(text):
        raise WeChatFileSendError(
            code="ROUTE_VALIDATION_FAILED",
            message="本地文件路径必须使用微信联系人发送文件技能",
        )
    client = automation or PywinautoWechatAutomation(launch_path=launch_path)
    client.open()
    client.search_contact(contact)
    client.send_message(text)
    return {"success": True, "contact_name": contact, "message": text}


def send_contact_file(
    *,
    recipient_name: str,
    file_path: str,
    launch_path: str | None = None,
    automation: PywinautoWechatAutomation | None = None,
    confirm_fn: Callable[..., bool] | None = None,
    log_fn: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Validate, confirm, and submit one local file to a verified WeChat chat."""

    recipient = _clean_required(recipient_name, "recipient name")
    emit = log_fn or (lambda message: logger.info("WeChat file send: %s", message))
    emit("正在验证文件")
    validated = validate_local_file(file_path)
    emit(f"文件已验证：{validated.name}（{_format_file_size(validated.size_bytes)}）")

    client = automation or PywinautoWechatAutomation(launch_path=launch_path)
    emit("正在打开微信")
    client.open()

    emit(f"正在查找“{recipient}”")
    contact = client.search_contact_verified(recipient)
    if not contact.verified or not contact.displayed_name:
        raise WeChatFileSendError(
            code="CONTACT_UNVERIFIED",
            message="无法确认微信发送对象",
        )
    emit(f"已确认发送对象：{contact.displayed_name}")

    emit("等待确认发送")
    confirmer = confirm_fn or _default_file_send_confirmation
    if not confirmer(recipient=contact.displayed_name, file=validated):
        return {
            "success": False,
            "cancelled": True,
            "status": "cancelled",
            "code": "USER_CANCELLED",
            "recipient_name": contact.displayed_name,
            "file_name": validated.name,
            "file_size_bytes": validated.size_bytes,
        }

    revalidate_local_file(validated)
    emit("正在选择文件")
    try:
        result = client.send_file(validated.path)
    except WeChatFileSendError as exc:
        if not exc.send_may_have_started:
            raise
        emit("已触发发送，但无法确认结果；请检查聊天记录，不要直接重试")
        return {
            "success": False,
            "status": "unknown",
            "code": "SEND_STATUS_UNKNOWN",
            "message": exc.message,
            "recipient_name": contact.displayed_name,
            "file_name": validated.name,
            "file_size_bytes": validated.size_bytes,
            "method": str(exc.details.get("method") or "unknown"),
            "verified": False,
            "retryable": False,
            "send_may_have_started": True,
        }

    emit("文件发送操作已完成")
    return {
        "success": result.success,
        "status": result.status,
        "recipient_name": contact.displayed_name,
        "file_name": validated.name,
        "file_size_bytes": validated.size_bytes,
        "method": result.method,
        "verified": result.verified,
        "phase": result.phase.value,
    }

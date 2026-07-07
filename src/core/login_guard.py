"""Generic login-popup detection and wait helpers."""

from __future__ import annotations

import os
import time
from typing import Any, Callable
from urllib.parse import urlparse


class GenericLoginGuard:
    """Pause execution when a login modal appears and resume after auth cookies change."""

    def __init__(
        self,
        page_getter: Callable[[], Any],
        *,
        browser_manager: Any | None = None,
        log_fn: Callable[[str], None] | None = None,
        panel_manager_getter: Callable[[], Any] | None = None,
        enabled: bool = True,
    ) -> None:
        self._page_getter = page_getter
        self._browser_manager = browser_manager
        self._log_fn = log_fn
        self._panel_manager_getter = panel_manager_getter
        self._enabled = enabled
        self._waiting = False

    def maybe_wait(self, action_name: str) -> bool:
        if not self._enabled or self._waiting:
            return False
        prompt = self._detect_login_prompt()
        if prompt.get("login_required"):
            self._wait_for_completion(action_name)
            return True
        return False

    @staticmethod
    def script_has_explicit_login_flow(script_code: str) -> bool:
        markers = (
            "ensure_auth(",
            "_detect_login_state",
            "_detect_login_status",
            "_wait_for_login",
            "_wait_until_logged_in",
            "PHONE_LOGIN_TEXT",
            "click_get_code",
            "save_cookies(",
            "load_cookies(",
            "\u9a8c\u8bc1\u7801",
            "\u77ed\u4fe1\u767b\u5f55",
            "\u624b\u673a\u53f7\u767b\u5f55",
            "authentication code",
            "two-factor",
        )
        return any(marker in script_code for marker in markers)

    def _page(self) -> Any:
        return self._page_getter()

    def _context(self) -> Any | None:
        context = getattr(self._browser_manager, "_context", None)
        if context is not None:
            return context
        try:
            return getattr(self._page(), "context", None)
        except Exception:
            return None

    def _log(self, message: str) -> None:
        if self._log_fn is not None:
            self._log_fn(message)

    def _hostname(self) -> str:
        try:
            return (urlparse(self._page().url).hostname or "").lower()
        except Exception:
            return ""

    def _domain(self) -> str:
        current_domain = str(
            getattr(self._browser_manager, "current_domain", "") or ""
        ).strip().lower()
        if current_domain:
            return current_domain
        host = self._hostname()
        if host.endswith("mail.google.com"):
            return "gmail"
        labels = [part for part in host.split(".") if part and part != "www"]
        return labels[0] if labels else "default"

    def _fingerprint(self) -> tuple:
        context = self._context()
        if context is None:
            return ()
        try:
            state = context.storage_state()
        except Exception:
            return ()

        host = self._hostname()
        labels = host.split(".") if host else []
        root = ".".join(labels[-2:]) if len(labels) >= 2 else host

        def matches(value: str) -> bool:
            if not host:
                return True
            target = value.strip(".").lower()
            if not target:
                return True
            return (
                host == target
                or host.endswith("." + target)
                or target.endswith("." + host)
                or (root and target == root)
                or (root and target.endswith("." + root))
            )

        items = []
        for cookie in state.get("cookies", []):
            domain = str(cookie.get("domain", "") or "")
            if matches(domain):
                items.append(
                    (
                        "cookie",
                        domain.lower(),
                        str(cookie.get("name", "")).lower(),
                        str(cookie.get("value", "")),
                    )
                )
        for origin in state.get("origins", []):
            origin_url = str(origin.get("origin", "") or "")
            origin_host = (urlparse(origin_url).hostname or "").lower()
            if origin_host and not matches(origin_host):
                continue
            for item in origin.get("localStorage", []):
                items.append(
                    (
                        "localStorage",
                        origin_host,
                        str(item.get("name", "")).lower(),
                        str(item.get("value", "")),
                    )
                )
        return tuple(sorted(items))

    def _storage_state_logged_in(self, domain: str) -> bool:
        context = self._context()
        if context is None:
            return False
        try:
            state = context.storage_state()
        except Exception:
            return False

        cookies = {
            str(cookie.get("name", "")).lower(): str(cookie.get("value", "")).strip()
            for cookie in state.get("cookies", [])
        }
        if domain == "zhihu":
            return bool(cookies.get("z_c0"))
        if domain == "xiaohongshu":
            return bool(
                cookies.get("web_session")
                and cookies.get("id_token")
                and cookies.get("x-rednote-datactry")
                and cookies.get("x-rednote-holderctry")
            )

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

    def _detect_login_prompt(self) -> dict:
        try:
            result = self._page().evaluate(
                """
(() => {
  /* GENERIC_LOGIN_PROMPT_DETECTOR */
  const LOGIN_TEXT = '\\u767b\\u5f55';
  const LOGIN_ALT_TEXT = '\\u767b\\u9646';
  const visible = (el) => {
    const style = window.getComputedStyle(el);
    return style && style.visibility !== 'hidden' && style.display !== 'none' &&
      (el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  };
  const compact = (el) => (el.innerText || el.textContent || '').trim().replace(/\\s+/g, '');
  const hasLoginText = (text) => text.includes(LOGIN_TEXT) || text.includes(LOGIN_ALT_TEXT);
  const modalLike = (el) => {
    if (!visible(el)) return false;
    const rect = el.getBoundingClientRect();
    const style = window.getComputedStyle(el);
    const role = (el.getAttribute('role') || '').toLowerCase();
    const tag = (el.tagName || '').toLowerCase();
    const className = String(el.className || '').toLowerCase();
    const ariaModal = el.getAttribute('aria-modal') === 'true';
    const z = Number.parseInt(style.zIndex || '0', 10) || 0;
    const largeEnough = rect.width >= 220 && rect.height >= 120;
    const onScreen = rect.bottom > 0 && rect.right > 0 &&
      rect.left < window.innerWidth && rect.top < window.innerHeight;
    const fixedLayer = ['fixed', 'absolute', 'sticky'].includes(style.position) || z >= 10;
    const modalClass = /(modal|popup|dialog|overlay|mask|passport|login|auth|sign)/i.test(className);
    const pageChrome = tag === 'header' || tag === 'nav' ||
      /(header|navbar|nav-|topbar|toolbar|menu|sidebar|footer)/i.test(className);
    const centerX = rect.left + rect.width / 2;
    const centerY = rect.top + rect.height / 2;
    const centered = centerX > window.innerWidth * 0.2 &&
      centerX < window.innerWidth * 0.8 &&
      centerY > window.innerHeight * 0.15 &&
      centerY < window.innerHeight * 0.85;
    if (pageChrome) return false;
    return onScreen && (
      role === 'dialog' ||
      role === 'alertdialog' ||
      ariaModal ||
      (largeEnough && modalClass) ||
      (largeEnough && fixedLayer && centered)
    );
  };
  const loginNodes = Array.from(document.querySelectorAll(
    'button,[role="button"],a,div,section,article,form,span,p'
  )).filter(visible).map((el) => ({el, text: compact(el)}))
    .filter((item) => hasLoginText(item.text) && item.text.length <= 1200);
  for (const item of loginNodes) {
    let node = item.el;
    for (let depth = 0; node && depth < 8; depth += 1, node = node.parentElement) {
      if (!modalLike(node)) continue;
      const modalText = compact(node);
      if (!hasLoginText(modalText)) continue;
      return {
        success: true,
        login_required: true,
        reason: 'login_text_in_modal',
        text: item.text.slice(0, 120),
        modal_text: modalText.slice(0, 200),
        url: location.href
      };
    }
  }
  return {success: true, login_required: false, url: location.href};
})()
"""
            )
            if isinstance(result, dict):
                return result
        except Exception as exc:
            return {
                "success": False,
                "login_required": False,
                "error": f"{type(exc).__name__}: {exc}",
            }
        return {"success": False, "login_required": False}

    def _is_page_closed(self, page: Any | None = None) -> bool:
        try:
            current_page = page or self._page()
            is_closed = getattr(current_page, "is_closed", None)
            if callable(is_closed):
                return bool(is_closed())
        except Exception:
            return True
        return False

    def _wait_for_completion(self, action_name: str) -> None:
        self._waiting = True
        try:
            page = self._page()
            domain = self._domain()
            initial_fingerprint = self._fingerprint()
            timeout_seconds = int(os.environ.get("AUTO_LOGIN_WAIT_SECONDS", "300") or "300")
            deadline = time.monotonic() + max(1, timeout_seconds)
            message = (
                f"Detected login popup on {domain} after {action_name}. "
                "Please complete login in the browser."
            )
            self._log(message)
            try:
                if self._panel_manager_getter is not None:
                    panel = self._panel_manager_getter()
                    panel.toggle(page, True)
                    panel.log(page, message)
            except Exception:
                pass

            known_domains = {
                "bilibili",
                "douyin",
                "github",
                "gmail",
                "xiaohongshu",
                "zhihu",
            }
            while True:
                if self._is_page_closed(page):
                    raise RuntimeError("Page closed while waiting for manual login")
                prompt_gone = not self._detect_login_prompt().get("login_required")
                current_fingerprint = self._fingerprint()
                known_logged_in = (
                    domain in known_domains and self._storage_state_logged_in(domain)
                )
                if prompt_gone and (
                    known_logged_in or current_fingerprint != initial_fingerprint
                ):
                    try:
                        if self._browser_manager is not None:
                            self._browser_manager.save_auth(domain)
                    except Exception:
                        pass
                    self._log(f"{domain} login detected; continuing task")
                    return

                if time.monotonic() >= deadline:
                    raise RuntimeError(
                        "Timed out waiting for manual login after detecting login popup"
                    )

                try:
                    page.wait_for_timeout(1000)
                except Exception as exc:
                    message = str(exc)
                    if "TargetClosed" in message or "closed" in message.lower():
                        raise RuntimeError(
                            "Page closed while waiting for manual login"
                        ) from exc
                    raise
        finally:
            self._waiting = False

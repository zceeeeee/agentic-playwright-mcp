"""Xiaohongshu note comment adapter."""

try:
    from src.layer_2 import controls as _controls
except Exception:
    _controls = None


DEFAULT_LOGIN_URL = "https://www.xiaohongshu.com/login"
DEFAULT_NOTE_URL = "https://www.xiaohongshu.com/explore"


def _default_log(message):
    print(f"[LOG] {message}")


def _safe_call(func, default, *args):
    try:
        return func(*args)
    except Exception:
        return default


def _resolve_log(log_fn):
    if log_fn is not None:
        return log_fn
    try:
        return log
    except NameError:
        return _default_log


def _js_string(value):
    text = str(value)
    text = text.replace("\\", "\\\\")
    text = text.replace('"', '\\"')
    text = text.replace("\n", "\\n")
    text = text.replace("\r", "\\r")
    return '"' + text + '"'


def _run_js_dict(run_js_fn, code):
    try:
        result = run_js_fn(code)
    except Exception as exc:
        return {"success": False, "error": f"{type(exc).__name__}: {exc}"}
    if isinstance(result, dict):
        return result
    return {"success": bool(result), "result": result}


def _detect_login_state(run_js_fn):
    return _run_js_dict(
        run_js_fn,
        """
(() => {
  const PHONE_LOGIN_TEXT = '\\u624b\\u673a\\u53f7\\u767b\\u5f55';
  const LOGIN_REQUIRED_TEXT = '\\u767b\\u5f55\\u540e\\u63a8\\u8350\\u66f4\\u61c2\\u4f60\\u7684\\u7b14\\u8bb0';
  const visible = (el) => {
    const style = window.getComputedStyle(el);
    return style && style.visibility !== 'hidden' && style.display !== 'none' &&
      (el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  };
  const compactText = (el) => (el.innerText || el.textContent || '').trim().replace(/\\s+/g, '');
  const phoneLogin = Array.from(document.querySelectorAll('body,button,[role="button"],a,div,span,p'))
    .some((el) => visible(el) && compactText(el).includes(PHONE_LOGIN_TEXT));
  const loginRequiredPrompt = Array.from(document.querySelectorAll('body,button,[role="button"],a,div,span,p'))
    .some((el) => visible(el) && compactText(el).includes(LOGIN_REQUIRED_TEXT));
  const requiresLogin = phoneLogin || loginRequiredPrompt;
  return {
    success: true,
    logged_in: !requiresLogin,
    phone_login: phoneLogin,
    has_phone_login_text: phoneLogin,
    login_required_prompt: loginRequiredPrompt,
    url: location.href
  };
})()
""",
    )


def _wait_for_login_completion(run_js_fn, wait_fn, steps, max_wait_seconds, interval_seconds):
    attempts = max(1, int(max_wait_seconds / interval_seconds) + 1)
    for attempt in range(1, attempts + 1):
        state = _detect_login_state(run_js_fn)
        steps.append({"step": f"wait_login_attempt_{attempt}", "result": state})
        if state.get("logged_in"):
            return {"success": True, "attempts": attempt, "state": state}
        if attempt < attempts:
            steps.append(
                {
                    "step": f"wait_before_login_attempt_{attempt + 1}",
                    "result": _safe_call(wait_fn, "", interval_seconds),
                }
            )
    return {
        "success": False,
        "requires_manual_login": True,
        "error": "Timed out waiting for Xiaohongshu login completion",
    }


def _find_comment_input(run_js_fn):
    return _run_js_dict(
        run_js_fn,
        """
(() => {
  const visible = (el) => {
    const style = window.getComputedStyle(el);
    return style && style.visibility !== 'hidden' && style.display !== 'none' &&
      (el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  };
  const candidates = Array.from(document.querySelectorAll(
    '#content-textarea,p.content-input[contenteditable="true"],.engage-bar.active .content-input,[contenteditable="true"],[role="textbox"],textarea'
  )).filter(visible).map((el) => {
    const rect = el.getBoundingClientRect();
    const activeBar = Boolean(el.closest('.engage-bar.active'));
    const label = [
      el.id || '',
      String(el.className || ''),
      el.placeholder || '',
      el.getAttribute('data-placeholder') || '',
      el.getAttribute('aria-label') || ''
    ].join(' ');
    return {el, rect, activeBar, label};
  }).filter((item) => {
    const label = item.label.toLowerCase();
    return item.el.id === 'content-textarea' ||
      item.activeBar ||
      /comment|content-input|评论|留言|回复/.test(label);
  });
  if (!candidates.length) {
    return {success: false, error: 'Xiaohongshu comment input not found'};
  }
  candidates.sort((a, b) => {
    const score = (item) => {
      let value = item.rect.top / 40;
      if (item.el.id === 'content-textarea') value -= 1000;
      if (item.activeBar) value -= 700;
      if (/content-input/.test(item.label)) value -= 300;
      return value;
    };
    return score(a) - score(b);
  });
  const target = candidates[0].el;
  target.scrollIntoView({block: 'center', inline: 'center'});
  target.focus();
  return {
    success: true,
    selector: target.id || target.className || target.tagName,
    method: 'find_xiaohongshu_comment_input'
  };
})()
""",
    )


def _fill_comment(run_js_fn, comment_text):
    return _run_js_dict(
        run_js_fn,
        """
(() => {
  const comment = COMMENT_TEXT;
  const visible = (el) => {
    const style = window.getComputedStyle(el);
    return style && style.visibility !== 'hidden' && style.display !== 'none' &&
      (el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  };
  const escapeHtml = (text) => String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
  const candidates = Array.from(document.querySelectorAll(
    '#content-textarea,p.content-input[contenteditable="true"],.engage-bar.active .content-input,[contenteditable="true"],[role="textbox"],textarea'
  )).filter(visible);
  const target = candidates.find((el) => el.id === 'content-textarea') ||
    candidates.find((el) => el.closest('.engage-bar.active')) ||
    candidates[0];
  if (!target) {
    return {success: false, error: 'Xiaohongshu comment input not found'};
  }
  target.scrollIntoView({block: 'center', inline: 'center'});
  target.focus();
  if (target.tagName === 'TEXTAREA' || target.tagName === 'INPUT') {
    const proto = target.tagName === 'TEXTAREA' ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
    const descriptor = Object.getOwnPropertyDescriptor(proto, 'value');
    if (descriptor && descriptor.set) {
      descriptor.set.call(target, comment);
    } else {
      target.value = comment;
    }
  } else {
    target.innerHTML = String(comment).split('\\n').map((line) => escapeHtml(line) || '<br>').join('<br>');
  }
  try {
    target.dispatchEvent(new InputEvent('beforeinput', {bubbles: true, cancelable: true, inputType: 'insertText', data: comment}));
  } catch (error) {}
  try {
    target.dispatchEvent(new InputEvent('input', {bubbles: true, cancelable: true, inputType: 'insertText', data: comment}));
  } catch (error) {
    target.dispatchEvent(new Event('input', {bubbles: true}));
  }
  target.dispatchEvent(new Event('change', {bubbles: true}));
  target.dispatchEvent(new KeyboardEvent('keyup', {bubbles: true, key: comment.slice(-1) || 'a'}));
  const value = target.value || target.innerText || target.textContent || '';
  return {
    success: value.includes(comment.split('\\n')[0]),
    value: value.substring(0, 120),
    method: 'fill_xiaohongshu_comment'
  };
})()
""".replace("COMMENT_TEXT", _js_string(comment_text)),
    )


def _click_send_comment(run_js_fn):
    return _run_js_dict(
        run_js_fn,
        """
(() => {
  const SEND_TEXT = '\\u53d1\\u9001';
  const visible = (el) => {
    const style = window.getComputedStyle(el);
    return style && style.visibility !== 'hidden' && style.display !== 'none' &&
      (el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  };
  const compactText = (el) => (el.innerText || el.textContent || '').trim().replace(/\\s+/g, '');
  const buttons = Array.from(document.querySelectorAll(
    '.engage-bar.active button.btn.submit,button.btn.submit,button,[role="button"],div,span'
  )).filter(visible).map((el) => {
    const rect = el.getBoundingClientRect();
    const text = compactText(el);
    const inEngageBar = Boolean(el.closest('.engage-bar.active'));
    const disabled = Boolean(el.disabled || el.getAttribute('disabled') !== null || el.getAttribute('aria-disabled') === 'true');
    const submitClass = /submit/i.test(String(el.className || ''));
    return {el, rect, text, inEngageBar, disabled, submitClass};
  }).filter((item) => item.text === SEND_TEXT || (item.text.includes(SEND_TEXT) && item.submitClass));
  if (!buttons.length) {
    return {success: false, error: 'Xiaohongshu send comment button not found'};
  }
  buttons.sort((a, b) => {
    const score = (item) => {
      let value = item.rect.top / 50;
      if (item.inEngageBar) value -= 1000;
      if (item.submitClass) value -= 500;
      if (item.disabled) value += 2000;
      value -= item.rect.left / 100;
      return value;
    };
    return score(a) - score(b);
  });
  const target = buttons[0].el.closest('button,[role="button"]') || buttons[0].el;
  if (buttons[0].disabled) {
    return {success: false, error: 'Xiaohongshu send comment button is disabled', text: buttons[0].text};
  }
  target.scrollIntoView({block: 'center', inline: 'center'});
  target.click();
  return {success: true, text: buttons[0].text, method: 'click_xiaohongshu_send_comment'};
})()
""",
    )


def _retry(step_name, action, steps, wait_fn, attempts=5, interval=1):
    last_result = None
    for attempt in range(1, attempts + 1):
        result = action()
        last_result = result
        steps.append({"step": step_name if attempt == 1 else f"{step_name}_retry_{attempt}", "result": result})
        if isinstance(result, dict) and result.get("success"):
            return result
        if attempt < attempts:
            steps.append({"step": f"wait_before_{step_name}_retry_{attempt + 1}", "result": _safe_call(wait_fn, "", interval)})
    return last_result or {"success": False, "error": f"{step_name} failed"}


def run(
    comment_text,
    note_url=DEFAULT_NOTE_URL,
    *,
    login_url=DEFAULT_LOGIN_URL,
    max_wait_seconds=300,
    wait_seconds=1,
    goto_fn=None,
    run_js_fn=None,
    wait_fn=None,
    get_url_fn=None,
    get_text_fn=None,
    log_fn=None,
):
    """Ensure Xiaohongshu login, open a note, fill the comment box, and click send."""
    if goto_fn is None:
        goto_fn = _controls.goto if _controls is not None else goto
    if run_js_fn is None:
        run_js_fn = _controls.run_js if _controls is not None else run_js
    if wait_fn is None:
        wait_fn = _controls.wait if _controls is not None else wait
    if get_url_fn is None:
        get_url_fn = _controls.get_page_url if _controls is not None else get_url
    if get_text_fn is None:
        get_text_fn = _controls.get_page_text if _controls is not None else get_text

    log_fn = _resolve_log(log_fn)
    steps = []

    try:
        comment = str(comment_text or "").strip()
        url = str(note_url or "").strip()
        if not comment:
            raise ValueError("Xiaohongshu comment requires comment text")
        if not url or "xiaohongshu.com" not in url:
            raise ValueError("Xiaohongshu comment requires a Xiaohongshu note URL")

        steps.append({"step": "navigate_login", "result": goto_fn(login_url)})
        if wait_seconds:
            steps.append({"step": "wait_after_login_navigation", "result": wait_fn(wait_seconds)})

        login_state = _detect_login_state(run_js_fn)
        steps.append({"step": "detect_login_state", "result": login_state})
        if not login_state.get("logged_in"):
            log_fn("Please complete Xiaohongshu login in the browser before commenting.")
            wait_result = _wait_for_login_completion(
                run_js_fn,
                wait_fn,
                steps,
                max_wait_seconds=max_wait_seconds,
                interval_seconds=2,
            )
            steps.append({"step": "manual_login_completion", "result": wait_result})
            if not wait_result.get("success"):
                return {
                    "success": False,
                    "requires_manual_login": True,
                    "error": "Please complete Xiaohongshu login before commenting",
                    "steps": steps,
                }

        steps.append({"step": "navigate_note", "result": goto_fn(url)})
        steps.append({"step": "wait_after_note_navigation", "result": _safe_call(wait_fn, "", 2)})

        note_login_state = _detect_login_state(run_js_fn)
        steps.append({"step": "detect_note_login_state", "result": note_login_state})
        if not note_login_state.get("logged_in"):
            log_fn("Please complete Xiaohongshu login in the browser before commenting.")
            wait_result = _wait_for_login_completion(
                run_js_fn,
                wait_fn,
                steps,
                max_wait_seconds=max_wait_seconds,
                interval_seconds=2,
            )
            steps.append({"step": "manual_login_completion_after_note_navigation", "result": wait_result})
            if not wait_result.get("success"):
                return {
                    "success": False,
                    "requires_manual_login": True,
                    "error": "Please complete Xiaohongshu login before commenting",
                    "steps": steps,
                }

        find_result = _retry(
            "find_comment_input",
            lambda: _find_comment_input(run_js_fn),
            steps,
            wait_fn,
            attempts=5,
            interval=1,
        )
        if not find_result.get("success"):
            return {"success": False, "error": "Failed to find Xiaohongshu comment input", "steps": steps}

        fill_result = _retry(
            "fill_comment",
            lambda: _fill_comment(run_js_fn, comment),
            steps,
            wait_fn,
            attempts=5,
            interval=1,
        )
        if not fill_result.get("success"):
            return {"success": False, "error": "Failed to fill Xiaohongshu comment", "steps": steps}

        send_result = _retry(
            "click_send_comment",
            lambda: _click_send_comment(run_js_fn),
            steps,
            wait_fn,
            attempts=5,
            interval=1,
        )
        if not send_result.get("success"):
            return {"success": False, "error": "Failed to click Xiaohongshu send comment button", "steps": steps}

        log_fn("Xiaohongshu comment sent successfully")
        return {
            "success": True,
            "comment": comment,
            "note_url": url,
            "url": _safe_call(get_url_fn, ""),
            "steps": steps,
            "message": "Xiaohongshu comment filled and send button clicked.",
        }
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        log_fn(f"Xiaohongshu comment failed: {error}")
        return {"success": False, "error": error, "steps": steps}

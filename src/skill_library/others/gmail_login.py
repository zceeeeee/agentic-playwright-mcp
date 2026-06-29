"""Gmail login adapter.

The skill opens Gmail, fills the account email and password, handles the
"choose a sign-in method" page by selecting the first method, waits for the
user to enter a verification code, then submits and verifies Gmail is loaded.
"""

try:
    from src.layer_2 import controls as _controls
except Exception:
    _controls = None


DEFAULT_LOGIN_URL = "https://mail.google.com/mail?hl=zh-CN"
DEFAULT_CODE_WAIT_SECONDS = 30


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


def _fill_email(run_js_fn, email):
    return _run_js_dict(
        run_js_fn,
        """
(() => {
  const value = EMAIL_VALUE;
  const visible = (el) => {
    const style = window.getComputedStyle(el);
    return style && style.visibility !== 'hidden' && style.display !== 'none' &&
      (el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  };
  const target = Array.from(document.querySelectorAll(
    'input[type="email"],input#identifierId,input[name="identifier"],input[autocomplete="username"],input[aria-label*="邮箱"],input[aria-label*="email" i]'
  )).filter(visible)[0];
  if (!target) {
    return {success: false, error: 'Gmail email input not found'};
  }
  const descriptor = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value');
  target.scrollIntoView({block: 'center', inline: 'center'});
  target.focus();
  target.click();
  if (descriptor && descriptor.set) {
    descriptor.set.call(target, value);
  } else {
    target.value = value;
  }
  target.dispatchEvent(new Event('input', {bubbles: true}));
  target.dispatchEvent(new Event('change', {bubbles: true}));
  return {
    success: (target.value || '').trim() === value,
    value: target.value || '',
    id: target.id || '',
    name: target.name || ''
  };
})()
""".replace("EMAIL_VALUE", _js_string(email)),
    )


def _fill_password(run_js_fn, password):
    return _run_js_dict(
        run_js_fn,
        """
(() => {
  const value = PASSWORD_VALUE;
  const visible = (el) => {
    const style = window.getComputedStyle(el);
    return style && style.visibility !== 'hidden' && style.display !== 'none' &&
      (el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  };
  const target = Array.from(document.querySelectorAll(
    'input[type="password"],input[name="Passwd"],input[autocomplete="current-password"],input[aria-label*="密码"],input[aria-label*="password" i]'
  )).filter(visible)[0];
  if (!target) {
    return {success: false, error: 'Gmail password input not found'};
  }
  const descriptor = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value');
  target.scrollIntoView({block: 'center', inline: 'center'});
  target.focus();
  target.click();
  if (descriptor && descriptor.set) {
    descriptor.set.call(target, value);
  } else {
    target.value = value;
  }
  target.dispatchEvent(new Event('input', {bubbles: true}));
  target.dispatchEvent(new Event('change', {bubbles: true}));
  return {
    success: (target.value || '') === value,
    value_length: (target.value || '').length,
    id: target.id || '',
    name: target.name || ''
  };
})()
""".replace("PASSWORD_VALUE", _js_string(password)),
    )


def _click_next(run_js_fn):
    return _run_js_dict(
        run_js_fn,
        """
(() => {
  const NEXT_TEXT = '\\u4e0b\\u4e00\\u6b65';
  const visible = (el) => {
    const style = window.getComputedStyle(el);
    return style && style.visibility !== 'hidden' && style.display !== 'none' &&
      (el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  };
  const textOf = (el) => [
    (el.innerText || el.textContent || '').trim().replace(/\\s+/g, ''),
    el.getAttribute('aria-label') || '',
    el.getAttribute('data-tooltip') || '',
    el.id || ''
  ].join(' ').trim();
  const candidates = Array.from(document.querySelectorAll(
    '#identifierNext,#passwordNext,button,[role="button"],div[role="button"],input[type="submit"]'
  )).filter(visible).map((el) => {
    const text = textOf(el);
    const rect = el.getBoundingClientRect();
    const id = el.id || '';
    return {el, text, rect, id};
  }).filter((item) => {
    if (/back|cancel|取消|返回|创建|create/i.test(item.text)) return false;
    return item.id === 'identifierNext' || item.id === 'passwordNext' ||
      item.text.includes(NEXT_TEXT) || /next/i.test(item.text);
  });
  if (!candidates.length) {
    return {success: false, error: 'Gmail next button not found'};
  }
  candidates.sort((a, b) => {
    const score = (item) => {
      let value = item.rect.width * item.rect.height / 1000;
      if (item.id === 'identifierNext' || item.id === 'passwordNext') value -= 500;
      if (item.text.includes(NEXT_TEXT) || /next/i.test(item.text)) value -= 250;
      return value;
    };
    return score(a) - score(b);
  });
  const target = candidates[0].el.closest('button,[role="button"]') || candidates[0].el;
  if (target.disabled || target.getAttribute('aria-disabled') === 'true') {
    return {success: false, error: 'Gmail next button is disabled', text: candidates[0].text};
  }
  target.scrollIntoView({block: 'center', inline: 'center'});
  target.click();
  return {success: true, text: candidates[0].text, id: candidates[0].id || ''};
})()
""",
    )


def _press_enter(run_js_fn):
    return _run_js_dict(
        run_js_fn,
        """
(() => {
  const active = document.activeElement;
  if (!active) {
    return {success: false, error: 'No active element for Enter key'};
  }
  active.dispatchEvent(new KeyboardEvent('keydown', {bubbles: true, cancelable: true, key: 'Enter', code: 'Enter', keyCode: 13, which: 13}));
  active.dispatchEvent(new KeyboardEvent('keyup', {bubbles: true, cancelable: true, key: 'Enter', code: 'Enter', keyCode: 13, which: 13}));
  return {success: true};
})()
""",
    )


def _submit_next(run_js_fn):
    result = _click_next(run_js_fn)
    if result.get("success"):
        return result
    enter_result = _press_enter(run_js_fn)
    if enter_result.get("success"):
        enter_result["method"] = "enter_fallback"
        enter_result["previous_error"] = result.get("error", "")
        return enter_result
    return result


def _choose_first_signin_method(run_js_fn):
    return _run_js_dict(
        run_js_fn,
        """
(() => {
  const PROMPT_TEXT = '\\u9009\\u62e9\\u60a8\\u60f3\\u8981\\u4f7f\\u7528\\u7684\\u767b\\u5f55\\u65b9\\u5f0f\\uff1a';
  const visible = (el) => {
    const style = window.getComputedStyle(el);
    return style && style.visibility !== 'hidden' && style.display !== 'none' &&
      (el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  };
  const compactText = (el) => (el.innerText || el.textContent || '').trim().replace(/\\s+/g, '');
  const bodyText = compactText(document.body);
  if (!bodyText.includes(PROMPT_TEXT)) {
    return {success: true, skipped: true, reason: 'sign-in method prompt not present'};
  }
  const promptNodes = Array.from(document.querySelectorAll('h1,h2,div,span,p'))
    .filter(visible)
    .filter((el) => compactText(el).includes(PROMPT_TEXT));
  promptNodes.sort((a, b) => {
    const score = (el) => {
      const text = compactText(el);
      const rect = el.getBoundingClientRect();
      let value = text.length;
      if (text === PROMPT_TEXT) value -= 1000;
      value += rect.width * rect.height / 10000;
      return value;
    };
    return score(a) - score(b);
  });
  const promptNode = promptNodes[0] || null;
  const promptRect = promptNode ? promptNode.getBoundingClientRect() : {bottom: 0, top: 0};
  const candidates = Array.from(document.querySelectorAll(
    'div[role="link"],div[role="button"],li[role="link"],li[role="button"],button,[role="button"],[role="link"],a'
  )).filter(visible).map((el) => {
    const text = compactText(el);
    const rect = el.getBoundingClientRect();
    return {el, text, rect};
  }).filter((item) => {
    if (!item.text) return false;
    if (item.rect.top < promptRect.bottom - 8) return false;
    if (/帮助|了解详情|取消|返回|更多|Try another way|Learn more|Help|Cancel|Back/i.test(item.text)) return false;
    if (item.text.includes(PROMPT_TEXT)) return false;
    return item.rect.width >= 80 && item.rect.height >= 20;
  });
  if (!candidates.length) {
    return {success: false, error: 'Gmail sign-in method option not found'};
  }
  candidates.sort((a, b) => {
    const score = (item) => {
      let value = item.rect.top;
      value += Math.max(0, item.text.length - 80) * 3;
      if (item.el.getAttribute('role') === 'link' || item.el.getAttribute('role') === 'button') {
        value -= 100;
      }
      return value;
    };
    return score(a) - score(b);
  });
  const target = candidates[0].el.closest('[role="link"],[role="button"],button,a') || candidates[0].el;
  target.scrollIntoView({block: 'center', inline: 'center'});
  target.click();
  return {success: true, clicked: true, text: candidates[0].text};
})()
""",
    )


def _detect_gmail_loaded(run_js_fn):
    return _run_js_dict(
        run_js_fn,
        """
(() => {
  const visible = (el) => {
    const style = window.getComputedStyle(el);
    return style && style.visibility !== 'hidden' && style.display !== 'none' &&
      (el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  };
  const textOf = (el) => [
    (el.innerText || el.textContent || '').trim(),
    el.getAttribute('aria-label') || '',
    el.getAttribute('title') || '',
    el.getAttribute('alt') || ''
  ].join(' ');
  const compactText = (el) => (el.innerText || el.textContent || '').trim().replace(/\\s+/g, '');
  const loginInput = Array.from(document.querySelectorAll(
    'input[type="email"],input#identifierId,input[name="identifier"],' +
    'input[type="password"],input[name="Passwd"],input[autocomplete="one-time-code"],input[name="idvPin"]'
  )).some((el) => visible(el));
  const loginPrompt = Array.from(document.querySelectorAll('h1,h2,div,span,p'))
    .some((el) => {
      if (!visible(el)) return false;
      const text = compactText(el);
      return text.includes('\\u767b\\u5f55') ||
        text.includes('\\u4f7f\\u7528\\u60a8\\u7684Google\\u8d26\\u53f7') ||
        text.includes('\\u9009\\u62e9\\u60a8\\u60f3\\u8981\\u4f7f\\u7528\\u7684\\u767b\\u5f55\\u65b9\\u5f0f') ||
        text.includes('\\u9a8c\\u8bc1\\u60a8\\u7684\\u8eab\\u4efd') ||
        /Sign in|Use your Google Account|Choose how you want to sign in|Verify/i.test(text);
    });
  const nextButton = Array.from(document.querySelectorAll(
    '#identifierNext,#passwordNext,button,[role="button"],input[type="submit"]'
  )).some((el) => {
    if (!visible(el)) return false;
    const text = textOf(el).replace(/\\s+/g, '');
    return text.includes('\\u4e0b\\u4e00\\u6b65') || /next/i.test(text);
  });
  const logo = Array.from(document.querySelectorAll(
    'a[title="Gmail"],a[aria-label="Gmail"],img[alt="Gmail"],div[aria-label="Gmail"]'
  )).some((el) => {
    const rect = el.getBoundingClientRect();
    return visible(el) && rect.top < Math.max(180, window.innerHeight * 0.3) &&
      rect.left < Math.max(260, window.innerWidth * 0.35);
  });
  const leftGmailText = Array.from(document.querySelectorAll('a,div,span,img'))
    .some((el) => {
      const rect = el.getBoundingClientRect();
      return visible(el) && /Gmail/i.test(textOf(el)) &&
        rect.top < Math.max(180, window.innerHeight * 0.3) &&
        rect.left < Math.max(260, window.innerWidth * 0.35);
    });
  const compose = Array.from(document.querySelectorAll('div[role="button"],a,button'))
    .some((el) => visible(el) && /(写邮件|Compose)/i.test(textOf(el)));
  const loginPage = Boolean(loginInput || loginPrompt || nextButton);
  return {
    success: true,
    logged_in: !loginPage && Boolean(logo || leftGmailText || compose),
    gmail_logo: Boolean(logo || leftGmailText),
    compose: Boolean(compose),
    login_page: loginPage,
    login_input: Boolean(loginInput),
    login_prompt: Boolean(loginPrompt),
    next_button: Boolean(nextButton),
    url: location.href
  };
})()
""",
    )


def _wait_for_gmail_loaded(run_js_fn, wait_fn, steps, max_wait_seconds, interval_seconds):
    attempts = max(1, int(max_wait_seconds / interval_seconds) + 1)
    for attempt in range(1, attempts + 1):
        state = _detect_gmail_loaded(run_js_fn)
        steps.append({"step": f"wait_gmail_loaded_attempt_{attempt}", "result": state})
        if state.get("logged_in"):
            return {"success": True, "attempts": attempt, "state": state}
        if attempt < attempts:
            steps.append(
                {
                    "step": f"wait_before_gmail_loaded_attempt_{attempt + 1}",
                    "result": _safe_call(wait_fn, "", interval_seconds),
                }
            )
    return {
        "success": False,
        "error": "Timed out waiting for Gmail logo after login",
    }


def _retry(step_name, action_fn, steps, wait_fn, attempts, interval):
    result = {"success": False, "error": "step not attempted"}
    for attempt in range(1, attempts + 1):
        result = action_fn()
        suffix = "" if attempt == 1 else f"_attempt_{attempt}"
        steps.append({"step": f"{step_name}{suffix}", "result": result})
        if result.get("success"):
            return result
        if attempt < attempts:
            steps.append(
                {
                    "step": f"wait_before_{step_name}_attempt_{attempt + 1}",
                    "result": _safe_call(wait_fn, "", interval),
                }
            )
    return result


def run(
    email,
    password,
    login_url=DEFAULT_LOGIN_URL,
    *,
    code_wait_seconds=DEFAULT_CODE_WAIT_SECONDS,
    max_wait_seconds=120,
    goto_fn=None,
    run_js_fn=None,
    wait_fn=None,
    get_url_fn=None,
    get_text_fn=None,
    log_fn=None,
):
    """Log in to Gmail and verify the Gmail logo appears."""
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
        account = str(email).strip()
        secret = str(password)
        if not account or "@" not in account:
            raise ValueError("Gmail login requires a valid email account")
        if not secret:
            raise ValueError("Gmail login requires password")

        log_fn(f"Opening Gmail login page: {login_url}")
        steps.append({"step": "navigate_gmail", "result": goto_fn(login_url)})
        steps.append({"step": "wait_after_navigation", "result": _safe_call(wait_fn, "", 2)})

        initial_state = _detect_gmail_loaded(run_js_fn)
        steps.append({"step": "detect_initial_gmail_loaded", "result": initial_state})
        if initial_state.get("logged_in"):
            log_fn("Gmail already logged in")
            return {
                "success": True,
                "already_logged_in": True,
                "email": account,
                "url": _safe_call(get_url_fn, ""),
                "steps": steps,
            }

        email_result = _retry(
            "fill_email",
            lambda: _fill_email(run_js_fn, account),
            steps,
            wait_fn,
            attempts=8,
            interval=1,
        )
        if not email_result.get("success"):
            return {"success": False, "error": "Failed to fill Gmail email", "steps": steps}

        next_email_result = _submit_next(run_js_fn)
        steps.append({"step": "submit_email", "result": next_email_result})
        if not next_email_result.get("success"):
            return {"success": False, "error": "Failed to submit Gmail email", "steps": steps}
        steps.append({"step": "wait_after_email_submit", "result": _safe_call(wait_fn, "", 2)})

        password_result = _retry(
            "fill_password",
            lambda: _fill_password(run_js_fn, secret),
            steps,
            wait_fn,
            attempts=8,
            interval=1,
        )
        if not password_result.get("success"):
            return {
                "success": False,
                "error": "Failed to fill Gmail password",
                "steps": steps,
            }

        next_password_result = _submit_next(run_js_fn)
        steps.append({"step": "submit_password", "result": next_password_result})
        if not next_password_result.get("success"):
            return {
                "success": False,
                "error": "Failed to submit Gmail password",
                "steps": steps,
            }
        steps.append({"step": "wait_after_password_submit", "result": _safe_call(wait_fn, "", 2)})

        method_result = _choose_first_signin_method(run_js_fn)
        steps.append({"step": "choose_first_signin_method", "result": method_result})
        if not method_result.get("success"):
            return {
                "success": False,
                "error": "Failed to choose Gmail sign-in method",
                "steps": steps,
            }
        if method_result.get("clicked"):
            steps.append({"step": "wait_after_signin_method", "result": _safe_call(wait_fn, "", 2)})

        log_fn("Waiting for user to enter Gmail verification code.")
        steps.append(
            {
                "step": "wait_for_manual_verification_code",
                "result": _safe_call(wait_fn, "", code_wait_seconds),
            }
        )

        code_next_result = _submit_next(run_js_fn)
        steps.append({"step": "submit_verification_code", "result": code_next_result})
        if not code_next_result.get("success"):
            return {
                "success": False,
                "error": "Failed to submit Gmail verification code",
                "steps": steps,
            }
        steps.append({"step": "wait_after_code_submit", "result": _safe_call(wait_fn, "", 3)})

        loaded_result = _wait_for_gmail_loaded(
            run_js_fn,
            wait_fn,
            steps,
            max_wait_seconds=max_wait_seconds,
            interval_seconds=2,
        )
        steps.append({"step": "verify_gmail_loaded", "result": loaded_result})
        if not loaded_result.get("success"):
            return {
                "success": False,
                "error": "Failed to verify Gmail login",
                "steps": steps,
            }

        log_fn("Gmail login succeeded")
        return {
            "success": True,
            "email": account,
            "url": _safe_call(get_url_fn, ""),
            "steps": steps,
            "message": "Gmail login succeeded and Gmail logo was detected.",
        }

    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        log_fn(f"Gmail login failed: {error}")
        return {"success": False, "error": error, "steps": steps}

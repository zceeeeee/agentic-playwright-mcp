"""Bilibili SMS login preparation.

The skill opens Bilibili, switches to SMS login, fills a phone number,
and requests an SMS code. Human verification and final code entry remain
manual in the browser popup.
"""

try:
    from src.layer_2 import controls as _controls
except Exception:
    _controls = None


DEFAULT_LOGIN_URL = "https://www.bilibili.com"


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


def _normalize_phone_number(phone_number):
    digits = ""
    for char in str(phone_number):
        if "0" <= char <= "9":
            digits += char

    if len(digits) == 13 and digits[:2] == "86":
        digits = digits[2:]

    if len(digits) != 11 or digits[0] != "1" or digits[1] < "3" or digits[1] > "9":
        raise ValueError("Bilibili login requires a valid 11-digit phone number")

    return digits


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


def _detect_security_page(get_url_fn, get_text_fn):
    url = str(_safe_call(get_url_fn, "") or "")
    text = str(_safe_call(get_text_fn, "") or "")
    lower = f"{url}\n{text}".lower()

    if (
        "captcha" in lower
        or "geetest" in lower
        or "安全验证" in text
        or "真人认证" in text
    ):
        return {
            "success": False,
            "requires_manual_verification": True,
            "error": "Bilibili requires human verification before login can continue",
            "url": url,
        }

    return None


def _open_login_panel(run_js_fn):
    return _run_js_dict(
        run_js_fn,
        """
(async () => {
  const LOGIN_TEXT = '\\u767b\\u5f55';
  const SMS_LOGIN_TEXT = '\\u77ed\\u4fe1\\u767b\\u5f55';
  const PANEL_SELECTOR = [
    '.bili-mini-login',
    '.login-panel',
    '.login-panel-popover',
    '.login-container',
    '.bili-login',
    '.passport-login-container',
    '[class*="mini-login" i]',
    '[class*="login-panel" i]',
    '[class*="login"]'
  ].join(',');
  const visible = (el) => {
    const style = window.getComputedStyle(el);
    return style && style.visibility !== 'hidden' && style.display !== 'none' &&
      (el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  };
  const compactText = (el) => (el.innerText || el.textContent || '').trim().replace(/\\s+/g, '');
  const labelOf = (el) => [
    compactText(el),
    el.getAttribute('aria-label') || '',
    el.getAttribute('title') || ''
  ].join('').trim().replace(/\\s+/g, '');
  const hasSmsLogin = () => {
    return Array.from(
      document.querySelectorAll('body,' + PANEL_SELECTOR + ',button,[role="button"],a,div,span,p')
    ).some((el) => visible(el) && compactText(el).includes(SMS_LOGIN_TEXT));
  };
  const hasPhoneInput = () => {
    return Array.from(document.querySelectorAll('input')).some((el) => {
      const text = [
        el.placeholder || '',
        el.type || '',
        el.name || '',
        el.id || '',
        el.autocomplete || '',
        el.inputMode || '',
        el.getAttribute('aria-label') || ''
      ].join(' ').toLowerCase();
      return visible(el) && /(手机号|手机|phone|mobile|tel)/i.test(text);
    });
  };
  if (hasSmsLogin() || hasPhoneInput()) {
    return {
      success: true,
      already_open: true,
      marker_found: hasSmsLogin(),
      has_phone_input: hasPhoneInput()
    };
  }

  const clickElement = (el) => {
    const target = el.closest('button,[role="button"],a') || el;
    target.scrollIntoView({block: 'center', inline: 'center'});
    target.click();
    return target;
  };
  const isLoginEntry = (el) => {
    const label = labelOf(el);
    const rect = el.getBoundingClientRect();
    const className = String(el.className || '');
    const topRight = rect.top < Math.max(180, window.innerHeight * 0.3) &&
      rect.left > window.innerWidth * 0.45;
    const loginClass = /header-login-entry|login-entry|right-entry|login/i.test(className);
    const compactLoginText = label === LOGIN_TEXT || label.toLowerCase() === 'login';
    return compactLoginText && (loginClass || topRight) &&
      rect.width <= 160 && rect.height <= 160;
  };
  const score = (el) => {
    const rect = el.getBoundingClientRect();
    const className = String(el.className || '');
    let value = 0;
    if (/header-login-entry/i.test(className)) {
      value -= 3000;
    }
    if (/login-entry/i.test(className)) {
      value -= 1500;
    }
    if (rect.top < Math.max(180, window.innerHeight * 0.3) &&
        rect.left > window.innerWidth * 0.45) {
      value -= 900;
    }
    if (rect.width === rect.height || Math.abs(rect.width - rect.height) < 16) {
      value -= 150;
    }
    value += Math.max(0, rect.top);
    value -= Math.max(0, rect.left / 10);
    value += rect.width * rect.height / 2000;
    return value;
  };
  const findHeaderLoginButton = () => {
    const selector = [
      '.header-login-entry',
      '.right-entry__outside .header-login-entry',
      '.right-entry .header-login-entry',
      '.bili-header .header-login-entry',
      '.international-header .header-login-entry',
      '[class*="header-login-entry"]',
      '[class*="login-entry"]',
      'button',
      '[role="button"]',
      'a',
      'div',
      'span'
    ].join(',');
    const candidates = Array.from(document.querySelectorAll(selector))
      .filter(visible)
      .filter(isLoginEntry);
    candidates.sort((a, b) => score(a) - score(b));
    return candidates[0] || null;
  };

  const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  let lastText = '';
  let lastClass = '';
  for (let attempt = 1; attempt <= 6; attempt += 1) {
    const button = findHeaderLoginButton();
    if (!button) {
      return {
        success: false,
        error: 'Top-right Bilibili login icon not found',
        marker_found: false,
        attempts: attempt - 1
      };
    }
    const clicked = clickElement(button);
    lastText = compactText(clicked) || compactText(button);
    lastClass = String(button.className || '');
    await pause(700);
    if (hasSmsLogin()) {
      return {
        success: true,
        clicked: true,
        method: 'top_right_login_icon',
        text: lastText,
        class_name: lastClass,
        marker_found: true,
        attempts: attempt
      };
    }
  }

  return {
    success: false,
    error: 'Bilibili SMS login marker not found after clicking login icon',
    clicked: true,
    method: 'top_right_login_icon',
    text: lastText,
    class_name: lastClass,
    marker_found: false,
    attempts: 6
  };
})()
""",
    )


def _click_sms_login(run_js_fn):
    return _run_js_dict(
        run_js_fn,
        """
(async () => {
  const SMS_LOGIN_TEXT = '\\u77ed\\u4fe1\\u767b\\u5f55';
  const PANEL_SELECTOR = [
    '.bili-mini-login',
    '.login-panel',
    '.login-panel-popover',
    '.login-container',
    '.bili-login',
    '.passport-login-container',
    '[class*="mini-login" i]',
    '[class*="login-panel" i]',
    '[class*="login"]'
  ].join(',');
  const visible = (el) => {
    const style = window.getComputedStyle(el);
    return style && style.visibility !== 'hidden' && style.display !== 'none' &&
      (el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  };
  const compactText = (el) => (el.innerText || el.textContent || '').trim().replace(/\\s+/g, '');
  const hasPhoneInput = () => {
    return Array.from(document.querySelectorAll('input')).some((el) => {
      const text = [
        el.placeholder || '',
        el.type || '',
        el.name || '',
        el.id || '',
        el.autocomplete || '',
        el.inputMode || '',
        el.getAttribute('aria-label') || ''
      ].join(' ').toLowerCase();
      return visible(el) && /(手机号|手机|phone|mobile|tel)/i.test(text);
    });
  };
  if (hasPhoneInput()) {
    return {success: true, already_sms_mode: true};
  }

  const roots = Array.from(document.querySelectorAll(PANEL_SELECTOR)).filter(visible);
  if (!roots.length) {
    roots.push(document.body);
  }
  const nodes = [];
  for (const root of roots) {
    nodes.push(...Array.from(root.querySelectorAll('button,[role="button"],a,div,span,p,li')));
  }
  const candidates = nodes.filter(visible).map((el) => {
    const rect = el.getBoundingClientRect();
    const text = compactText(el);
    const clickable = Boolean(el.closest('button,[role="button"],a')) ||
      el.tagName === 'BUTTON' || el.getAttribute('role') === 'button';
    return {el, rect, text, clickable};
  }).filter((item) => {
    if (!item.text.includes(SMS_LOGIN_TEXT)) {
      return false;
    }
    if (item.el === document.body) {
      return false;
    }
    return item.text === SMS_LOGIN_TEXT || item.text.length <= 16 || item.clickable;
  });

  if (!candidates.length) {
    return {success: false, error: 'Bilibili SMS login switch not found'};
  }
  candidates.sort((a, b) => {
    const score = (item) => {
      let value = item.rect.width * item.rect.height;
      if (item.text === SMS_LOGIN_TEXT) {
        value -= 10000;
      }
      if (item.clickable) {
        value -= 5000;
      }
      if (/tab|sms|login/i.test(String(item.el.className || ''))) {
        value -= 1000;
      }
      return value;
    };
    return score(a) - score(b);
  });

  const target = candidates[0].el.closest('button,[role="button"],a') || candidates[0].el;
  target.scrollIntoView({block: 'center', inline: 'center'});
  target.click();
  await new Promise((resolve) => setTimeout(resolve, 400));
  return {
    success: true,
    clicked: true,
    method: 'sms_login_switch',
    text: candidates[0].text,
    has_phone_input_after: hasPhoneInput()
  };
})()
""",
    )


def _fill_phone(run_js_fn, phone_number):
    return _run_js_dict(
        run_js_fn,
        """
(async () => {
  const phone = PHONE_NUMBER;
  const PANEL_SELECTOR = [
    '.bili-mini-login',
    '.login-panel',
    '.login-panel-popover',
    '.login-container',
    '.bili-login',
    '.passport-login-container',
    '[class*="mini-login" i]',
    '[class*="login-panel" i]',
    '[class*="login"]'
  ].join(',');
  const visible = (el) => {
    const style = window.getComputedStyle(el);
    return style && style.visibility !== 'hidden' && style.display !== 'none' &&
      (el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  };
  const compactText = (el) => (el.innerText || el.textContent || '').trim().replace(/\\s+/g, '');
  const textOf = (el) => [
    el.placeholder || '',
    el.type || '',
    el.name || '',
    el.id || '',
    el.autocomplete || '',
    el.inputMode || '',
    el.getAttribute('aria-label') || ''
  ].join(' ').toLowerCase();
  const ancestorTextMatches = (el) => {
    let node = el.parentElement;
    for (let i = 0; i < 7 && node; i += 1) {
      const text = compactText(node);
      if (
        text.includes('\\u77ed\\u4fe1\\u767b\\u5f55') ||
        text.includes('\\u672a\\u6ce8\\u518c\\u8fc7\\u54d4\\u54e9\\u54d4\\u54e9') ||
        text.includes('\\u9a8c\\u8bc1\\u7801') ||
        text.includes('\\u767b\\u5f55\\u6216\\u5b8c\\u6210\\u6ce8\\u518c')
      ) {
        return true;
      }
      node = node.parentElement;
    }
    return false;
  };
  const inLoginPanel = (el) => Boolean(el.closest(PANEL_SELECTOR)) || ancestorTextMatches(el);
  const denied = (text) => {
    return /(验证码|code|密码|password|国家|地区|area|country|邮箱|email|搜索|search|keyword|账号|account)/i.test(text);
  };
  const phoneHint = (text) => /(手机号|手机|phone|mobile|tel)/i.test(text);
  const inputs = Array.from(document.querySelectorAll('input')).filter(visible);
  let target = inputs.find((el) => {
    const text = textOf(el);
    return inLoginPanel(el) && phoneHint(text) && !denied(text);
  });
  if (!target) {
    target = inputs.find((el) => {
      const text = textOf(el);
      const type = (el.type || '').toLowerCase();
      return inLoginPanel(el) && !denied(text) && type === 'tel';
    });
  }
  if (!target) {
    return {success: false, error: 'Phone input not found in Bilibili login panel'};
  }

  const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const descriptor = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value');
  const setValue = (value) => {
    if (descriptor && descriptor.set) {
      descriptor.set.call(target, value);
    } else {
      target.value = value;
    }
  };
  const emitInput = (inputType, data) => {
    try {
      target.dispatchEvent(new InputEvent('input', {
        bubbles: true,
        cancelable: true,
        inputType,
        data
      }));
    } catch (error) {
      target.dispatchEvent(new Event('input', {bubbles: true}));
    }
  };
  const emitKeyboard = (type, key) => {
    try {
      target.dispatchEvent(new KeyboardEvent(type, {
        bubbles: true,
        cancelable: true,
        key,
        code: /^\\d$/.test(key) ? `Digit${key}` : '',
        charCode: key.length === 1 ? key.charCodeAt(0) : 0,
        keyCode: key.length === 1 ? key.charCodeAt(0) : 0,
        which: key.length === 1 ? key.charCodeAt(0) : 0
      }));
    } catch (error) {}
  };

  target.scrollIntoView({block: 'center', inline: 'center'});
  target.focus();
  target.click();
  setValue('');
  emitInput('deleteContentBackward', null);
  await pause(30);

  for (const char of phone) {
    emitKeyboard('keydown', char);
    emitKeyboard('keypress', char);
    try {
      target.dispatchEvent(new InputEvent('beforeinput', {
        bubbles: true,
        cancelable: true,
        inputType: 'insertText',
        data: char
      }));
    } catch (error) {}
    setValue((target.value || '') + char);
    emitInput('insertText', char);
    emitKeyboard('keyup', char);
    await pause(25);
  }

  target.dispatchEvent(new Event('change', {bubbles: true}));
  await pause(120);
  const digits = (target.value || '').replace(/\\D/g, '');
  return {
    success: digits === phone,
    error: digits === phone ? '' : 'Phone input did not accept all digits',
    placeholder: target.placeholder || '',
    name: target.name || '',
    id: target.id || '',
    type: target.type || '',
    value: target.value || ''
  };
})()
""".replace("PHONE_NUMBER", _js_string(phone_number)),
    )


def _click_get_code(run_js_fn):
    return _run_js_dict(
        run_js_fn,
        """
(() => {
  const SEND_TEXT = '\\u53d1\\u9001\\u9a8c\\u8bc1\\u7801';
  const GET_TEXT = '\\u83b7\\u53d6\\u9a8c\\u8bc1\\u7801';
  const PANEL_SELECTOR = [
    '.bili-mini-login',
    '.login-panel',
    '.login-panel-popover',
    '.login-container',
    '.bili-login',
    '.passport-login-container',
    '[class*="mini-login" i]',
    '[class*="login-panel" i]',
    '[class*="login"]'
  ].join(',');
  const visible = (el) => {
    const style = window.getComputedStyle(el);
    return style && style.visibility !== 'hidden' && style.display !== 'none' &&
      (el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  };
  const compactText = (el) => (el.innerText || el.textContent || '').trim().replace(/\\s+/g, '');
  const textOf = (el) => [
    el.placeholder || '',
    el.type || '',
    el.name || '',
    el.id || '',
    el.autocomplete || '',
    el.inputMode || '',
    el.getAttribute('aria-label') || ''
  ].join(' ').toLowerCase();
  const ancestorTextMatches = (el) => {
    let node = el.parentElement;
    for (let i = 0; i < 7 && node; i += 1) {
      const text = compactText(node);
      if (
        text.includes('\\u77ed\\u4fe1\\u767b\\u5f55') ||
        text.includes('\\u672a\\u6ce8\\u518c\\u8fc7\\u54d4\\u54e9\\u54d4\\u54e9') ||
        text.includes('\\u9a8c\\u8bc1\\u7801') ||
        text.includes('\\u767b\\u5f55\\u6216\\u5b8c\\u6210\\u6ce8\\u518c')
      ) {
        return true;
      }
      node = node.parentElement;
    }
    return false;
  };
  const inLoginPanel = (el) => Boolean(el.closest(PANEL_SELECTOR)) || ancestorTextMatches(el);
  const phoneInput = Array.from(document.querySelectorAll('input')).find((el) => {
    return visible(el) && inLoginPanel(el) && /(手机号|手机|phone|mobile|tel)/i.test(textOf(el));
  });
  const codeInput = Array.from(document.querySelectorAll('input')).find((el) => {
    return visible(el) && inLoginPanel(el) && /(验证码|code)/i.test(textOf(el));
  });
  const clickLikeHuman = (el) => {
    const target = el.closest('button,[role="button"],a') || el;
    target.scrollIntoView({block: 'center', inline: 'center'});
    const rect = target.getBoundingClientRect();
    const clientX = rect.left + rect.width / 2;
    const clientY = rect.top + rect.height / 2;
    const eventInit = {
      bubbles: true,
      cancelable: true,
      view: window,
      clientX,
      clientY,
      button: 0,
      buttons: 1
    };
    try {
      target.dispatchEvent(new PointerEvent('pointerdown', eventInit));
      target.dispatchEvent(new PointerEvent('pointerup', {...eventInit, buttons: 0}));
    } catch (error) {}
    target.dispatchEvent(new MouseEvent('mousedown', eventInit));
    target.dispatchEvent(new MouseEvent('mouseup', {...eventInit, buttons: 0}));
    if (typeof target.click === 'function') {
      target.click();
    } else {
      target.dispatchEvent(new MouseEvent('click', {...eventInit, buttons: 0}));
    }
    return target;
  };
  const nodes = Array.from(
    document.querySelectorAll('button,[role="button"],a,div,span,p')
  ).filter(visible).map((el) => {
    const text = compactText(el);
    const rect = el.getBoundingClientRect();
    const style = window.getComputedStyle(el);
    const phoneRect = phoneInput ? phoneInput.getBoundingClientRect() : null;
    const belowPhone = phoneRect ? rect.top >= phoneRect.bottom - 16 : false;
    const samePhoneRow = phoneRect ? rect.bottom >= phoneRect.top - 8 && rect.top <= phoneRect.bottom + 8 : false;
    const rightOfPhone = phoneRect ? rect.left >= phoneRect.left + phoneRect.width * 0.5 : false;
    const blueOrPinkText = /rgb\\(\\s*(0|20|30|251)\\s*,\\s*(1[4-9][0-9]|2[0-5][0-9]|95)\\s*,\\s*(2[0-5][0-9]|135)\\s*\\)|#?00a1d6|#?fb7299/i.test(
      style.color || ''
    );
    return {el, text, rect, belowPhone, samePhoneRow, rightOfPhone, blueOrPinkText};
  }).filter((item) => {
    if (!inLoginPanel(item.el)) {
      return false;
    }
    if (/收不到|无法|语音|voice/i.test(item.text)) {
      return false;
    }
    if (item.text === SEND_TEXT || item.text === GET_TEXT) {
      return true;
    }
    if (item.text.includes(SEND_TEXT) && item.text.length <= 24) {
      return true;
    }
    if (item.text.includes(GET_TEXT) && item.text.length <= 24) {
      return true;
    }
    return false;
  });

  if (!nodes.length) {
    return {success: false, error: 'Bilibili get-code button not found'};
  }

  nodes.sort((a, b) => {
    const score = (item) => {
      let value = item.rect.width * item.rect.height / 1000;
      if (item.text === SEND_TEXT) {
        value -= 140;
      } else if (item.text.includes(SEND_TEXT)) {
        value -= 110;
      } else if (item.text === GET_TEXT) {
        value -= 80;
      }
      if (item.samePhoneRow && item.rightOfPhone) {
        value -= 120;
      } else if (item.rightOfPhone) {
        value -= 80;
      } else if (item.belowPhone) {
        value -= 40;
      }
      if (item.blueOrPinkText) {
        value -= 30;
      }
      if (codeInput) {
        const inputRect = codeInput.getBoundingClientRect();
        const inputCenterY = inputRect.top + inputRect.height / 2;
        const centerY = item.rect.top + item.rect.height / 2;
        const sameRow = item.rect.bottom >= inputRect.top - 8 && item.rect.top <= inputRect.bottom + 8;
        const rightOfCodeInput = item.rect.left >= inputRect.left + inputRect.width * 0.45;
        value += Math.abs(centerY - inputCenterY) / 10;
        if (sameRow) {
          value -= 50;
        }
        if (rightOfCodeInput) {
          value -= 40;
        }
      }
      value += Math.max(0, item.text.length - 5);
      return value;
    };
    return score(a) - score(b);
  });

  const target = nodes[0].el.closest('button,[role="button"],a') || nodes[0].el;
  if (target.disabled || target.getAttribute('aria-disabled') === 'true') {
    return {success: false, error: 'Bilibili get-code button is disabled', text: nodes[0].text};
  }

  const clicked = clickLikeHuman(nodes[0].el);
  return {
    success: true,
    text: nodes[0].text,
    id: clicked.id || '',
    method: codeInput ? 'code_input_right_button' : 'phone_input_right_button',
    near_code_input: Boolean(codeInput),
    right_of_phone_input: Boolean(nodes[0].rightOfPhone)
  };
})()
""",
    )


def _retry_browser_step(step_name, action_fn, steps, wait_fn, *, attempts, interval):
    result = {"success": False, "error": "step not attempted"}
    for attempt in range(1, attempts + 1):
        result = action_fn()
        suffix = "" if attempt == 1 else f"_attempt_{attempt}"
        steps.append({"step": f"{step_name}{suffix}", "result": result})
        if result.get("success"):
            return result
        if attempt < attempts and interval:
            steps.append(
                {
                    "step": f"wait_before_{step_name}_attempt_{attempt + 1}",
                    "result": wait_fn(interval),
                }
            )
    return result


def run(
    phone_number,
    login_url=DEFAULT_LOGIN_URL,
    wait_seconds=1,
    *,
    goto_fn=None,
    run_js_fn=None,
    wait_fn=None,
    get_url_fn=None,
    get_text_fn=None,
    log_fn=None,
):
    """Prepare Bilibili SMS login and stop at manual verification/code entry."""
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
        phone = _normalize_phone_number(phone_number)

        nav_result = goto_fn(login_url)
        steps.append({"step": "navigate", "result": nav_result})
        if wait_seconds:
            steps.append({"step": "wait_after_navigation", "result": wait_fn(wait_seconds)})

        security_page = _detect_security_page(get_url_fn, get_text_fn)
        if security_page:
            security_page["steps"] = steps
            log_fn("Bilibili requires human verification before login")
            return security_page

        open_result = _open_login_panel(run_js_fn)
        steps.append({"step": "open_login_panel", "result": open_result})
        if not open_result.get("success"):
            return {
                "success": False,
                "error": "Failed to open Bilibili login panel",
                "steps": steps,
            }
        if wait_seconds:
            steps.append({"step": "wait_after_open_login", "result": wait_fn(wait_seconds)})

        sms_result = _retry_browser_step(
            "click_sms_login",
            lambda: _click_sms_login(run_js_fn),
            steps,
            wait_fn,
            attempts=4,
            interval=0.5,
        )
        if not sms_result.get("success"):
            return {
                "success": False,
                "error": "Failed to switch Bilibili login panel to SMS login",
                "steps": steps,
            }
        if sms_result.get("clicked") and wait_seconds:
            steps.append({"step": "wait_after_sms_login", "result": wait_fn(wait_seconds)})

        fill_result = _retry_browser_step(
            "fill_phone",
            lambda: _fill_phone(run_js_fn, phone),
            steps,
            wait_fn,
            attempts=6,
            interval=0.5,
        )
        if not fill_result.get("success"):
            return {
                "success": False,
                "error": "Failed to fill Bilibili phone number",
                "steps": steps,
            }

        get_code_result = _retry_browser_step(
            "click_get_code",
            lambda: _click_get_code(run_js_fn),
            steps,
            wait_fn,
            attempts=6,
            interval=0.5,
        )
        if not get_code_result.get("success"):
            return {
                "success": False,
                "error": "Failed to request Bilibili verification code",
                "steps": steps,
            }

        if wait_seconds:
            steps.append({"step": "wait_after_get_code", "result": wait_fn(wait_seconds)})

        log_fn("Bilibili verification code requested; manual verification required")
        return {
            "success": True,
            "requires_manual_verification": True,
            "requires_manual_code": True,
            "phone_number": phone,
            "steps": steps,
            "message": (
                "Please complete Bilibili human verification in the popup, "
                "then enter the SMS verification code manually."
            ),
        }

    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        log_fn(f"Bilibili login preparation failed: {error}")
        return {"success": False, "error": error, "steps": steps}

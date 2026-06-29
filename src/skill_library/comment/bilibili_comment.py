"""Bilibili video comment publishing adapter."""

try:
    from src.layer_2 import controls as _controls
except Exception:
    _controls = None


DEFAULT_LOGIN_URL = "https://www.bilibili.com"
DEFAULT_VIDEO_URL = "https://www.bilibili.com/video/BV1oh7b6xE4R"
POST_LOGIN_WAIT_SECONDS = 20


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
        raise ValueError("Bilibili comment requires a valid 11-digit phone number")

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


def _detect_login_state(run_js_fn):
    return _run_js_dict(
        run_js_fn,
        """
(() => {
  const visible = (el) => {
    const style = window.getComputedStyle(el);
    return style && style.visibility !== 'hidden' && style.display !== 'none' &&
      (el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  };
  const compactText = (el) => (el.innerText || el.textContent || '').trim().replace(/\\s+/g, '');
  const loginPopup = Array.from(document.querySelectorAll(
    '.bili-mini-login,.login-panel,[class*="login-panel" i],[class*="mini-login" i],[class*="login"]'
  )).some((el) => visible(el) && (
    compactText(el).includes('\\u77ed\\u4fe1\\u767b\\u5f55') ||
    compactText(el).includes('\\u9a8c\\u8bc1\\u7801') ||
    compactText(el).includes('\\u767b\\u5f55\\u6216\\u5b8c\\u6210\\u6ce8\\u518c')
  ));
  const loginEntry = Array.from(document.querySelectorAll(
    '.header-login-entry,[class*="login-entry"],button,[role="button"],a,div,span'
  )).some((el) => {
    const rect = el.getBoundingClientRect();
    const topRight = rect.top < Math.max(180, window.innerHeight * 0.3) &&
      rect.left > window.innerWidth * 0.45;
    return visible(el) && topRight && compactText(el) === '\\u767b\\u5f55';
  });
  const headerAvatar = Array.from(document.querySelectorAll(
    '.right-entry__outside .header-avatar,.right-entry .header-avatar,' +
    '.right-entry__outside img,.right-entry img,' +
    '.bili-header [class*="avatar" i],.international-header [class*="avatar" i]'
  )).some((el) => {
    const rect = el.getBoundingClientRect();
    const topRight = rect.top < Math.max(180, window.innerHeight * 0.3) &&
      rect.left > window.innerWidth * 0.45;
    return visible(el) && topRight;
  });
  const loggedIn = headerAvatar && !loginPopup;
  return {
    success: true,
    logged_in: loggedIn,
    login_popup: loginPopup,
    login_entry: loginEntry,
    header_avatar: headerAvatar,
    url: location.href
  };
})()
""",
    )


def _open_login_panel(run_js_fn):
    return _run_js_dict(
        run_js_fn,
        """
(async () => {
  const LOGIN_TEXT = '\\u767b\\u5f55';
  const SMS_LOGIN_TEXT = '\\u77ed\\u4fe1\\u767b\\u5f55';
  try {
    window.scrollTo({top: 0, behavior: 'instant'});
  } catch (error) {
    window.scrollTo(0, 0);
  }
  const visible = (el) => {
    const style = window.getComputedStyle(el);
    return style && style.visibility !== 'hidden' && style.display !== 'none' &&
      (el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  };
  const compactText = (el) => (el.innerText || el.textContent || '').trim().replace(/\\s+/g, '');
  const hasSmsLogin = () => Array.from(document.querySelectorAll('body,button,[role="button"],a,div,span,p'))
    .some((el) => visible(el) && compactText(el).includes(SMS_LOGIN_TEXT));
  if (hasSmsLogin()) {
    return {success: true, already_open: true, marker_found: true};
  }
  const score = (el) => {
    const rect = el.getBoundingClientRect();
    const className = String(el.className || '');
    let value = 0;
    if (/header-login-entry/i.test(className)) value -= 3000;
    if (/login-entry/i.test(className)) value -= 1500;
    if (rect.top < Math.max(180, window.innerHeight * 0.3) &&
        rect.left > window.innerWidth * 0.45) value -= 900;
    const style = window.getComputedStyle(el);
    if (/rgb\\(\\s*(0|20|30)\\s*,\\s*(1[4-9][0-9]|2[0-5][0-9])\\s*,\\s*(2[0-5][0-9])\\s*\\)|#?00a1d6|#?00aeec/i.test(
      `${style.backgroundColor} ${style.color} ${style.borderColor}`
    )) {
      value -= 300;
    }
    if (Math.abs(rect.width - rect.height) <= 18 && rect.width <= 90 && rect.height <= 90) {
      value -= 180;
    }
    value += rect.top;
    value -= rect.left / 10;
    return value;
  };
  const findButton = () => {
    const nodes = Array.from(document.querySelectorAll(
      '.header-login-entry,.right-entry__outside .header-login-entry,[class*="login-entry"],button,[role="button"],a,div,span'
    )).filter(visible).filter((el) => {
      const label = [
        compactText(el),
        el.getAttribute('aria-label') || '',
        el.getAttribute('title') || ''
      ].join('').trim().replace(/\\s+/g, '');
      const rect = el.getBoundingClientRect();
      const topRight = rect.top < Math.max(180, window.innerHeight * 0.3) &&
        rect.left > window.innerWidth * 0.45;
      const className = String(el.className || '');
      const rightEntry = Boolean(el.closest('.right-entry,.right-entry__outside,.bili-header,.international-header'));
      const compactLoginText = label === LOGIN_TEXT || label.toLowerCase() === 'login';
      const loginEntryClass = /header-login-entry|login-entry/i.test(className);
      if (compactLoginText && (topRight || rightEntry || loginEntryClass)) {
        return true;
      }
      return loginEntryClass && (topRight || rightEntry) && rect.width <= 180 && rect.height <= 180;
    });
    nodes.sort((a, b) => score(a) - score(b));
    return nodes[0] || null;
  };
  const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  let lastText = '';
  let lastClass = '';
  for (let attempt = 1; attempt <= 10; attempt += 1) {
    if (hasSmsLogin()) {
      return {success: true, already_open: true, marker_found: true, attempts: attempt - 1};
    }
    const button = findButton();
    if (!button) {
      await pause(500);
      continue;
    }
    const target = button.closest('button,[role="button"],a') || button;
    target.scrollIntoView({block: 'center', inline: 'center'});
    lastText = compactText(target) || compactText(button);
    lastClass = String(button.className || '');
    target.click();
    await pause(900);
    if (hasSmsLogin()) {
      return {
        success: true,
        clicked: true,
        marker_found: true,
        attempts: attempt,
        text: lastText,
        class_name: lastClass,
        method: 'top_right_login_button_until_sms_marker'
      };
    }
  }
  return {
    success: false,
    error: 'Bilibili SMS login marker not found after clicking login button',
    attempts: 10,
    text: lastText,
    class_name: lastClass
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
  const visible = (el) => {
    const style = window.getComputedStyle(el);
    return style && style.visibility !== 'hidden' && style.display !== 'none' &&
      (el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  };
  const compactText = (el) => (el.innerText || el.textContent || '').trim().replace(/\\s+/g, '');
  const hasPhoneInput = () => Array.from(document.querySelectorAll('input')).some((el) => {
    const text = [el.placeholder || '', el.type || '', el.name || '', el.id || ''].join(' ').toLowerCase();
    return visible(el) && /(手机号|手机|phone|mobile|tel)/i.test(text);
  });
  if (hasPhoneInput()) {
    return {success: true, already_sms_mode: true};
  }
  const candidates = Array.from(document.querySelectorAll('button,[role="button"],a,div,span,p,li'))
    .filter(visible).map((el) => {
      const rect = el.getBoundingClientRect();
      const text = compactText(el);
      return {el, rect, text, clickable: Boolean(el.closest('button,[role="button"],a'))};
    }).filter((item) => item.text.includes(SMS_LOGIN_TEXT) &&
      (item.text === SMS_LOGIN_TEXT || item.text.length <= 16 || item.clickable));
  if (!candidates.length) {
    return {success: false, error: 'SMS login switch not found'};
  }
  candidates.sort((a, b) => (a.rect.width * a.rect.height) - (b.rect.width * b.rect.height));
  const target = candidates[0].el.closest('button,[role="button"],a') || candidates[0].el;
  target.scrollIntoView({block: 'center', inline: 'center'});
  target.click();
  await new Promise((resolve) => setTimeout(resolve, 400));
  return {success: true, clicked: true, has_phone_input_after: hasPhoneInput()};
})()
""",
    )


def _fill_login_phone(run_js_fn, phone_number):
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
  const inLoginArea = (el) => Boolean(el.closest(PANEL_SELECTOR)) || ancestorTextMatches(el);
  const denied = (text) => /(验证码|code|密码|password|国家|地区|area|country|邮箱|email|搜索|search|keyword|账号|account)/i.test(text);
  const phoneHint = (text) => /(手机号|手机|phone|mobile|tel)/i.test(text);
  const inputs = Array.from(document.querySelectorAll('input')).filter(visible);
  let target = inputs.find((el) => {
    const text = textOf(el);
    return inLoginArea(el) && phoneHint(text) && !denied(text);
  });
  if (!target) {
    target = inputs.find((el) => {
      const text = textOf(el);
      const type = (el.type || '').toLowerCase();
      return inLoginArea(el) && !denied(text) && type === 'tel';
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
  const visible = (el) => {
    const style = window.getComputedStyle(el);
    return style && style.visibility !== 'hidden' && style.display !== 'none' &&
      (el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  };
  const compactText = (el) => (el.innerText || el.textContent || '').trim().replace(/\\s+/g, '');
  const nodes = Array.from(document.querySelectorAll('button,[role="button"],a,div,span,p'))
    .filter(visible).map((el) => ({el, text: compactText(el), rect: el.getBoundingClientRect()}))
    .filter((item) => {
      if (/收不到|语音|无法/.test(item.text)) return false;
      return item.text === SEND_TEXT || item.text === GET_TEXT ||
        (item.text.includes(SEND_TEXT) && item.text.length <= 24) ||
        (item.text.includes(GET_TEXT) && item.text.length <= 24);
    });
  if (!nodes.length) {
    return {success: false, error: 'Get-code button not found'};
  }
  nodes.sort((a, b) => {
    const score = (item) => {
      let value = item.rect.width * item.rect.height / 1000;
      if (item.text === SEND_TEXT) value -= 140;
      if (item.text === GET_TEXT) value -= 80;
      return value;
    };
    return score(a) - score(b);
  });
  const target = nodes[0].el.closest('button,[role="button"],a') || nodes[0].el;
  if (target.disabled || target.getAttribute('aria-disabled') === 'true') {
    return {success: false, error: 'Get-code button is disabled', text: nodes[0].text};
  }
  target.scrollIntoView({block: 'center', inline: 'center'});
  target.click();
  return {success: true, text: nodes[0].text};
})()
""",
    )


def _reload_page(run_js_fn):
    """Reload the current page."""
    return _run_js_dict(
        run_js_fn,
        """
(() => {
  location.reload();
  return {success: true};
})()
""",
    )


def _prepare_sms_login_on_video(phone, run_js_fn, get_url_fn, get_text_fn, steps):
    """Prepare SMS login on the already-open video page."""
    state = _detect_login_state(run_js_fn)
    steps.append({"step": "detect_login_state", "result": state})
    if state.get("logged_in"):
        return {"success": True, "already_logged_in": True}

    open_result = _open_login_panel(run_js_fn)
    steps.append({"step": "open_login_panel", "result": open_result})
    if not open_result.get("success"):
        return {"success": False, "error": "Failed to open Bilibili login panel"}

    sms_result = _click_sms_login(run_js_fn)
    steps.append({"step": "click_sms_login", "result": sms_result})
    if not sms_result.get("success"):
        return {"success": False, "error": "Failed to switch to SMS login"}

    fill_result = _fill_login_phone(run_js_fn, phone)
    steps.append({"step": "fill_login_phone", "result": fill_result})
    if not fill_result.get("success"):
        return {"success": False, "error": "Failed to fill Bilibili login phone"}

    get_code_result = _click_get_code(run_js_fn)
    steps.append({"step": "click_get_code", "result": get_code_result})
    if not get_code_result.get("success"):
        return {"success": False, "error": "Failed to request Bilibili verification code"}

    return {
        "success": True,
        "requires_manual_verification": True,
        "requires_manual_code": True,
        "url": _safe_call(get_url_fn, ""),
        "text": _safe_call(get_text_fn, ""),
    }


def _wait_for_login_completion_on_video(run_js_fn, wait_fn, steps, max_wait_seconds, interval_seconds):
    """Wait for login to complete on video page, with extra wait for human verification."""
    attempts = max(1, int(max_wait_seconds / interval_seconds) + 1)
    for attempt in range(1, attempts + 1):
        state = _detect_login_state(run_js_fn)
        steps.append({"step": f"wait_login_completion_attempt_{attempt}", "result": state})
        if state.get("logged_in"):
            return {"success": True, "attempts": attempt, "state": state}
        if attempt < attempts:
            steps.append(
                {
                    "step": f"wait_before_login_completion_attempt_{attempt + 1}",
                    "result": _safe_call(wait_fn, "", interval_seconds),
                }
            )
    return {
        "success": False,
        "requires_manual_login": True,
        "error": "Timed out waiting for Bilibili manual verification/login completion",
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
  const labelOf = (el) => [
    el.placeholder || '',
    el.getAttribute('aria-label') || '',
    el.getAttribute('data-placeholder') || '',
    el.getAttribute('title') || '',
    el.name || '',
    el.id || '',
    String(el.className || '')
  ].join(' ').toLowerCase();
  const compactText = (el) => (el.innerText || el.textContent || '').trim().replace(/\\s+/g, '');

  const commentKeywords = [
    '\\u8bc4\\u8bba', '\\u8bc4\\u8bb0', '\\u53d1\\u8868\\u4f60\\u7684\\u770b\\u6cd5',
    '\\u5594\\u54e6\\u8bc4\\u8bb0\\u4e00\\u4e0b', '\\u6280\\u672f\\u8bc4\\u8bba',
    '\\u70b9\\u51fb\\u8bc4\\u8bba', 'comment', 'reply', '\\u56de\\u590d'
  ];

  const scrollForComments = () => {
    const anchors = Array.from(document.querySelectorAll('a,button,div,span'))
      .filter(visible)
      .filter((el) => /评论/.test(compactText(el)));
    if (anchors.length) {
      anchors[0].scrollIntoView({block: 'center', inline: 'center'});
    } else {
      window.scrollTo({top: Math.max(window.innerHeight * 0.8, 700), behavior: 'instant'});
    }
  };

  const inputCandidates = Array.from(document.querySelectorAll(
    '.reply-box-textarea,.comment-input,textarea,[contenteditable="true"],[role="textbox"],[data-placeholder],[class*="reply" i] textarea,[class*="comment" i] textarea,[class*="comment" i] [contenteditable="true"]'
  )).filter(visible).filter((el) => {
    const label = labelOf(el);
    const nearText = compactText(el.parentElement || el.parentElement?.parentElement || el);
    return commentKeywords.some((kw) => label.includes(kw) || nearText.includes(kw)) ||
      /textarea.*comment|comment.*textarea/i.test(String(el.className || el.id || ''));
  });

  if (inputCandidates.length) {
    return {success: true, found: true, selector: inputCandidates[0].className || inputCandidates[0].id || inputCandidates[0].tagName};
  }

  const textInputCandidates = Array.from(document.querySelectorAll('textarea,input')).filter(visible).filter((el) => {
    const label = labelOf(el);
    return /(评论|comment|回复|reply)/i.test(label) && el.tagName !== 'INPUT';
  });

  if (textInputCandidates.length) {
    return {success: true, found: true, selector: textInputCandidates[0].className || textInputCandidates[0].id || textInputCandidates[0].tagName};
  }

  const placeholderHints = ['说点什么', '评论', '留下你的精彩评论', '文明上网', '发表评论'];
  const fallbackCandidates = Array.from(document.querySelectorAll('textarea,[contenteditable="true"],[role="textbox"]'))
    .filter(visible).filter((el) => {
      const ph = el.placeholder || el.getAttribute('data-placeholder') || '';
      return placeholderHints.some((hint) => ph.includes(hint));
    });

  if (fallbackCandidates.length) {
    return {success: true, found: true, selector: 'fallback', method: 'placeholder_hint'};
  }

  scrollForComments();
  return {success: false, error: 'Bilibili comment input not found'};
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
  const labelOf = (el) => [
    el.placeholder || '',
    el.getAttribute('aria-label') || '',
    el.getAttribute('data-placeholder') || '',
    el.getAttribute('title') || '',
    el.name || '',
    el.id || '',
    String(el.className || '')
  ].join(' ').toLowerCase();
  const compactText = (el) => (el.innerText || el.textContent || '').trim().replace(/\\s+/g, '');

  const scrollForComments = () => {
    const anchors = Array.from(document.querySelectorAll('a,button,div,span'))
      .filter(visible)
      .filter((el) => /评论/.test(compactText(el)));
    if (anchors.length) {
      anchors[0].scrollIntoView({block: 'center', inline: 'center'});
    } else {
      window.scrollTo({top: Math.max(window.innerHeight * 0.8, 700), behavior: 'instant'});
    }
  };

  const commentKeywords = [
    '\\u8bc4\\u8bba', '\\u8bc4\\u8bb0', '\\u53d1\\u8868\\u4f60\\u7684\\u770b\\u6cd5',
    '\\u5594\\u54e6\\u8bc4\\u8bb0\\u4e00\\u4e0b', '\\u6280\\u672f\\u8bc4\\u8bba',
    '\\u70b9\\u51fb\\u8bc4\\u8bba', '\\u53d1\\u4e00\\u6761\\u53cb\\u5584\\u7684\\u8bc4\\u8bba',
    '\\u53cb\\u5584\\u7684\\u8bc4\\u8bba', 'comment', 'reply'
  ];

  let target = null;
  const allInputs = Array.from(document.querySelectorAll(
    '.reply-box-textarea,.comment-input,textarea,[contenteditable="true"],[role="textbox"],[data-placeholder],[class*="reply" i] textarea,[class*="comment" i] textarea,[class*="comment" i] [contenteditable="true"]'
  )).filter(visible);

  for (const el of allInputs) {
    const label = labelOf(el);
    const nearText = compactText(el.parentElement || el.parentElement?.parentElement || el);
    if (commentKeywords.some((kw) => label.includes(kw) || nearText.includes(kw))) {
      target = el;
      break;
    }
  }

  if (!target) {
    scrollForComments();
    const placeholderHints = ['说点什么', '评论', '留下你的精彩评论', '文明上网', '发表评论', '发一条友善的评论', '友善的评论'];
    for (const el of allInputs) {
      const ph = el.placeholder || el.getAttribute('data-placeholder') || '';
      if (placeholderHints.some((hint) => ph.includes(hint))) {
        target = el;
        break;
      }
    }
  }

  if (!target) {
    const textInputs = Array.from(document.querySelectorAll('textarea')).filter(visible);
    for (const el of textInputs) {
      const label = labelOf(el);
      if (/(评论|comment|回复|reply)/i.test(label)) {
        target = el;
        break;
      }
    }
  }

  if (!target) {
    return {success: false, error: 'Comment input not found'};
  }

  target.scrollIntoView({block: 'center', inline: 'center'});
  target.focus();

  if (target.tagName === 'TEXTAREA' || target.tagName === 'INPUT') {
    const descriptor = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value') ||
                       Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value');
    if (descriptor && descriptor.set) {
      descriptor.set.call(target, comment);
    } else {
      target.value = comment;
    }
    target.dispatchEvent(new Event('input', {bubbles: true}));
    target.dispatchEvent(new Event('change', {bubbles: true}));
  } else {
    target.innerHTML = '';
    target.dispatchEvent(new Event('focus', {bubbles: true}));
    try {
      target.dispatchEvent(new InputEvent('beforeinput', {bubbles: true, cancelable: true, inputType: 'insertText', data: comment}));
    } catch (e) {}
    target.innerText = comment;
    try {
      target.dispatchEvent(new InputEvent('input', {bubbles: true}));
    } catch (e) {
      target.dispatchEvent(new Event('input', {bubbles: true}));
    }
  }

  target.dispatchEvent(new Event('blur', {bubbles: true}));
  const value = target.value || target.innerText || target.textContent || '';
  return {success: value.includes(comment.split('\\n')[0]), value: value.substring(0, 100)};
})()
""".replace("COMMENT_TEXT", _js_string(comment_text)),
    )


def _click_send_comment(run_js_fn):
    return _run_js_dict(
        run_js_fn,
        """
(() => {
  const SEND_TEXT = '\\u53d1\\u5e03';
  const visible = (el) => {
    const style = window.getComputedStyle(el);
    return style && style.visibility !== 'hidden' && style.display !== 'none' &&
      (el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  };
  const compactText = (el) => (el.innerText || el.textContent || '').trim().replace(/\\s+/g, '');
  const labelOf = (el) => [
    el.placeholder || '',
    el.getAttribute('aria-label') || '',
    el.getAttribute('title') || '',
    el.name || '',
    el.id || '',
    String(el.className || '')
  ].join(' ').toLowerCase();

  const sendKeywords = [
    '\\u53d1\\u5e03', '\\u53d1\\u9001', '\\u63d0\\u4ea4', '\\u63d0\\u4ea4\\u8bc4\\u8bba',
    '\\u8bc4\\u8bba', '\\u56de\\u590d', 'submit', 'send', 'post'
  ];
  const editorSelectors = [
    '.reply-box-textarea',
    '.comment-input',
    'textarea',
    '[contenteditable="true"]',
    '[role="textbox"]',
    '[data-placeholder]'
  ].join(',');
  const editors = Array.from(document.querySelectorAll(editorSelectors))
    .filter(visible)
    .map((el) => {
      const value = el.value || el.innerText || el.textContent || '';
      const label = labelOf(el);
      const rect = el.getBoundingClientRect();
      const commentLike = /(评论|comment|回复|reply|友善)/i.test(label);
      return {el, value, label, rect, commentLike};
    })
    .filter((item) => item.value.trim() || item.commentLike);
  editors.sort((a, b) => {
    const score = (item) => {
      let value = 0;
      if (item.value.trim()) value -= 800;
      if (item.commentLike) value -= 300;
      value += item.rect.top;
      return value;
    };
    return score(a) - score(b);
  });
  const editor = editors[0] ? editors[0].el : null;
  const editorRect = editor ? editor.getBoundingClientRect() : null;
  let editorRoot = null;
  if (editor) {
    editorRoot = editor.closest(
      '.reply-box,.comment-box,.comment-send,.comment-container,.bili-comment,.reply-box-wrap,[class*="reply" i],[class*="comment" i]'
    );
    if (!editorRoot || editorRoot === editor) {
      editorRoot = editor.parentElement;
    }
  }
  const nearEditor = (rect) => {
    if (!editorRect) return false;
    const horizontallyNear = rect.left >= editorRect.left + editorRect.width * 0.35 ||
      rect.right >= editorRect.right - 40;
    const belowOrSame = rect.top >= editorRect.top - 24 &&
      rect.top <= editorRect.bottom + 180;
    return horizontallyNear && belowOrSame;
  };
  const blueButton = (el) => {
    const style = window.getComputedStyle(el);
    return /rgb\\(\\s*(0|20|30|64)\\s*,\\s*(1[4-9][0-9]|2[0-5][0-9])\\s*,\\s*(2[0-5][0-9])\\s*\\)|#?00a1d6|#?00aeec|#?1890ff/i.test(
      `${style.backgroundColor} ${style.color} ${style.borderColor}`
    );
  };

  let candidates = Array.from(document.querySelectorAll(
    'button,[role="button"],a,div,span'
  )).filter(visible).map((el) => {
    const rect = el.getBoundingClientRect();
    const text = compactText(el);
    const label = labelOf(el);
    const target = el.closest('button,[role="button"],a') || el;
    const inEditorRoot = editorRoot ? editorRoot.contains(el) : false;
    return {
      el,
      target,
      text,
      label,
      rect,
      clickable: Boolean(el.closest('button,[role="button"],a')) || el.tagName === 'BUTTON',
      near_editor: nearEditor(rect),
      in_editor_root: inEditorRoot,
      blue: blueButton(target) || blueButton(el)
    };
  }).filter((item) => {
    if (!item.text) return false;
    if (/取消|关闭|删除|编辑/.test(item.text)) return false;
    if (!sendKeywords.some((kw) => item.text.includes(kw) || item.label.includes(kw))) return false;
    return item.near_editor || item.in_editor_root || item.blue;
  });

  if (candidates.length) {
    candidates.sort((a, b) => {
      const score = (item) => {
        let value = 0;
        if (item.text === SEND_TEXT) value -= 500;
        if (item.clickable) value -= 100;
        if (item.in_editor_root) value -= 400;
        if (item.near_editor) value -= 300;
        if (item.blue) value -= 250;
        if (item.text.includes(SEND_TEXT)) value -= 200;
        value += item.rect.width * item.rect.height / 1000;
        return value;
      };
      return score(a) - score(b);
    });
    const target = candidates[0].target;
    if (target.disabled || target.getAttribute('aria-disabled') === 'true') {
      return {success: false, error: 'Send button is disabled', text: candidates[0].text};
    }
    target.scrollIntoView({block: 'center', inline: 'center'});
    target.click();
    return {
      success: true,
      text: candidates[0].text,
      method: candidates[0].near_editor ? 'comment_box_bottom_right_publish_button' : 'keyword_match',
      blue: Boolean(candidates[0].blue),
      near_editor: Boolean(candidates[0].near_editor)
    };
  }

  const bottomRightButtons = Array.from(document.querySelectorAll('button,[role="button"]'))
    .filter(visible).filter((el) => {
      const rect = el.getBoundingClientRect();
      const inBottomArea = rect.top > window.innerHeight * 0.5;
      const inRightArea = rect.left > window.innerWidth * 0.4;
      return inBottomArea || inRightArea;
    }).map((el) => {
      const rect = el.getBoundingClientRect();
      const text = compactText(el);
      return {el, text, rect};
    }).filter((item) => item.text && item.text.length <= 10);

  if (bottomRightButtons.length) {
    bottomRightButtons.sort((a, b) => (b.rect.width * b.rect.height) - (a.rect.width * a.rect.height));
    const target = bottomRightButtons[0].el;
    target.scrollIntoView({block: 'center', inline: 'center'});
    target.click();
    return {success: true, text: bottomRightButtons[0].text, method: 'bottom_right_fallback'};
  }

  return {success: false, error: 'Bilibili send comment button not found'};
})()
""",
    )


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
    phone_number,
    comment_text,
    video_url=None,
    *,
    max_wait_seconds=300,
    post_login_wait_seconds=POST_LOGIN_WAIT_SECONDS,
    goto_fn=None,
    run_js_fn=None,
    wait_fn=None,
    get_url_fn=None,
    get_text_fn=None,
    log_fn=None,
):
    """Log in to Bilibili on video page, then scroll to comments and post.

    Flow:
    1. Open video page
    2. Click login button (top right)
    3. Switch to SMS login
    4. Fill phone and send code
    5. Wait for manual verification/login completion
    6. Wait 20 seconds after login completion
    7. Scroll down, find comment input, fill it, and click its blue publish button
    """
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
        video = str(video_url).strip() if video_url else DEFAULT_VIDEO_URL
        comment = str(comment_text).strip()
        if not comment:
            raise ValueError("Bilibili comment requires comment text")

        # Step 1: Open video page
        log_fn(f"Opening video page: {video}")
        steps.append({"step": "navigate_video", "result": goto_fn(video)})
        steps.append({"step": "wait_after_video_navigation", "result": _safe_call(wait_fn, "", 2)})

        # Step 2-5: Login on video page
        login_result = _prepare_sms_login_on_video(
            phone,
            run_js_fn,
            get_url_fn,
            get_text_fn,
            steps,
        )
        steps.append({"step": "prepare_sms_login", "result": login_result})
        if not login_result.get("success"):
            return {
                "success": False,
                "error": login_result.get("error", "Failed to prepare Bilibili SMS login"),
                "steps": steps,
            }

        if not login_result.get("already_logged_in"):
            log_fn("Please complete Bilibili human verification and SMS login.")
            wait_result = _wait_for_login_completion_on_video(
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
                    "error": "Please complete Bilibili human verification/login before commenting",
                    "steps": steps,
                }

        log_fn("Login completed. Waiting 20 seconds before locating comments.")
        steps.append(
            {
                "step": "wait_after_login_completion_before_comment",
                "result": _safe_call(wait_fn, "", post_login_wait_seconds),
            }
        )

        # Find comment input
        input_result = _retry(
            "find_comment_input",
            lambda: _find_comment_input(run_js_fn),
            steps,
            wait_fn,
            attempts=5,
            interval=1,
        )
        if not input_result.get("success"):
            return {
                "success": False,
                "error": "Failed to find Bilibili comment input",
                "steps": steps,
            }

        # Fill comment
        fill_result = _retry(
            "fill_comment",
            lambda: _fill_comment(run_js_fn, comment),
            steps,
            wait_fn,
            attempts=5,
            interval=1,
        )
        if not fill_result.get("success"):
            return {
                "success": False,
                "error": "Failed to fill Bilibili comment",
                "steps": steps,
            }

        # Click send
        send_result = _retry(
            "click_send_comment",
            lambda: _click_send_comment(run_js_fn),
            steps,
            wait_fn,
            attempts=5,
            interval=1,
        )
        if not send_result.get("success"):
            return {
                "success": False,
                "error": "Failed to click Bilibili send comment button",
                "steps": steps,
            }

        log_fn("Bilibili comment published successfully")
        return {
            "success": True,
            "comment": comment,
            "video_url": video,
            "url": _safe_call(get_url_fn, ""),
            "steps": steps,
            "message": "Bilibili comment filled and send button clicked.",
        }

    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        log_fn(f"Bilibili comment failed: {error}")
        return {"success": False, "error": error, "steps": steps}

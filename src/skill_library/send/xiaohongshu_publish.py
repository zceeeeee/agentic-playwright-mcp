"""Xiaohongshu image-text publishing adapter.

The flow checks the login page first. If the phone-login UI is visible, it
fills the phone number, accepts the agreement, requests an SMS code, and waits
until the page shows "About us" in the lower-left area before publishing.
"""

try:
    from src.layer_2 import controls as _controls
except Exception:
    _controls = None


DEFAULT_LOGIN_URL = "https://www.xiaohongshu.com/login"
DEFAULT_PUBLISH_URL = (
    "https://creator.xiaohongshu.com/publish/publish"
    "?source=official&from=tab_switch&target=image"
)


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
        raise ValueError("Xiaohongshu publish requires a valid 11-digit phone number")

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


def _detect_blocked(get_url_fn, get_text_fn):
    url = str(_safe_call(get_url_fn, "") or "")
    text = str(_safe_call(get_text_fn, "") or "")

    if (
        "website-login/error" in url
        or "\u5b89\u5168\u9650\u5236" in text
        or "IP\u5b58\u5728\u98ce\u9669" in text
        or "\u5b58\u5728\u98ce\u9669" in text
    ):
        return {
            "success": False,
            "requires_network_change": True,
            "error": "Xiaohongshu returned a security restriction page",
            "url": url,
        }

    return None


def _detect_login_state(run_js_fn):
    return _run_js_dict(
        run_js_fn,
        """
(() => {
  const PHONE_LOGIN_TEXT = '\\u624b\\u673a\\u53f7\\u767b\\u5f55';
  const visible = (el) => {
    const style = window.getComputedStyle(el);
    return style && style.visibility !== 'hidden' && style.display !== 'none' &&
      (el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  };
  const compactText = (el) => (el.innerText || el.textContent || '').trim().replace(/\\s+/g, '');
  const labelOf = (el) => [
    el.placeholder || '',
    el.type || '',
    el.name || '',
    el.id || '',
    el.autocomplete || '',
    el.inputMode || '',
    el.getAttribute('aria-label') || '',
    el.getAttribute('title') || ''
  ].join(' ').toLowerCase();
  const denied = (text) => /(\\u9a8c\\u8bc1\\u7801|code|\\u5bc6\\u7801|password|\\u641c\\u7d22|search)/i.test(text);
  const hasPhoneLoginText = Array.from(document.querySelectorAll('body,button,[role="button"],a,div,span,p'))
    .some((el) => visible(el) && compactText(el).includes(PHONE_LOGIN_TEXT));
  const hasPhoneInput = Array.from(document.querySelectorAll('input')).some((el) => {
    const text = labelOf(el);
    return visible(el) && /(\\u624b\\u673a|\\u624b\\u673a\\u53f7|phone|mobile|tel)/i.test(text) &&
      !denied(text);
  });
  const phoneLogin = hasPhoneLoginText || hasPhoneInput;
  return {
    success: true,
    logged_in: !phoneLogin,
    phone_login: phoneLogin,
    has_phone_login_text: hasPhoneLoginText,
    has_phone_input: hasPhoneInput,
    url: location.href
  };
})()
""",
    )


def _fill_phone(run_js_fn, phone_number):
    return _run_js_dict(
        run_js_fn,
        """
(() => {
  const phone = PHONE_NUMBER;
  const visible = (el) => {
    const style = window.getComputedStyle(el);
    return style && style.visibility !== 'hidden' && style.display !== 'none' &&
      (el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  };
  const labelOf = (el) => [
    el.placeholder || '',
    el.type || '',
    el.name || '',
    el.id || '',
    el.autocomplete || '',
    el.inputMode || '',
    el.getAttribute('aria-label') || '',
    el.getAttribute('title') || ''
  ].join(' ').toLowerCase();
  const denied = (text) => /(\\u9a8c\\u8bc1\\u7801|code|\\u5bc6\\u7801|password|\\u90ae\\u7bb1|email|\\u641c\\u7d22|search)/i.test(text);
  const inputs = Array.from(document.querySelectorAll('input')).filter(visible);
  let target = inputs.find((el) => {
    const text = labelOf(el);
    return /(\\u624b\\u673a|\\u624b\\u673a\\u53f7|phone|mobile|tel)/i.test(text) &&
      !denied(text);
  });
  if (!target) {
    target = inputs.find((el) => {
      const text = labelOf(el);
      const type = (el.type || '').toLowerCase();
      return !denied(text) && (!type || type === 'text' || type === 'tel' || type === 'number');
    });
  }
  if (!target) {
    return {success: false, error: 'Phone input not found'};
  }

  target.scrollIntoView({block: 'center', inline: 'center'});
  target.focus();
  const descriptor = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value');
  if (descriptor && descriptor.set) {
    descriptor.set.call(target, phone);
  } else {
    target.value = phone;
  }
  target.dispatchEvent(new Event('input', {bubbles: true}));
  target.dispatchEvent(new Event('change', {bubbles: true}));
  return {
    success: (target.value || '').replace(/\\D/g, '') === phone,
    value: target.value || '',
    selector: target.placeholder || target.name || target.id || target.type || target.tagName
  };
})()
""".replace("PHONE_NUMBER", _js_string(phone_number)),
    )


def _accept_agreement(run_js_fn):
    return _run_js_dict(
        run_js_fn,
        """
(() => {
  const visible = (el) => {
    const style = window.getComputedStyle(el);
    return style && style.visibility !== 'hidden' && style.display !== 'none' &&
      (el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  };
  const normalize = (text) => (text || '').trim().replace(/\\s+/g, '');
  const agreementText = (text) => {
    const normalized = normalize(text);
    return normalized.includes('\\u7528\\u6237\\u534f\\u8bae') &&
      normalized.includes('\\u9690\\u79c1\\u653f\\u7b56') &&
      (
        normalized.includes('\\u6211\\u5df2\\u9605\\u8bfb') ||
        normalized.includes('\\u540c\\u610f') ||
        normalized.includes('\\u513f\\u7ae5') ||
        normalized.includes('\\u9752\\u5c11\\u5e74')
      );
  };
  const nearAgreement = (el) => {
    let node = el;
    for (let i = 0; i < 7 && node; i += 1) {
      if (agreementText(node.innerText || node.textContent || '')) {
        return true;
      }
      node = node.parentElement;
    }
    return false;
  };
  const dispatchCheckboxEvents = (el) => {
    el.dispatchEvent(new Event('input', {bubbles: true}));
    el.dispatchEvent(new Event('change', {bubbles: true}));
  };
  const clickCheckbox = (el) => {
    if (!el) return false;
    try {
      el.scrollIntoView({block: 'center', inline: 'center'});
    } catch (error) {}
    if (el.type === 'checkbox') {
      if (!el.checked) {
        el.click();
      }
      if (!el.checked) {
        const descriptor = Object.getOwnPropertyDescriptor(
          window.HTMLInputElement.prototype,
          'checked'
        );
        if (descriptor && descriptor.set) {
          descriptor.set.call(el, true);
        } else {
          el.checked = true;
        }
        dispatchCheckboxEvents(el);
      }
      return !!el.checked;
    }
    el.click();
    return true;
  };

  const checkboxes = Array.from(document.querySelectorAll('input[type="checkbox"]'));
  let target = checkboxes.find((el) => !el.checked && nearAgreement(el));
  if (!target) {
    target = checkboxes.find((el) => !el.checked && visible(el));
  }
  if (target) {
    const checked = clickCheckbox(target);
    return {success: true, checked, method: 'checkbox'};
  }

  const roleCheckboxes = Array.from(
    document.querySelectorAll('[role="checkbox"],[aria-checked]')
  ).filter((el) => visible(el) && el.getAttribute('aria-checked') !== 'true');
  target = roleCheckboxes.find(nearAgreement) || roleCheckboxes[0];
  if (target) {
    clickCheckbox(target);
    return {success: true, method: 'role_checkbox'};
  }

  const textTargets = [];
  for (const el of Array.from(document.querySelectorAll('label,div,span,p'))) {
    if (!visible(el) || !agreementText(el.innerText || el.textContent || '')) {
      continue;
    }
    let node = el;
    for (let depth = 0; depth < 5 && node; depth += 1) {
      if (visible(node) && agreementText(node.innerText || node.textContent || '')) {
        const rect = node.getBoundingClientRect();
        const area = rect.width * rect.height;
        const hasAgreementChildren = node.children.length > 0 ||
          Boolean(node.querySelector('a,input,[role="checkbox"],[aria-checked]'));
        if (
          hasAgreementChildren &&
          area > 0 &&
          area < window.innerWidth * window.innerHeight * 0.6
        ) {
          textTargets.push({el: node, rect, area});
        }
      }
      node = node.parentElement;
    }
  }

  textTargets.sort((a, b) => a.area - b.area);
  for (const item of textTargets) {
    const checkbox = Array.from(
      item.el.querySelectorAll('input[type="checkbox"],[role="checkbox"],[aria-checked]')
    ).find((el) => visible(el) || el.type === 'checkbox');
    if (checkbox) {
      clickCheckbox(checkbox);
      return {success: true, method: 'agreement_container_checkbox'};
    }

    const y = Math.min(Math.max(item.rect.top + item.rect.height / 2, 0), window.innerHeight - 1);
    const xCandidates = [
      item.rect.left + 8,
      item.rect.left - 8,
      item.rect.left + 18,
    ].filter((x) => x >= 0 && x < window.innerWidth);
    for (const x of xCandidates) {
      const pointTarget = document.elementFromPoint(x, y);
      if (pointTarget && !pointTarget.closest('a')) {
        pointTarget.click();
        return {success: true, method: 'agreement_left_point'};
      }
    }

    item.el.click();
    return {success: true, method: 'agreement_container'};
  }

  const bodyText = document.body ? (document.body.innerText || '') : '';
  if (
    bodyText.includes('\\u767b\\u5f55\\u5373\\u540c\\u610f') &&
    bodyText.includes('\\u7528\\u6237\\u534f\\u8bae') &&
    bodyText.includes('\\u9690\\u79c1\\u653f\\u7b56')
  ) {
    return {success: true, method: 'implicit_agreement'};
  }

  return {success: false, error: 'Agreement checkbox not found'};
})()
""",
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
  const labelOf = (el) => [
    el.placeholder || '',
    el.type || '',
    el.name || '',
    el.id || '',
    el.autocomplete || '',
    el.inputMode || '',
    el.getAttribute('aria-label') || '',
    el.getAttribute('title') || ''
  ].join(' ').toLowerCase();
  const codeInput = Array.from(document.querySelectorAll('input')).find((el) => {
    return visible(el) && /(\\u9a8c\\u8bc1\\u7801|code)/i.test(labelOf(el));
  });
  const nodes = Array.from(
    document.querySelectorAll('button,[role="button"],a,div,span,p')
  ).filter(visible).map((el) => {
    const text = compactText(el);
    return {el, text, rect: el.getBoundingClientRect()};
  }).filter((item) => {
    if (/(\\u6536\\u4e0d\\u5230|\\u8bed\\u97f3|\\u65e0\\u6cd5)/.test(item.text)) return false;
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
      if (item.text === GET_TEXT) value -= 100;
      if (codeInput) {
        const inputRect = codeInput.getBoundingClientRect();
        const centerY = item.rect.top + item.rect.height / 2;
        const inputCenterY = inputRect.top + inputRect.height / 2;
        const sameRow = item.rect.bottom >= inputRect.top - 10 &&
          item.rect.top <= inputRect.bottom + 10;
        const rightOfInput = item.rect.left >= inputRect.left + inputRect.width * 0.35;
        if (sameRow) value -= 60;
        if (rightOfInput) value -= 40;
        value += Math.abs(centerY - inputCenterY) / 5;
      }
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


def _detect_about_us(run_js_fn):
    return _run_js_dict(
        run_js_fn,
        """
(() => {
  const ABOUT_US_TEXT = '\\u5173\\u4e8e\\u6211\\u4eec';
  const visible = (el) => {
    const style = window.getComputedStyle(el);
    return style && style.visibility !== 'hidden' && style.display !== 'none' &&
      (el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  };
  const compactText = (el) => (el.innerText || el.textContent || '').trim().replace(/\\s+/g, '');
  const matches = Array.from(document.querySelectorAll('a,button,[role="button"],div,span,p,li'))
    .filter(visible).map((el) => ({el, text: compactText(el), rect: el.getBoundingClientRect()}))
    .filter((item) => item.text.includes(ABOUT_US_TEXT));
  const lowerLeft = matches.find((item) => (
    item.rect.left < Math.max(360, window.innerWidth * 0.35) &&
    item.rect.top > window.innerHeight * 0.45
  ));
  const best = lowerLeft || matches[0] || null;
  return {
    success: true,
    about_us: Boolean(best),
    lower_left: Boolean(lowerLeft),
    count: matches.length,
    text: best ? best.text : '',
    url: location.href
  };
})()
""",
    )


def _wait_for_about_us(run_js_fn, wait_fn, steps, max_wait_seconds, interval_seconds):
    attempts = max(1, int(max_wait_seconds / interval_seconds) + 1)
    for attempt in range(1, attempts + 1):
        state = _detect_about_us(run_js_fn)
        steps.append({"step": f"wait_about_us_attempt_{attempt}", "result": state})
        if state.get("about_us"):
            return {"success": True, "attempts": attempt, "state": state}
        if attempt < attempts:
            steps.append(
                {
                    "step": f"wait_before_about_us_attempt_{attempt + 1}",
                    "result": _safe_call(wait_fn, "", interval_seconds),
                }
            )
    return {
        "success": False,
        "requires_manual_login": True,
        "error": "Timed out waiting for Xiaohongshu login completion",
    }


def _detect_me_button(run_js_fn):
    return _run_js_dict(
        run_js_fn,
        """
(() => {
  const ME_BUTTON_TEXT = '\\u6211';
  const visible = (el) => {
    const style = window.getComputedStyle(el);
    return style && style.visibility !== 'hidden' && style.display !== 'none' &&
      (el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  };
  const compactText = (el) => (el.innerText || el.textContent || '').trim().replace(/\\s+/g, '');
  const nodes = Array.from(document.querySelectorAll(
    'a,button,[role="button"],li,div,span,.channel,.text,.bottom-channel,.user'
  )).filter(visible).map((el) => {
    const rect = el.getBoundingClientRect();
    const text = compactText(el);
    const profileLink = el.closest('a[href*="/user/profile/"]');
    const userEntry = el.closest('li.user,.user.side-bar-component');
    const bottomEntry = el.closest('a.bottom-channel,.bottom-channel.bottom-menu-component');
    const channelLabel = el.matches('.channel,.text') ||
      Boolean(el.querySelector('.channel,.text'));
    const avatar = Boolean((profileLink || el).querySelector('.reds-avatar,.reds-image-container,.reds-img'));
    return {el, rect, text, profileLink, userEntry, bottomEntry, channelLabel, avatar};
  }).filter((item) => {
    const exactMe = item.text === ME_BUTTON_TEXT ||
      (item.el.matches('.channel,.text') && item.text.includes(ME_BUTTON_TEXT));
    if (!exactMe) return false;
    return Boolean(item.profileLink || item.userEntry || item.bottomEntry || item.channelLabel || item.avatar);
  });
  if (!nodes.length) {
    return {success: true, me_button: false, count: 0, url: location.href};
  }
  nodes.sort((a, b) => {
    const score = (item) => {
      let value = 0;
      if (item.profileLink) value -= 300;
      if (item.userEntry) value -= 240;
      if (item.bottomEntry) value -= 220;
      if (item.channelLabel) value -= 160;
      if (item.avatar) value -= 80;
      value += item.rect.top / 120;
      return value;
    };
    return score(a) - score(b);
  });
  const best = nodes[0];
  return {
    success: true,
    me_button: true,
    text: best.text,
    count: nodes.length,
    profile_href: best.profileLink ? best.profileLink.getAttribute('href') : '',
    method: best.bottomEntry ? 'bottom_me_button' : 'sidebar_me_button',
    url: location.href
  };
})()
""",
    )


def _wait_for_me_button(run_js_fn, wait_fn, steps, max_wait_seconds, interval_seconds):
    attempts = max(1, int(max_wait_seconds / interval_seconds) + 1)
    for attempt in range(1, attempts + 1):
        state = _detect_me_button(run_js_fn)
        steps.append({"step": f"wait_me_button_attempt_{attempt}", "result": state})
        if state.get("me_button"):
            return {"success": True, "attempts": attempt, "state": state}
        if attempt < attempts:
            steps.append(
                {
                    "step": f"wait_before_me_button_attempt_{attempt + 1}",
                    "result": _safe_call(wait_fn, "", interval_seconds),
                }
            )
    return {
        "success": False,
        "requires_manual_login": True,
        "error": "Timed out waiting for Xiaohongshu Me button before publishing",
    }


def _set_editable(el_var, value_var):
    return f"""
  {{
  const setEditable = (el, value) => {{
    el.scrollIntoView({{block: 'center', inline: 'center'}});
    el.focus();
    if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {{
      const proto = el.tagName === 'TEXTAREA' ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
      const descriptor = Object.getOwnPropertyDescriptor(proto, 'value');
      if (descriptor && descriptor.set) {{
        descriptor.set.call(el, value);
      }} else {{
        el.value = value;
      }}
    }} else {{
      const escapeHtml = (text) => String(text)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
      el.innerHTML = String(value).split('\\n').map((line) => escapeHtml(line) || '<br>').join('<br>');
    }}
    const dispatchEditableEvents = (target) => {{
      try {{
        target.dispatchEvent(new InputEvent('beforeinput', {{
          bubbles: true,
          cancelable: true,
          inputType: 'insertText',
          data: value
        }}));
      }} catch (error) {{}}
      try {{
        target.dispatchEvent(new InputEvent('input', {{
          bubbles: true,
          cancelable: true,
          inputType: 'insertText',
          data: value
        }}));
      }} catch (error) {{
        target.dispatchEvent(new Event('input', {{bubbles: true}}));
      }}
      target.dispatchEvent(new Event('change', {{bubbles: true}}));
      target.dispatchEvent(new Event('blur', {{bubbles: true}}));
    }};
    const eventTargets = [el];
    const editableParent = el.closest('[contenteditable="true"],[role="textbox"],.ql-editor,.ProseMirror,[class*="editor" i]');
    if (editableParent && editableParent !== el) {{
      eventTargets.push(editableParent);
    }}
    eventTargets.forEach(dispatchEditableEvents);
  }};
  setEditable({el_var}, {value_var});
  }}
"""


def _click_text_to_image(run_js_fn):
    return _run_js_dict(
        run_js_fn,
        """
(() => {
  const TEXT_TO_IMAGE_TEXT = '\\u6587\\u5b57\\u914d\\u56fe';
  const visible = (el) => {
    const style = window.getComputedStyle(el);
    return style && style.visibility !== 'hidden' && style.display !== 'none' &&
      (el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  };
  const compactText = (el) => (el.innerText || el.textContent || '').trim().replace(/\\s+/g, '');
  const nodes = Array.from(document.querySelectorAll(
    'button,[role="button"],[role="tab"],a,div,span,li'
  )).filter(visible).map((el) => {
    const rect = el.getBoundingClientRect();
    const text = compactText(el);
    const clickable = Boolean(el.closest('button,[role="button"],[role="tab"],a')) ||
      el.tagName === 'BUTTON';
    const selected = el.getAttribute('aria-selected') === 'true' ||
      /active|selected|checked|current/i.test(String(el.className || ''));
    return {el, rect, text, clickable, selected};
  }).filter((item) => {
    if (!item.text.includes(TEXT_TO_IMAGE_TEXT)) return false;
    return item.text === TEXT_TO_IMAGE_TEXT || item.text.length <= 20 || item.clickable;
  });
  if (!nodes.length) {
    return {success: false, error: 'Text-to-image tab not found'};
  }
  nodes.sort((a, b) => {
    const score = (item) => {
      let value = item.rect.width * item.rect.height / 1000;
      if (item.text === TEXT_TO_IMAGE_TEXT) value -= 500;
      if (item.selected) value -= 180;
      if (item.clickable) value -= 120;
      value += item.rect.top / 80;
      return value;
    };
    return score(a) - score(b);
  });
  const target = nodes[0].el.closest('button,[role="button"],[role="tab"],a') || nodes[0].el;
  if (target.disabled || target.getAttribute('aria-disabled') === 'true') {
    return {success: false, error: 'Text-to-image tab is disabled', text: nodes[0].text};
  }
  target.scrollIntoView({block: 'center', inline: 'center'});
  target.click();
  return {
    success: true,
    text: nodes[0].text,
    method: nodes[0].selected ? 'selected_text_to_image' : 'click_text_to_image'
  };
})()
""",
    )


def _fill_publish_content(run_js_fn, content):
    return _run_js_dict(
        run_js_fn,
        """
(() => {
  const content = CONTENT_TEXT;
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
  const denied = (text) => /(\\u641c\\u7d22|search|\\u9a8c\\u8bc1\\u7801|code|\\u5bc6\\u7801|password|\\u624b\\u673a|phone|mobile|login|\\u6807\\u7b7e|tag|\\u8bdd\\u9898|topic)/i.test(text);
  const goodLabel = (text) => /(\\u5185\\u5bb9|\\u6b63\\u6587|\\u6587\\u6848|\\u7b14\\u8bb0|\\u63cf\\u8ff0|\\u8bf4\\u70b9|\\u8f93\\u5165|\\u751f\\u6210|prompt|content|caption|description|editor)/i.test(text);
  const candidates = Array.from(document.querySelectorAll(
    'p.editor-paragraph,.editor-paragraph,textarea,[contenteditable="true"],[role="textbox"],input,.ql-editor,.ProseMirror,[class*="editor" i]'
  )).filter(visible).map((el) => {
    const rect = el.getBoundingClientRect();
    const label = labelOf(el);
    const nearText = compactText(el.parentElement || el);
    const editorParagraph = el.matches('p.editor-paragraph,.editor-paragraph');
    return {el, rect, label, nearText, editorParagraph};
  }).filter((item) => {
    const text = `${item.label} ${item.nearText}`;
    if (denied(text)) return false;
    const type = (item.el.type || '').toLowerCase();
    if (item.el.tagName === 'INPUT' && type && !['text', 'search'].includes(type)) return false;
    return item.editorParagraph ||
      goodLabel(text) ||
      item.el.tagName === 'TEXTAREA' ||
      item.el.isContentEditable ||
      item.rect.height >= 80;
  });
  if (!candidates.length) {
    return {success: false, error: 'Xiaohongshu publish content editor not found'};
  }
  candidates.sort((a, b) => {
    const score = (item) => {
      const text = `${item.label} ${item.nearText}`;
      let value = 0;
      if (item.editorParagraph) value -= 900;
      if (goodLabel(text)) value -= 500;
      if (item.el.tagName === 'TEXTAREA') value -= 350;
      if (item.el.isContentEditable) value -= 260;
      if (/\\u751f\\u6210|prompt|description|caption|content/.test(text)) value -= 220;
      if (/\\u6807\\u9898|title/.test(text) && candidates.length > 1) value += 450;
      value -= Math.min(item.rect.height, 420) / 4;
      value += item.rect.top / 80;
      return value;
    };
    return score(a) - score(b);
  });
  const target = candidates[0].el;
SET_EDITABLE_CONTENT
  const value = target.value || target.innerText || target.textContent || '';
  return {
    success: value.includes(content.split('\\n')[0]),
    content_value: value,
    selector: target.placeholder || target.getAttribute('data-placeholder') || target.className || target.id || target.tagName
  };
})()
"""
        .replace("CONTENT_TEXT", _js_string(content))
        .replace("SET_EDITABLE_CONTENT", _set_editable("target", "content")),
    )


def _click_generate_image(run_js_fn):
    return _run_js_dict(
        run_js_fn,
        """
(() => {
  const GENERATE_IMAGE_TEXT = '\\u751f\\u6210\\u56fe\\u7247';
  const visible = (el) => {
    const style = window.getComputedStyle(el);
    return style && style.visibility !== 'hidden' && style.display !== 'none' &&
      (el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  };
  const compactText = (el) => (el.innerText || el.textContent || '').trim().replace(/\\s+/g, '');
  const nodes = Array.from(document.querySelectorAll('button,[role="button"],a,div,span'))
    .filter(visible).map((el) => {
      const rect = el.getBoundingClientRect();
      const style = window.getComputedStyle(el);
      const text = compactText(el);
      const lower = rect.top > window.innerHeight * 0.35;
      const clickable = Boolean(el.closest('button,[role="button"],a')) || el.tagName === 'BUTTON';
      const editTextButton = Boolean(
        el.matches('span.edit-text-button-text,.edit-text-button-text') ||
        el.closest('span.edit-text-button-text,.edit-text-button-text')
      );
      const colored = /rgb\\(\\s*(220|230|240|250|255)\\s*,\\s*(0|20|40|50|60|70|80|90)\\s*,\\s*(50|60|70|80|90|100|110|120)\\s*\\)|#?ff2442|#?fe2c55|#?1890ff/i.test(
        `${style.backgroundColor} ${style.color} ${style.borderColor}`
      );
      return {el, rect, text, lower, clickable, colored, editTextButton};
    }).filter((item) => {
      if (!item.text.includes(GENERATE_IMAGE_TEXT)) return false;
      return item.editTextButton || item.text === GENERATE_IMAGE_TEXT || item.text.length <= 20 || item.clickable;
    });
  if (!nodes.length) {
    return {success: false, error: 'Generate-image button not found'};
  }
  nodes.sort((a, b) => {
    const score = (item) => {
      let value = item.rect.width * item.rect.height / 1000;
      if (item.editTextButton) value -= 1000;
      if (item.text === GENERATE_IMAGE_TEXT) value -= 500;
      if (item.lower) value -= 180;
      if (item.colored) value -= 140;
      if (item.clickable) value -= 100;
      return value;
    };
    return score(a) - score(b);
  });
  const target = nodes[0].el.closest('button,[role="button"],a') || nodes[0].el;
  if (target.disabled || target.getAttribute('aria-disabled') === 'true') {
    return {success: false, error: 'Generate-image button is disabled', text: nodes[0].text};
  }
  target.scrollIntoView({block: 'center', inline: 'center'});
  target.click();
  return {
    success: true,
    text: nodes[0].text,
    method: nodes[0].editTextButton ? 'edit_text_generate_image_button' : (nodes[0].lower ? 'lower_generate_image_button' : 'generate_image_button')
  };
})()
""",
    )


def _detect_preview_image(run_js_fn):
    return _run_js_dict(
        run_js_fn,
        """
(() => {
  const PREVIEW_IMAGE_TEXT = '\\u9884\\u89c8\\u56fe\\u7247';
  const visible = (el) => {
    const style = window.getComputedStyle(el);
    return style && style.visibility !== 'hidden' && style.display !== 'none' &&
      (el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  };
  const compactText = (el) => (el.innerText || el.textContent || '').trim().replace(/\\s+/g, '');
  const matches = Array.from(document.querySelectorAll('body,h1,h2,h3,div,span,p'))
    .filter(visible).map((el) => ({el, text: compactText(el), rect: el.getBoundingClientRect()}))
    .filter((item) => item.text.includes(PREVIEW_IMAGE_TEXT));
  const topLeft = matches.find((item) => (
    item.rect.top < Math.max(180, window.innerHeight * 0.3) &&
    item.rect.left < Math.max(420, window.innerWidth * 0.45)
  ));
  const best = topLeft || matches[0] || null;
  return {
    success: Boolean(best),
    preview_image: Boolean(best),
    top_left: Boolean(topLeft),
    text: best ? best.text : '',
    count: matches.length
  };
})()
""",
    )


def _click_next_step(run_js_fn):
    return _run_js_dict(
        run_js_fn,
        """
(() => {
  const NEXT_STEP_TEXT = '\\u4e0b\\u4e00\\u6b65';
  const visible = (el) => {
    const style = window.getComputedStyle(el);
    return style && style.visibility !== 'hidden' && style.display !== 'none' &&
      (el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  };
  const compactText = (el) => (el.innerText || el.textContent || '').trim().replace(/\\s+/g, '');
  const nodes = Array.from(document.querySelectorAll('button,[role="button"],a,div,span'))
    .filter(visible).map((el) => {
      const rect = el.getBoundingClientRect();
      const style = window.getComputedStyle(el);
      const text = compactText(el);
      const lowerLeft = rect.top > window.innerHeight * 0.45 &&
        rect.left < Math.max(520, window.innerWidth * 0.55);
      const clickable = Boolean(el.closest('button,[role="button"],a')) || el.tagName === 'BUTTON';
      const red = /rgb\\(\\s*(220|230|240|250|255)\\s*,\\s*(0|20|30|40|50|60|70|80|90)\\s*,\\s*(40|50|60|70|80|90|100|110|120)\\s*\\)|#?ff2442|#?fe2c55/i.test(
        `${style.backgroundColor} ${style.color} ${style.borderColor}`
      );
      return {el, rect, text, lowerLeft, clickable, red};
    }).filter((item) => {
      if (!item.text.includes(NEXT_STEP_TEXT)) return false;
      return item.text === NEXT_STEP_TEXT || item.text.length <= 16 || item.clickable;
    });
  if (!nodes.length) {
    return {success: false, error: 'Next-step button not found'};
  }
  nodes.sort((a, b) => {
    const score = (item) => {
      let value = item.rect.width * item.rect.height / 1000;
      if (item.text === NEXT_STEP_TEXT) value -= 500;
      if (item.lowerLeft) value -= 220;
      if (item.red) value -= 160;
      if (item.clickable) value -= 100;
      return value;
    };
    return score(a) - score(b);
  });
  const target = nodes[0].el.closest('button,[role="button"],a') || nodes[0].el;
  if (target.disabled || target.getAttribute('aria-disabled') === 'true') {
    return {success: false, error: 'Next-step button is disabled', text: nodes[0].text};
  }
  target.scrollIntoView({block: 'center', inline: 'center'});
  target.click();
  return {
    success: true,
    text: nodes[0].text,
    method: nodes[0].lowerLeft ? 'lower_left_next_step' : 'next_step_button'
  };
})()
""",
    )


def _detect_image_edit(run_js_fn):
    return _run_js_dict(
        run_js_fn,
        """
(() => {
  const IMAGE_EDIT_TEXT = '\\u56fe\\u7247\\u7f16\\u8f91';
  const visible = (el) => {
    const style = window.getComputedStyle(el);
    return style && style.visibility !== 'hidden' && style.display !== 'none' &&
      (el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  };
  const compactText = (el) => (el.innerText || el.textContent || '').trim().replace(/\\s+/g, '');
  const matches = Array.from(document.querySelectorAll('body,h1,h2,h3,div,span,p'))
    .filter(visible).map((el) => ({el, text: compactText(el), rect: el.getBoundingClientRect()}))
    .filter((item) => item.text.includes(IMAGE_EDIT_TEXT));
  const top = matches.find((item) => item.rect.top < Math.max(220, window.innerHeight * 0.35));
  const best = top || matches[0] || null;
  return {
    success: Boolean(best),
    image_edit: Boolean(best),
    top: Boolean(top),
    text: best ? best.text : '',
    count: matches.length
  };
})()
""",
    )


def _click_final_publish(run_js_fn, mouse_click_fn=None):
    host_result = _run_js_dict(
        run_js_fn,
        """
(() => {
  const FINAL_PUBLISH_TEXT = '\\u53d1\\u5e03';
  const XHS_PUBLISH_HOST = 'xhs-publish-btn';
  const visible = (el) => {
    const style = window.getComputedStyle(el);
    return style && style.visibility !== 'hidden' && style.display !== 'none' &&
      (el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  };
  const hosts = Array.from(document.querySelectorAll(XHS_PUBLISH_HOST))
    .filter(visible)
    .filter((el) => {
      const submitText = (el.getAttribute('submit-text') || '').trim();
      return submitText.includes(FINAL_PUBLISH_TEXT) ||
        el.getAttribute('is-publish') === 'true';
    });
  if (!hosts.length) {
    return {success: false, has_host: false, error: 'XHS publish host not found'};
  }
  const host = hosts.find((el) => el.getAttribute('submit-disabled') !== 'true') || hosts[0];
  if (host.getAttribute('submit-disabled') === 'true' || host.hasAttribute('disabled')) {
    return {success: false, has_host: true, error: 'XHS publish host is disabled'};
  }
  host.scrollIntoView({block: 'end', inline: 'center'});
  const rect = host.getBoundingClientRect();
  const hasSaveButton = host.getAttribute('is-save-draft') !== 'false' &&
    Boolean((host.getAttribute('save-text') || '').trim());
  const redButtonOffset = hasSaveButton ? 72 : 0;
  const x = Math.max(rect.left + 8, Math.min(rect.right - 8, rect.left + rect.width / 2 + redButtonOffset));
  const y = Math.max(rect.top + 8, Math.min(rect.bottom - 8, rect.top + rect.height / 2));
  return {
    success: true,
    has_host: true,
    x,
    y,
    text: host.getAttribute('submit-text') || FINAL_PUBLISH_TEXT,
    method: 'xhs_publish_host_coordinate'
  };
})()
""",
    )
    if host_result.get("has_host"):
        native_result = None
        if host_result.get("success") and mouse_click_fn is not None:
            native_result = _safe_call(
                mouse_click_fn,
                {"success": False, "error": "mouse click failed"},
                host_result.get("x"),
                host_result.get("y"),
            )
            if not isinstance(native_result, dict):
                native_result = {"success": bool(native_result), "result": native_result}
            if native_result.get("success"):
                result = dict(host_result)
                result["click_result"] = native_result
                return result

        if host_result.get("success"):
            fallback_result = _run_js_dict(
                run_js_fn,
                """
(() => {
  const x = CLICK_X;
  const y = CLICK_Y;
  const host = document.querySelector('xhs-publish-btn[submit-text*="\\u53d1\\u5e03"],xhs-publish-btn[is-publish="true"]');
  const target = document.elementFromPoint(x, y) || host;
  if (!target) {
    return {success: false, error: 'No target at XHS publish coordinates'};
  }
  const dispatch = (el, type) => {
    const options = {
      bubbles: true,
      cancelable: true,
      composed: true,
      view: window,
      clientX: x,
      clientY: y,
      button: 0,
      buttons: type === 'mouseup' || type === 'pointerup' || type === 'click' ? 0 : 1
    };
    try {
      if (type.startsWith('pointer') && window.PointerEvent) {
        el.dispatchEvent(new PointerEvent(type, options));
      } else {
        el.dispatchEvent(new MouseEvent(type, options));
      }
    } catch (error) {
      el.dispatchEvent(new Event(type, {bubbles: true, cancelable: true, composed: true}));
    }
  };
  ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click'].forEach((type) => dispatch(target, type));
  return {
    success: true,
    has_host: true,
    text: host ? host.getAttribute('submit-text') : '',
    method: 'xhs_publish_host_event_fallback',
    target_tag: target.tagName,
    target_class: String(target.className || '')
  };
})()
"""
                .replace("CLICK_X", str(host_result.get("x") or 0))
                .replace("CLICK_Y", str(host_result.get("y") or 0)),
            )
            if fallback_result.get("success"):
                return fallback_result

        result = dict(host_result)
        result["success"] = False
        if native_result is not None:
            result["click_result"] = native_result
        return result

    return _run_js_dict(
        run_js_fn,
        """
(() => {
  const FINAL_PUBLISH_TEXT = '\\u53d1\\u5e03';
  const visible = (el) => {
    const style = window.getComputedStyle(el);
    return style && style.visibility !== 'hidden' && style.display !== 'none' &&
      (el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  };
  const compactText = (el) => (el.innerText || el.textContent || '').trim().replace(/\\s+/g, '');
  const nodes = Array.from(document.querySelectorAll('button,[role="button"],a,div,span'))
    .filter(visible).map((el) => {
      const rect = el.getBoundingClientRect();
      const style = window.getComputedStyle(el);
      const text = compactText(el);
      const lower = rect.top > window.innerHeight * 0.45;
      const clickable = Boolean(el.closest('button,[role="button"],a')) || el.tagName === 'BUTTON';
      const ceRed = Boolean(
        el.matches('button.ce-btn.bg-red,.ce-btn.bg-red') ||
        el.closest('button.ce-btn.bg-red,.ce-btn.bg-red')
      );
      const red = /rgb\\(\\s*(220|230|240|250|255)\\s*,\\s*(0|20|30|40|50|60|70|80|90)\\s*,\\s*(40|50|60|70|80|90|100|110|120)\\s*\\)|#?ff2442|#?fe2c55/i.test(
        `${style.backgroundColor} ${style.color} ${style.borderColor}`
      );
      return {el, rect, text, lower, clickable, red, ceRed};
    }).filter((item) => {
      if (!item.text.includes(FINAL_PUBLISH_TEXT)) return false;
      if (/\\u5b9a\\u65f6|\\u8bbe\\u7f6e|\\u58f0\\u660e|\\u53d1\\u5e03\\u8bbe\\u7f6e/.test(item.text)) return false;
      return item.ceRed || item.text === FINAL_PUBLISH_TEXT || item.text.length <= 12 || item.clickable;
    });
  if (!nodes.length) {
    return {success: false, error: 'Final publish button not found'};
  }
  nodes.sort((a, b) => {
      const score = (item) => {
      let value = item.rect.width * item.rect.height / 1000;
      if (item.ceRed) value -= 1000;
      if (item.text === FINAL_PUBLISH_TEXT) value -= 500;
      if (item.lower) value -= 220;
      if (item.red) value -= 160;
      if (item.clickable) value -= 100;
      return value;
    };
    return score(a) - score(b);
  });
  const target = nodes[0].el.closest('button,[role="button"],a') || nodes[0].el;
  if (target.disabled || target.getAttribute('aria-disabled') === 'true') {
    return {success: false, error: 'Final publish button is disabled', text: nodes[0].text};
  }
  target.scrollIntoView({block: 'center', inline: 'center'});
  target.click();
  return {
    success: true,
    text: nodes[0].text,
    method: nodes[0].ceRed ? 'ce_red_publish_button' : (nodes[0].lower ? 'lower_publish_button' : 'publish_button')
  };
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


def _resolve_mouse_click(mouse_click_fn):
    if mouse_click_fn is not None:
        return mouse_click_fn
    if _controls is not None and hasattr(_controls, "mouse_click"):
        return _controls.mouse_click
    try:
        return mouse_click
    except Exception:
        return None


def run(
    keyword,
    phone_number=None,
    *,
    login_url=DEFAULT_LOGIN_URL,
    publish_url=DEFAULT_PUBLISH_URL,
    max_wait_seconds=300,
    wait_seconds=1,
    goto_fn=None,
    run_js_fn=None,
    wait_fn=None,
    get_url_fn=None,
    get_text_fn=None,
    mouse_click_fn=None,
    log_fn=None,
):
    """Log in to Xiaohongshu if needed, fill image-text content, and generate."""
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
    mouse_click_fn = _resolve_mouse_click(mouse_click_fn)

    log_fn = _resolve_log(log_fn)
    steps = []

    try:
        publish_content = str(keyword).strip()
        if not publish_content:
            raise ValueError("Xiaohongshu publish requires content")

        steps.append({"step": "navigate_login", "result": goto_fn(login_url)})
        if wait_seconds:
            steps.append({"step": "wait_after_login_navigation", "result": wait_fn(wait_seconds)})

        blocked = _detect_blocked(get_url_fn, get_text_fn)
        if blocked:
            blocked["steps"] = steps
            log_fn("Xiaohongshu login blocked by security restriction")
            return blocked

        login_state = _detect_login_state(run_js_fn)
        steps.append({"step": "detect_login_state", "result": login_state})

        phone = None
        if not login_state.get("logged_in"):
            if not phone_number:
                return {
                    "success": False,
                    "requires_phone_number": True,
                    "error": "Xiaohongshu publish requires phone number when not logged in",
                    "steps": steps,
                }

            phone = _normalize_phone_number(phone_number)

            fill_result = _fill_phone(run_js_fn, phone)
            steps.append({"step": "fill_phone", "result": fill_result})
            if not fill_result.get("success"):
                return {
                    "success": False,
                    "error": "Failed to fill Xiaohongshu phone number",
                    "steps": steps,
                }

            agreement_result = _accept_agreement(run_js_fn)
            steps.append({"step": "accept_agreement", "result": agreement_result})
            if not agreement_result.get("success"):
                return {
                    "success": False,
                    "error": "Failed to accept Xiaohongshu agreement",
                    "steps": steps,
                }

            get_code_result = _click_get_code(run_js_fn)
            steps.append({"step": "click_get_code", "result": get_code_result})
            if not get_code_result.get("success"):
                return {
                    "success": False,
                    "error": "Failed to request Xiaohongshu verification code",
                    "steps": steps,
                }

            log_fn("Please enter the Xiaohongshu SMS verification code in the browser.")
            wait_result = _wait_for_about_us(
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
                    "error": "Please complete Xiaohongshu login before publishing",
                    "steps": steps,
                }

        me_result = _wait_for_me_button(
            run_js_fn,
            wait_fn,
            steps,
            max_wait_seconds=max_wait_seconds,
            interval_seconds=2,
        )
        steps.append({"step": "login_me_button_confirmation", "result": me_result})
        if not me_result.get("success"):
            return {
                "success": False,
                "requires_manual_login": True,
                "error": "Please complete Xiaohongshu login before opening publish page",
                "steps": steps,
            }

        steps.append({"step": "navigate_publish_editor", "result": goto_fn(publish_url)})
        steps.append({"step": "wait_after_publish_navigation", "result": _safe_call(wait_fn, "", 2)})

        text_to_image_result = _retry(
            "click_text_to_image",
            lambda: _click_text_to_image(run_js_fn),
            steps,
            wait_fn,
            attempts=5,
            interval=1,
        )
        if not text_to_image_result.get("success"):
            return {
                "success": False,
                "error": "Failed to click Xiaohongshu text-to-image mode",
                "steps": steps,
            }
        steps.append({"step": "wait_after_text_to_image", "result": _safe_call(wait_fn, "", 1)})

        fill_publish_result = _retry(
            "fill_publish_content",
            lambda: _fill_publish_content(run_js_fn, publish_content),
            steps,
            wait_fn,
            attempts=5,
            interval=1,
        )
        if not fill_publish_result.get("success"):
            return {
                "success": False,
                "error": "Failed to fill Xiaohongshu publish content",
                "steps": steps,
            }
        steps.append(
            {"step": "wait_after_fill_publish_content", "result": _safe_call(wait_fn, "", 2)}
        )

        generate_result = _retry(
            "click_generate_image",
            lambda: _click_generate_image(run_js_fn),
            steps,
            wait_fn,
            attempts=5,
            interval=1,
        )
        if not generate_result.get("success"):
            return {
                "success": False,
                "error": "Failed to click Xiaohongshu generate-image button",
                "steps": steps,
            }

        preview_result = _retry(
            "detect_preview_image",
            lambda: _detect_preview_image(run_js_fn),
            steps,
            wait_fn,
            attempts=60,
            interval=1,
        )
        if not preview_result.get("success"):
            return {
                "success": False,
                "error": "Failed to detect Xiaohongshu preview image screen",
                "steps": steps,
            }

        next_result = _retry(
            "click_next_step",
            lambda: _click_next_step(run_js_fn),
            steps,
            wait_fn,
            attempts=5,
            interval=1,
        )
        if not next_result.get("success"):
            return {
                "success": False,
                "error": "Failed to click Xiaohongshu next-step button",
                "steps": steps,
            }
        steps.append({"step": "wait_after_next_step", "result": _safe_call(wait_fn, "", 1)})

        image_edit_result = _retry(
            "detect_image_edit",
            lambda: _detect_image_edit(run_js_fn),
            steps,
            wait_fn,
            attempts=30,
            interval=1,
        )
        if not image_edit_result.get("success"):
            return {
                "success": False,
                "error": "Failed to detect Xiaohongshu image edit screen",
                "steps": steps,
            }

        publish_result = _retry(
            "click_final_publish",
            lambda: _click_final_publish(run_js_fn, mouse_click_fn),
            steps,
            wait_fn,
            attempts=5,
            interval=1,
        )
        if not publish_result.get("success"):
            return {
                "success": False,
                "error": "Failed to click Xiaohongshu publish button",
                "steps": steps,
            }

        log_fn("Xiaohongshu publish button clicked")
        return {
            "success": True,
            "content": publish_content,
            "phone_number": phone,
            "url": _safe_call(get_url_fn, ""),
            "steps": steps,
            "message": "Xiaohongshu image-text content generated, advanced, and publish button clicked.",
        }

    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        log_fn(f"Xiaohongshu image-text publish failed: {error}")
        return {"success": False, "error": error, "steps": steps}

"""Gmail email sending adapter."""

try:
    from src.layer_2 import controls as _controls
except Exception:
    _controls = None


DEFAULT_INBOX_URL = "https://mail.google.com/mail/u/0/#inbox"
DEFAULT_LOGIN_URL = "https://mail.google.com/mail?hl=zh-CN"
DEFAULT_LOGIN_WAIT_SECONDS = 300
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


def _resolve_optional_function(name, provided=None):
    if provided is not None:
        return provided
    if _controls is not None and hasattr(_controls, name):
        return getattr(_controls, name)
    if name == "type_text":
        try:
            return type_text
        except Exception:
            return None
    if name == "press_key":
        try:
            return press_key
        except Exception:
            return None
    return None


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


def _detect_logged_in(run_js_fn):
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
    el.getAttribute('aria-label') || '',
    el.getAttribute('placeholder') || '',
    el.getAttribute('title') || '',
    el.name || '',
    el.id || '',
    (el.innerText || el.textContent || '').trim()
  ].join(' ');
  const searchMail = Array.from(document.querySelectorAll(
    'input[aria-label="Search mail"],input[placeholder="Search mail"],input[name="q"],input[type="text"]'
  )).some((el) => visible(el) && /Search mail/i.test(textOf(el)));
  return {
    success: true,
    logged_in: Boolean(searchMail),
    search_mail: Boolean(searchMail),
    url: location.href
  };
})()
""",
    )


def _wait_for_login_completion(
    run_js_fn,
    wait_fn,
    steps,
    max_wait_seconds=DEFAULT_LOGIN_WAIT_SECONDS,
    interval_seconds=2,
):
    attempts = max(1, int(max_wait_seconds / interval_seconds) + 1)
    for attempt in range(1, attempts + 1):
        state = _detect_logged_in(run_js_fn)
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
        "error": "Timed out waiting for Gmail login completion",
    }


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
    return {"success": False, "error": "Timed out waiting for Gmail after login"}


def _click_compose(run_js_fn):
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
    el.getAttribute('data-tooltip') || '',
    el.getAttribute('gh') || ''
  ].join(' ');
  const candidates = Array.from(document.querySelectorAll(
    'div[gh="cm"],.z0 .T-I[role="button"],div[role="button"],button,[aria-label*="Compose" i]'
  )).filter(visible).map((el) => {
    const rect = el.getBoundingClientRect();
    const text = textOf(el);
    let score = rect.top + rect.left / 10;
    if (el.getAttribute('gh') === 'cm') score -= 1000;
    if (/\\bCompose\\b/i.test(text)) score -= 500;
    return {el, text, score};
  }).filter((item) => item.el.getAttribute('gh') === 'cm' || /\\bCompose\\b/i.test(item.text));
  if (!candidates.length) {
    return {success: false, error: 'Gmail compose button not found'};
  }
  candidates.sort((a, b) => a.score - b.score);
  const target = candidates[0].el.closest('[role="button"],button,div[gh="cm"]') || candidates[0].el;
  target.scrollIntoView({block: 'center', inline: 'center'});
  target.click();
  return {success: true, text: candidates[0].text};
})()
""",
    )


def _click_compose_fullscreen(run_js_fn):
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
    el.getAttribute('data-tooltip') || '',
    el.getAttribute('alt') || '',
    String(el.className || ''),
    el.id || ''
  ].join(' ');
  const alreadyFull = Array.from(document.querySelectorAll(
    'img[role="button"],div[role="button"],button,[aria-label],[data-tooltip],[alt]'
  )).filter(visible).some((el) => /Exit full screen|退出全屏/i.test(textOf(el)));
  if (alreadyFull) {
    return {success: true, skipped: true, already_fullscreen: true};
  }
  const candidates = Array.from(document.querySelectorAll(
    'img.Hq.aUG[role="button"],img.Hq.aUG[aria-label*="Full screen" i],img.Hq.aUG[data-tooltip*="Full screen" i],img[role="button"][aria-label*="Full screen" i],img[role="button"][data-tooltip*="Full screen" i],img[role="button"][alt*="Pop-out" i],img[role="button"],div[role="button"],button,[aria-label],[data-tooltip],[alt],.Hq.aUG'
  )).filter(visible).map((el) => {
    const text = textOf(el);
    const rect = el.getBoundingClientRect();
    let score = rect.top + rect.left / 10;
    if (/Full screen/i.test(text)) score -= 1000;
    if (/Pop-out/i.test(text)) score -= 800;
    if (String(el.className || '').includes('Hq') && String(el.className || '').includes('aUG')) score -= 500;
    if (/Minimize|Close|Save & close|最小化|关闭/i.test(text)) score += 5000;
    return {el, text, score};
  }).filter((item) => /Full screen|Pop-out/i.test(item.text) && !/Minimize|Close|Save & close/i.test(item.text));
  if (!candidates.length) {
    return {success: false, error: 'Gmail compose full screen button not found'};
  }
  candidates.sort((a, b) => a.score - b.score);
  const target = candidates[0].el.closest('[role="button"],button') || candidates[0].el;
  target.scrollIntoView({block: 'center', inline: 'center'});
  target.click();
  return {success: true, clicked: true, text: candidates[0].text, id: target.id || ''};
})()
""",
    )


def _detect_compose_popup(run_js_fn):
    return _run_js_dict(
        run_js_fn,
        """
(() => {
  const visible = (el) => {
    const style = window.getComputedStyle(el);
    if (!style || style.visibility === 'hidden' || style.display === 'none') return false;
    if (el.type === 'hidden' || el.getAttribute('aria-hidden') === 'true') return false;
    return Boolean(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  };
  const compactText = (el) => (el.innerText || el.textContent || '').trim().replace(/\\s+/g, ' ');
  const buttonText = (el) => [
    compactText(el),
    el.getAttribute('aria-label') || '',
    el.getAttribute('data-tooltip') || '',
    el.getAttribute('alt') || '',
    String(el.className || ''),
    el.id || ''
  ].join(' ');
  const popup = Array.from(document.querySelectorAll('.Hp,.a3E,[role="dialog"],div'))
    .some((el) => visible(el) && /Compose:|New Message|新邮件|撰写/i.test(compactText(el)));
  const fullscreenButton = Array.from(document.querySelectorAll(
    'img[role="button"],div[role="button"],button,[aria-label],[data-tooltip],[alt],.Hq.aUG'
  )).some((el) => visible(el) && /Full screen|Pop-out|Exit full screen/i.test(buttonText(el)));
  const recipient = Array.from(document.querySelectorAll(
    'div[name="to"] input,div[aria-label="To"] input,td.eV input,input[aria-label="To recipients"],input[aria-label*="recipient" i],input[aria-label*="收件"],textarea[aria-label*="recipient" i],textarea[aria-label*="收件"],textarea[name="to"],input[name="to"]'
  )).some((el) => visible(el) && !/Search mail/i.test(el.getAttribute('aria-label') || ''));
  const subject = Array.from(document.querySelectorAll(
    'input[name="subjectbox"],input.aoT,input[aria-label*="Subject" i],input[aria-label*="主题"],input[placeholder*="Subject" i],input[placeholder*="主题"]'
  )).some((el) => visible(el));
  const body = Array.from(document.querySelectorAll(
    'div[aria-label*="Message Body" i],div[aria-label*="邮件正文"],div[role="textbox"][contenteditable="true"],.Am.Al.editable,[g_editable="true"],[contenteditable="true"]'
  )).some((el) => visible(el));
  return {
    success: true,
    popup: Boolean(popup || fullscreenButton || recipient || subject || body),
    compose_popup: Boolean(popup || fullscreenButton || recipient || subject || body),
    has_new_message: Boolean(popup),
    has_fullscreen_button: Boolean(fullscreenButton),
    has_recipient_input: Boolean(recipient),
    has_subject_input: Boolean(subject),
    has_body_editor: Boolean(body)
  };
})()
""",
    )


def _verify_recipient(run_js_fn, recipient):
    return _run_js_dict(
        run_js_fn,
        """
(() => {
  const value = RECIPIENT_VALUE;
  const localPart = value.split('@')[0];
  const textOf = (el) => [
    el.getAttribute('aria-label') || '',
    el.getAttribute('placeholder') || '',
    el.getAttribute('name') || '',
    String(el.className || ''),
    (el.innerText || el.textContent || '').trim(),
    el.value || ''
  ].join(' ');
  const containers = Array.from(document.querySelectorAll(
    'div[name="to"],div[aria-label="To"],div[aria-label*="收件"],td.eV,.oj,.wO.nr.l1,.aoD.hl,.aoD'
  ));
  const inputs = Array.from(document.querySelectorAll(
    'div[name="to"] input,div[name="to"] textarea,div[aria-label="To"] input,div[aria-label="To"] textarea,td.eV input,td.eV textarea,input[aria-label="To recipients"],input[aria-label*="recipient" i],input[aria-label*="收件"],input.agP.aFw'
  ));
  const chipTexts = Array.from(document.querySelectorAll('.aQ2,.afV,.vR,.vN,.aDm,.oL'))
    .map((el) => (el.innerText || el.textContent || '').trim())
    .filter(Boolean);
  const allText = containers.concat(inputs).map(textOf).concat(chipTexts).join('\\n');
  return {
    success: allText.includes(value) ||
      inputs.some((el) => (el.value || '').includes(value)) ||
      chipTexts.some((text) => text.includes(value) || (localPart && text === localPart)),
    text: allText,
    chips: chipTexts,
    input_values: inputs.map((el) => el.value || '').filter(Boolean)
  };
})()
""".replace("RECIPIENT_VALUE", _js_string(recipient)),
    )


def _fill_recipient(run_js_fn, recipient, type_text_fn=None, press_key_fn=None):
    native_typing = type_text_fn is not None
    focus_result = _run_js_dict(
        run_js_fn,
        """
(() => {
  const value = RECIPIENT_VALUE;
  const useNativeTyping = NATIVE_TYPING;
  const visible = (el) => {
    const style = window.getComputedStyle(el);
    if (!style || style.visibility === 'hidden' || style.display === 'none') return false;
    if (el.type === 'hidden' || el.disabled || el.getAttribute('aria-hidden') === 'true') return false;
    if (el.offsetWidth || el.offsetHeight || el.getClientRects().length) return true;
    const parent = el.closest('[role="dialog"],.nH,.AD,.M9,.aoI,.aH9');
    return Boolean(parent && parent.getClientRects().length);
  };
  const textOf = (el) => [
    el.getAttribute('aria-label') || '',
    el.getAttribute('placeholder') || '',
    el.getAttribute('name') || '',
    String(el.className || ''),
    (el.innerText || el.textContent || '').trim()
  ].join(' ');
  const nearestToContainer = (el) => el.closest(
    'div[name="to"],div[aria-label="To"],div[aria-label*="收件"],td.eV,.oj,.wO.nr.l1,.aoD.hl,.aoD'
  );
  const isRecipientInput = (el) => {
    const label = textOf(el);
    if (/Search mail/i.test(label)) return false;
    if (/cc|bcc|抄送|密送/i.test(label)) return false;
    if (/To recipients|recipient|收件/i.test(label)) return true;
    const container = nearestToContainer(el);
    if (!container) return false;
    const containerLabel = [
      container.getAttribute('name') || '',
      container.getAttribute('aria-label') || '',
      String(container.className || ''),
      (container.innerText || container.textContent || '').trim()
    ].join(' ');
    return /(^|\\s)to($|\\s)|recipient|收件|\\boj\\b|\\beV\\b|\\bwO\\b/i.test(containerLabel);
  };
  const queryInputs = () => Array.from(document.querySelectorAll(
    'div[name="to"] input,div[name="to"] textarea,div[aria-label="To"] input,div[aria-label="To"] textarea,div[aria-label*="收件"] input,div[aria-label*="收件"] textarea,td.eV input,td.eV textarea,input[aria-label="To recipients"],input[aria-label*="recipient" i],input[aria-label*="收件"],textarea[aria-label*="recipient" i],textarea[aria-label*="收件"],input[name="to"],textarea[name="to"],input.agP.aFw'
  )).filter(visible).filter(isRecipientInput).map((el) => {
    const label = textOf(el);
    const rect = el.getBoundingClientRect();
    let score = rect.top + rect.left / 10;
    if (/To recipients|收件|recipient/i.test(label)) score -= 1000;
    if (nearestToContainer(el)) score -= 800;
    if (/agP|aFw/.test(label)) score -= 500;
    if (/cc|bcc|抄送|密送|Search mail/i.test(label)) score += 5000;
    return {el, label, score};
  }).filter((item) => !/cc|bcc|抄送|密送|Search mail/i.test(item.label));

  const queryRecipientRows = () => Array.from(document.querySelectorAll(
    '.aoD.hl,.aoD,td.eV div[tabindex],div[name="to"],div[aria-label="To"],div[aria-label*="收件"]'
  )).filter(visible).map((el) => {
    const label = textOf(el);
    const rect = el.getBoundingClientRect();
    let score = rect.top + rect.left / 10;
    if (/Recipients|To|收件人|收件邮箱/i.test(label)) score -= 1000;
    if (String(el.className || '').includes('aoD')) score -= 800;
    if (String(el.className || '').includes('hl')) score -= 300;
    if (/cc|bcc|抄送|密送|Search mail/i.test(label)) score += 5000;
    return {el, label, score};
  }).filter((item) => {
    if (/cc|bcc|抄送|密送|Search mail/i.test(item.label)) return false;
    return /Recipients|To|收件人|收件邮箱/i.test(item.label) ||
      item.el.matches('.aoD.hl,.aoD,td.eV div[tabindex],div[name="to"],div[aria-label="To"],div[aria-label*="收件"]');
  }).sort((a, b) => a.score - b.score);

  let inputs = queryInputs();
  if (!inputs.length) {
    const row = queryRecipientRows()[0];
    if (row) {
      const clickTarget = row.el.closest('.aoD.hl,.aoD,td.eV,div[name="to"],div[aria-label="To"],div[aria-label*="收件"]') || row.el;
      clickTarget.scrollIntoView({block: 'center', inline: 'center'});
      clickTarget.focus && clickTarget.focus();
      clickTarget.click();
      inputs = queryInputs();
    }
  }
  if (!inputs.length) {
    const labels = Array.from(document.querySelectorAll('.aoD.hl,.aoD,td.eV span,td.eV div,div[name="to"],div[aria-label="To"],div[aria-label*="收件"],label'))
      .filter(visible)
      .filter((el) => /Recipients|To|收件人|收件邮箱/i.test((el.innerText || el.textContent || '').trim()))
      .map((el) => el.closest('.aoD.hl,.aoD,td.eV,div[name="to"],div[aria-label="To"],div[aria-label*="收件"]') || el)
      .filter((el, index, list) => list.indexOf(el) === index);
    if (labels[0]) {
      labels[0].scrollIntoView({block: 'center', inline: 'center'});
      labels[0].focus && labels[0].focus();
      labels[0].click();
      inputs = queryInputs();
    }
  }
  if (!inputs.length) {
    const active = document.activeElement;
    if (active && visible(active) && isRecipientInput(active)) {
      inputs = [{el: active, label: textOf(active), score: -2000}];
    }
  }
  inputs.sort((a, b) => a.score - b.score);
  const target = inputs[0] && inputs[0].el;
  if (!target) {
    return {success: false, error: 'Gmail recipient input not found'};
  }
  const proto = target.tagName.toLowerCase() === 'textarea' ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
  const descriptor = Object.getOwnPropertyDescriptor(proto, 'value');
  target.scrollIntoView({block: 'center', inline: 'center'});
  target.focus();
  target.click();
  if (useNativeTyping) {
    return {
      success: true,
      focused: true,
      target_id: target.id || '',
      target_label: target.getAttribute('aria-label') || '',
      active_tag: document.activeElement ? document.activeElement.tagName : '',
      active_label: document.activeElement ? (document.activeElement.getAttribute('aria-label') || '') : ''
    };
  }
  const setValue = (newValue) => {
    if (descriptor && descriptor.set) {
      descriptor.set.call(target, newValue);
    } else {
      target.value = newValue;
    }
  };
  setValue('');
  target.dispatchEvent(new Event('input', {bubbles: true}));
  for (const char of value) {
    target.dispatchEvent(new KeyboardEvent('keydown', {
      bubbles: true, cancelable: true, key: char, code: char, charCode: char.charCodeAt(0),
      keyCode: char.charCodeAt(0), which: char.charCodeAt(0)
    }));
    try {
      target.dispatchEvent(new InputEvent('beforeinput', {
        bubbles: true, cancelable: true, inputType: 'insertText', data: char
      }));
    } catch (err) {}
    setValue((target.value || '') + char);
    try {
      target.dispatchEvent(new InputEvent('input', {
        bubbles: true, cancelable: true, inputType: 'insertText', data: char
      }));
    } catch (err) {
      target.dispatchEvent(new Event('input', {bubbles: true}));
    }
    target.dispatchEvent(new KeyboardEvent('keypress', {
      bubbles: true, cancelable: true, key: char, code: char, charCode: char.charCodeAt(0),
      keyCode: char.charCodeAt(0), which: char.charCodeAt(0)
    }));
    target.dispatchEvent(new KeyboardEvent('keyup', {
      bubbles: true, cancelable: true, key: char, code: char, charCode: char.charCodeAt(0),
      keyCode: char.charCodeAt(0), which: char.charCodeAt(0)
    }));
  }
  const beforeEnterValue = target.value || '';
  target.dispatchEvent(new Event('change', {bubbles: true}));
  target.dispatchEvent(new KeyboardEvent('keydown', {bubbles: true, cancelable: true, key: 'Enter', code: 'Enter', keyCode: 13, which: 13}));
  target.dispatchEvent(new KeyboardEvent('keypress', {bubbles: true, cancelable: true, key: 'Enter', code: 'Enter', keyCode: 13, which: 13}));
  target.dispatchEvent(new KeyboardEvent('keyup', {bubbles: true, cancelable: true, key: 'Enter', code: 'Enter', keyCode: 13, which: 13}));
  const container = nearestToContainer(target);
  const containerText = container ? (container.innerText || container.textContent || '') : '';
  const localPart = value.split('@')[0];
  const chipTexts = container ? Array.from(container.querySelectorAll('.aQ2,.afV,.vR,.vN')).map((el) => (el.innerText || el.textContent || '').trim()).filter(Boolean) : [];
  return {
    success: beforeEnterValue.includes(value) ||
      (target.value || '').includes(value) ||
      containerText.includes(value) ||
      chipTexts.some((text) => text.includes(value) || (localPart && text === localPart)),
    value: target.value || beforeEnterValue || '',
    container_text: containerText,
    chips: chipTexts,
    target_id: target.id || '',
    target_label: target.getAttribute('aria-label') || ''
  };
})()
""".replace("RECIPIENT_VALUE", _js_string(recipient)).replace(
            "NATIVE_TYPING", "true" if native_typing else "false"
        ),
    )
    if not native_typing:
        return focus_result

    if not focus_result.get("success"):
        return focus_result

    type_result = _safe_call(
        type_text_fn,
        {"success": False, "error": "type_text failed"},
        str(recipient),
    )
    press_result = (
        _safe_call(press_key_fn, {"success": False, "error": "press_key unavailable"}, "Enter")
        if press_key_fn is not None
        else {"success": False, "error": "press_key unavailable"}
    )
    verify_result = _verify_recipient(run_js_fn, recipient)
    verify_result["focus_result"] = focus_result
    verify_result["type_result"] = type_result
    verify_result["press_result"] = press_result
    if verify_result.get("success"):
        return verify_result

    fallback_result = _fill_recipient(run_js_fn, recipient)
    fallback_result["native_verify"] = verify_result
    return fallback_result


def _fill_subject(run_js_fn, subject):
    return _run_js_dict(
        run_js_fn,
        """
(() => {
  const value = SUBJECT_VALUE;
  const visible = (el) => {
    const style = window.getComputedStyle(el);
    if (!style || style.visibility === 'hidden' || style.display === 'none') return false;
    if (el.type === 'hidden' || el.disabled || el.getAttribute('aria-hidden') === 'true') return false;
    return Boolean(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  };
  const candidates = Array.from(document.querySelectorAll(
    'input[name="subjectbox"],input.aoT,input[aria-label*="Subject" i],input[aria-label*="主题"],input[placeholder*="Subject" i],input[placeholder*="主题"],input[name="subject"]'
  ));
  const visibleCandidates = candidates.filter(visible).filter((el) => {
    const label = [
      el.name || '',
      el.getAttribute('aria-label') || '',
      el.getAttribute('placeholder') || '',
      el.id || ''
    ].join(' ');
    return /subject|主题/i.test(label);
  });
  visibleCandidates.sort((a, b) => {
    const score = (el) => {
      const label = [
        el.name || '',
        el.getAttribute('aria-label') || '',
        el.getAttribute('placeholder') || '',
        String(el.className || '')
      ].join(' ');
      let value = el.getBoundingClientRect().top + el.getBoundingClientRect().left / 10;
      if (el.name === 'subjectbox') value -= 1000;
      if (/aoT/.test(label)) value -= 500;
      if (/subject|主题/i.test(label)) value -= 250;
      return value;
    };
    return score(a) - score(b);
  });
  const target = visibleCandidates[0];
  if (!target) {
    return {success: false, error: 'Gmail subject input not found'};
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
  try {
    target.dispatchEvent(new InputEvent('input', {bubbles: true, cancelable: true, inputType: 'insertText', data: value}));
  } catch (err) {
    target.dispatchEvent(new Event('input', {bubbles: true}));
  }
  target.dispatchEvent(new Event('change', {bubbles: true}));
  return {success: (target.value || '') === value, value: target.value || '', name: target.name || ''};
})()
""".replace("SUBJECT_VALUE", _js_string(subject)),
    )


def _fill_body(run_js_fn, body, type_text_fn=None):
    native_typing = type_text_fn is not None
    focus_result = _run_js_dict(
        run_js_fn,
        """
(() => {
  const value = BODY_VALUE;
  const useNativeTyping = NATIVE_TYPING;
  const visible = (el) => {
    const style = window.getComputedStyle(el);
    if (!style || style.visibility === 'hidden' || style.display === 'none') return false;
    if (el.getAttribute('aria-hidden') === 'true') return false;
    return Boolean(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  };
  const candidates = Array.from(document.querySelectorAll(
    'div[aria-label="Message Body"][contenteditable="true"],div[aria-label*="Message Body" i][contenteditable="true"],div.Am.aiL.Al.editable[contenteditable="true"],div.Am.Al.editable[contenteditable="true"],div[g_editable="true"][role="textbox"],div[aria-label*="邮件正文"][contenteditable="true"],div[role="textbox"][contenteditable="true"],[g_editable="true"],textarea[aria-label*="Message" i],textarea[aria-label*="邮件正文"]'
  )).filter(visible).map((el) => {
    const label = [
      el.getAttribute('aria-label') || '',
      el.getAttribute('role') || '',
      String(el.className || ''),
      el.getAttribute('g_editable') || '',
      el.getAttribute('contenteditable') || '',
      el.tagName || ''
    ].join(' ');
    const rect = el.getBoundingClientRect();
    let score = rect.top + rect.left / 10;
    if (/Message Body|邮件正文/i.test(label)) score -= 1000;
    if (/textbox/i.test(label)) score -= 500;
    if (/editable|g_editable/i.test(label)) score -= 250;
    if (/\\bAm\\b/.test(label) && /\\bAl\\b/.test(label) && /editable/.test(label)) score -= 500;
    if (/Search mail|Subject|主题|recipient|收件/i.test(label)) score += 5000;
    return {el, score};
  });
  if (!candidates.length) {
    return {success: false, error: 'Gmail body editor not found'};
  }
  candidates.sort((a, b) => a.score - b.score);
  const target = candidates[0].el;
  const readText = () => (target.value || target.innerText || target.textContent || '').trim();
  target.scrollIntoView({block: 'center', inline: 'center'});
  target.focus();
  target.click();
  if (target.tagName.toLowerCase() === 'textarea') {
    const descriptor = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value');
    if (descriptor && descriptor.set) {
      descriptor.set.call(target, value);
    } else {
      target.value = value;
    }
    try {
      target.dispatchEvent(new InputEvent('input', {bubbles: true, cancelable: true, inputType: 'insertText', data: value}));
    } catch (err) {
      target.dispatchEvent(new Event('input', {bubbles: true}));
    }
    target.dispatchEvent(new Event('change', {bubbles: true}));
    return {success: (target.value || '') === value, text: target.value || '', mode: 'textarea'};
  }

  const selection = window.getSelection && window.getSelection();
  const range = document.createRange();
  range.selectNodeContents(target);
  if (selection) {
    selection.removeAllRanges();
    selection.addRange(range);
  }
  target.innerHTML = '';
  target.dispatchEvent(new Event('input', {bubbles: true}));

  if (useNativeTyping) {
    return {
      success: true,
      focused: document.activeElement === target || target.contains(document.activeElement),
      text: readText(),
      mode: 'native_focus',
      target_id: target.id || '',
      target_label: target.getAttribute('aria-label') || '',
      target_class: String(target.className || '')
    };
  }

  try {
    target.dispatchEvent(new InputEvent('beforeinput', {bubbles: true, cancelable: true, inputType: 'insertText', data: value}));
  } catch (err) {}

  let inserted = false;
  try {
    inserted = document.execCommand && document.execCommand('insertText', false, value);
  } catch (err) {
    inserted = false;
  }

  if (!inserted || readText() !== value.trim()) {
    target.innerHTML = '';
    const lines = value.split(/\\r?\\n/);
    lines.forEach((line, index) => {
      if (index > 0) target.appendChild(document.createElement('br'));
      target.appendChild(document.createTextNode(line));
    });
  } else {
    target.normalize();
  }

  try {
    target.dispatchEvent(new InputEvent('input', {bubbles: true, cancelable: true, inputType: 'insertText', data: value}));
  } catch (err) {
    target.dispatchEvent(new Event('input', {bubbles: true}));
  }
  target.dispatchEvent(new KeyboardEvent('keyup', {bubbles: true, cancelable: true, key: value.slice(-1) || 'Unidentified'}));
  target.dispatchEvent(new Event('change', {bubbles: true}));
  return {
    success: readText() === value.trim(),
    text: readText(),
    mode: inserted ? 'execCommand' : 'text_nodes',
    target_id: target.id || '',
    target_label: target.getAttribute('aria-label') || '',
    target_class: String(target.className || '')
  };
})()
""".replace("BODY_VALUE", _js_string(body)).replace(
            "NATIVE_TYPING", "true" if native_typing else "false"
        ),
    )

    if not native_typing or not focus_result.get("success"):
        return focus_result

    type_result = _safe_call(
        type_text_fn,
        {"success": False, "error": "type_text failed"},
        str(body),
    )
    verify_result = _run_js_dict(
        run_js_fn,
        """
(() => {
  const value = BODY_VALUE;
  const visible = (el) => {
    const style = window.getComputedStyle(el);
    if (!style || style.visibility === 'hidden' || style.display === 'none') return false;
    if (el.getAttribute('aria-hidden') === 'true') return false;
    return Boolean(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  };
  const candidates = Array.from(document.querySelectorAll(
    'div[aria-label="Message Body"][contenteditable="true"],div[aria-label*="Message Body" i][contenteditable="true"],div.Am.aiL.Al.editable[contenteditable="true"],div.Am.Al.editable[contenteditable="true"],div[g_editable="true"][role="textbox"],div[aria-label*="邮件正文"][contenteditable="true"],div[role="textbox"][contenteditable="true"],[g_editable="true"],textarea[aria-label*="Message" i],textarea[aria-label*="邮件正文"]'
  )).filter(visible);
  const texts = candidates.map((el) => (el.value || el.innerText || el.textContent || '').trim());
  return {
    success: texts.some((text) => text === value.trim()),
    texts,
    focus_result: FOCUS_RESULT,
    type_result: TYPE_RESULT
  };
})()
""".replace("BODY_VALUE", _js_string(body))
        .replace("FOCUS_RESULT", _js_string(focus_result))
        .replace("TYPE_RESULT", _js_string(type_result)),
    )
    if verify_result.get("success"):
        return verify_result

    fallback_result = _fill_body(run_js_fn, body)
    fallback_result["native_verify"] = verify_result
    return fallback_result


def _click_send(run_js_fn):
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
    el.getAttribute('data-tooltip') || '',
    el.id || '',
    String(el.className || '')
  ].join(' ');
  const candidates = Array.from(document.querySelectorAll(
    'div[aria-label^="Send"],div[data-tooltip^="Send"],div[role="button"],button,[role="button"]'
  )).filter(visible).map((el) => {
    const text = textOf(el);
    const rect = el.getBoundingClientRect();
    let score = rect.top + rect.left / 10;
    if (/^Send\\b/i.test((el.getAttribute('aria-label') || '').trim())) score -= 1000;
    if (/^Send\\b/i.test((el.getAttribute('data-tooltip') || '').trim())) score -= 800;
    if (/\\bSend\\b/i.test(text)) score -= 500;
    if (String(el.className || '').includes('aoO')) score -= 300;
    return {el, text, score};
  }).filter((item) => /\\bSend\\b/i.test(item.text));
  if (!candidates.length) {
    return {success: false, error: 'Gmail send button not found'};
  }
  candidates.sort((a, b) => a.score - b.score);
  const target = candidates[0].el.closest('[role="button"],button') || candidates[0].el;
  if (target.getAttribute('aria-disabled') === 'true' || target.disabled) {
    return {success: false, error: 'Gmail send button is disabled', text: candidates[0].text};
  }
  target.scrollIntoView({block: 'center', inline: 'center'});
  target.click();
  return {success: true, text: candidates[0].text};
})()
""",
    )


def _fill_login_email(run_js_fn, email):
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
    'input[type="email"],input#identifierId,input[name="identifier"],input[autocomplete="username"],input[aria-label*="email" i],input[aria-label*="邮箱"]'
  )).filter(visible)[0];
  if (!target) return {success: false, error: 'Gmail login email input not found'};
  const descriptor = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value');
  target.scrollIntoView({block: 'center', inline: 'center'});
  target.focus();
  target.click();
  if (descriptor && descriptor.set) descriptor.set.call(target, value);
  else target.value = value;
  target.dispatchEvent(new Event('input', {bubbles: true}));
  target.dispatchEvent(new Event('change', {bubbles: true}));
  return {success: (target.value || '').trim() === value, value: target.value || ''};
})()
""".replace("EMAIL_VALUE", _js_string(email)),
    )


def _fill_login_password(run_js_fn, password):
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
    'input[type="password"],input[name="Passwd"],input[autocomplete="current-password"],input[aria-label*="password" i],input[aria-label*="密码"]'
  )).filter(visible)[0];
  if (!target) return {success: false, error: 'Gmail login password input not found'};
  const descriptor = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value');
  target.scrollIntoView({block: 'center', inline: 'center'});
  target.focus();
  target.click();
  if (descriptor && descriptor.set) descriptor.set.call(target, value);
  else target.value = value;
  target.dispatchEvent(new Event('input', {bubbles: true}));
  target.dispatchEvent(new Event('change', {bubbles: true}));
  return {success: (target.value || '') === value, value_length: (target.value || '').length};
})()
""".replace("PASSWORD_VALUE", _js_string(password)),
    )


def _click_login_next(run_js_fn):
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
    el.getAttribute('data-tooltip') || '',
    el.id || ''
  ].join(' ').replace(/\\s+/g, '');
  const candidates = Array.from(document.querySelectorAll(
    '#identifierNext,#passwordNext,button,[role="button"],input[type="submit"]'
  )).filter(visible).map((el) => {
    const text = textOf(el);
    const rect = el.getBoundingClientRect();
    let score = rect.top + rect.left / 10;
    if (el.id === 'identifierNext' || el.id === 'passwordNext') score -= 1000;
    if (/下一步|Next/i.test(text)) score -= 500;
    return {el, text, score};
  }).filter((item) => {
    if (/取消|返回|back|cancel|create|创建/i.test(item.text)) return false;
    return item.el.id === 'identifierNext' || item.el.id === 'passwordNext' || /下一步|Next/i.test(item.text);
  });
  if (!candidates.length) return {success: false, error: 'Gmail login next button not found'};
  candidates.sort((a, b) => a.score - b.score);
  const target = candidates[0].el.closest('button,[role="button"]') || candidates[0].el;
  target.scrollIntoView({block: 'center', inline: 'center'});
  target.click();
  return {success: true, text: candidates[0].text, id: target.id || ''};
})()
""",
    )


def _press_enter(run_js_fn):
    return _run_js_dict(
        run_js_fn,
        """
(() => {
  const active = document.activeElement;
  if (!active) return {success: false, error: 'No active element for Enter key'};
  active.dispatchEvent(new KeyboardEvent('keydown', {bubbles: true, cancelable: true, key: 'Enter', code: 'Enter', keyCode: 13, which: 13}));
  active.dispatchEvent(new KeyboardEvent('keyup', {bubbles: true, cancelable: true, key: 'Enter', code: 'Enter', keyCode: 13, which: 13}));
  return {success: true};
})()
""",
    )


def _submit_login_next(run_js_fn):
    result = _click_login_next(run_js_fn)
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
  const visible = (el) => {
    const style = window.getComputedStyle(el);
    return style && style.visibility !== 'hidden' && style.display !== 'none' &&
      (el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  };
  const compact = (el) => (el.innerText || el.textContent || '').trim().replace(/\\s+/g, '');
  const bodyText = compact(document.body);
  if (!/选择您想要使用的登录方式|Choosehowyouwanttosignin/i.test(bodyText)) {
    return {success: true, skipped: true, reason: 'sign-in method prompt not present'};
  }
  const prompt = Array.from(document.querySelectorAll('h1,h2,div,span,p'))
    .filter(visible)
    .find((el) => /选择您想要使用的登录方式|Choosehowyouwanttosignin/i.test(compact(el)));
  const promptBottom = prompt ? prompt.getBoundingClientRect().bottom : 0;
  const candidates = Array.from(document.querySelectorAll(
    '[role="link"],[role="button"],button,a,li,div'
  )).filter(visible).map((el) => {
    const text = compact(el);
    const rect = el.getBoundingClientRect();
    return {el, text, rect};
  }).filter((item) => {
    if (!item.text || item.rect.top < promptBottom - 8) return false;
    if (/帮助|了解详情|取消|返回|更多|Tryanotherway|Learnmore|Help|Cancel|Back/i.test(item.text)) return false;
    return item.rect.width >= 80 && item.rect.height >= 20;
  });
  if (!candidates.length) return {success: false, error: 'Gmail sign-in method option not found'};
  candidates.sort((a, b) => a.rect.top - b.rect.top);
  const target = candidates[0].el.closest('[role="link"],[role="button"],button,a') || candidates[0].el;
  target.scrollIntoView({block: 'center', inline: 'center'});
  target.click();
  return {success: true, clicked: true, text: candidates[0].text};
})()
""",
    )


def _login_with_credentials(
    email,
    password,
    *,
    goto_fn,
    run_js_fn,
    wait_fn,
    steps,
    login_url=DEFAULT_LOGIN_URL,
    code_wait_seconds=DEFAULT_CODE_WAIT_SECONDS,
    max_wait_seconds=120,
):
    account = str(email).strip()
    secret = str(password)
    if not account or "@" not in account:
        return {"success": False, "error": "Gmail sender email is invalid"}
    if not secret:
        return {"success": False, "error": "Gmail sender password is required"}

    steps.append({"step": "navigate_gmail_login", "result": goto_fn(login_url)})
    steps.append({"step": "wait_after_login_navigation", "result": _safe_call(wait_fn, "", 2)})

    initial_state = _detect_gmail_loaded(run_js_fn)
    steps.append({"step": "detect_initial_gmail_loaded", "result": initial_state})
    if initial_state.get("logged_in"):
        return {"success": True, "already_logged_in": True, "email": account}

    email_result = _retry(
        "login_fill_email",
        lambda: _fill_login_email(run_js_fn, account),
        steps,
        wait_fn,
        attempts=8,
        interval=1,
    )
    if not email_result.get("success"):
        return {"success": False, "error": "Failed to fill Gmail login email"}

    next_email = _submit_login_next(run_js_fn)
    steps.append({"step": "login_submit_email", "result": next_email})
    if not next_email.get("success"):
        return {"success": False, "error": "Failed to submit Gmail login email"}
    steps.append({"step": "wait_after_login_email_submit", "result": _safe_call(wait_fn, "", 2)})

    password_result = _retry(
        "login_fill_password",
        lambda: _fill_login_password(run_js_fn, secret),
        steps,
        wait_fn,
        attempts=8,
        interval=1,
    )
    if not password_result.get("success"):
        return {"success": False, "error": "Failed to fill Gmail login password"}

    next_password = _submit_login_next(run_js_fn)
    steps.append({"step": "login_submit_password", "result": next_password})
    if not next_password.get("success"):
        return {"success": False, "error": "Failed to submit Gmail login password"}
    steps.append({"step": "wait_after_login_password_submit", "result": _safe_call(wait_fn, "", 2)})

    method_result = _choose_first_signin_method(run_js_fn)
    steps.append({"step": "login_choose_first_signin_method", "result": method_result})
    if not method_result.get("success"):
        return {"success": False, "error": "Failed to choose Gmail sign-in method"}
    if method_result.get("clicked"):
        steps.append({"step": "wait_after_login_signin_method", "result": _safe_call(wait_fn, "", 2)})

    steps.append(
        {
            "step": "wait_for_manual_gmail_verification_code",
            "result": _safe_call(wait_fn, "", code_wait_seconds),
        }
    )
    next_code = _submit_login_next(run_js_fn)
    steps.append({"step": "login_submit_verification_code", "result": next_code})
    if not next_code.get("success"):
        return {"success": False, "error": "Failed to submit Gmail verification code"}
    steps.append({"step": "wait_after_login_code_submit", "result": _safe_call(wait_fn, "", 3)})

    loaded = _wait_for_gmail_loaded(
        run_js_fn,
        wait_fn,
        steps,
        max_wait_seconds=max_wait_seconds,
        interval_seconds=2,
    )
    steps.append({"step": "login_verify_gmail_loaded", "result": loaded})
    if not loaded.get("success"):
        return {"success": False, "error": "Failed to verify Gmail login"}
    return {"success": True, "email": account}


def _retry(step_name, action_fn, steps, wait_fn, attempts=6, interval=1):
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
    recipient,
    subject,
    body,
    inbox_url=DEFAULT_INBOX_URL,
    *,
    sender_email=None,
    password=None,
    login_url=DEFAULT_LOGIN_URL,
    code_wait_seconds=DEFAULT_CODE_WAIT_SECONDS,
    max_wait_seconds=DEFAULT_LOGIN_WAIT_SECONDS,
    wait_interval_seconds=2,
    goto_fn=None,
    run_js_fn=None,
    wait_fn=None,
    get_url_fn=None,
    type_text_fn=None,
    press_key_fn=None,
    log_fn=None,
):
    """Send an email from Gmail after confirming the inbox is logged in."""
    if goto_fn is None:
        goto_fn = _controls.goto if _controls is not None else goto
    if run_js_fn is None:
        run_js_fn = _controls.run_js if _controls is not None else run_js
    if wait_fn is None:
        wait_fn = _controls.wait if _controls is not None else wait
    if get_url_fn is None:
        get_url_fn = _controls.get_page_url if _controls is not None else get_url
    type_text_fn = _resolve_optional_function("type_text", type_text_fn)
    press_key_fn = _resolve_optional_function("press_key", press_key_fn)

    log_fn = _resolve_log(log_fn)
    steps = []

    try:
        to_email = str(recipient).strip()
        mail_subject = str(subject).strip()
        mail_body = str(body).strip()
        if "@" not in to_email:
            raise ValueError("Gmail send requires a recipient email address")
        if not mail_subject:
            raise ValueError("Gmail send requires subject")
        if not mail_body:
            raise ValueError("Gmail send requires body")

        log_fn(f"Opening Gmail inbox: {inbox_url}")
        steps.append({"step": "navigate_gmail_inbox", "result": goto_fn(inbox_url)})
        steps.append({"step": "wait_after_navigation", "result": _safe_call(wait_fn, "", 2)})

        login_state = _detect_logged_in(run_js_fn)
        steps.append({"step": "detect_login_state", "result": login_state})
        if not login_state.get("logged_in"):
            if sender_email and password:
                log_fn("Gmail is not logged in. Logging in with provided sender account.")
                login_result = _login_with_credentials(
                    sender_email,
                    password,
                    goto_fn=goto_fn,
                    run_js_fn=run_js_fn,
                    wait_fn=wait_fn,
                    steps=steps,
                    login_url=login_url,
                    code_wait_seconds=code_wait_seconds,
                    max_wait_seconds=max_wait_seconds,
                )
                steps.append({"step": "auto_login_completion", "result": login_result})
                if not login_result.get("success"):
                    return {
                        "success": False,
                        "error": login_result.get("error") or "Failed to log in to Gmail",
                        "steps": steps,
                    }
                steps.append({"step": "navigate_gmail_inbox_after_login", "result": goto_fn(inbox_url)})
                steps.append({"step": "wait_after_inbox_after_login", "result": _safe_call(wait_fn, "", 2)})
            else:
                log_fn("Gmail is not logged in. Waiting for user to complete login.")
                login_result = _wait_for_login_completion(
                    run_js_fn,
                    wait_fn,
                    steps,
                    max_wait_seconds=max_wait_seconds,
                    interval_seconds=wait_interval_seconds,
                )
                steps.append({"step": "manual_login_completion", "result": login_result})
                if not login_result.get("success"):
                    return {
                        "success": False,
                        "error": "Failed to verify Gmail login",
                        "steps": steps,
                        "requires_manual_login": True,
                    }

        compose_result = _retry(
            "click_compose",
            lambda: _click_compose(run_js_fn),
            steps,
            wait_fn,
            attempts=5,
            interval=1,
        )
        if not compose_result.get("success"):
            return {"success": False, "error": "Failed to click Gmail Compose", "steps": steps}
        steps.append({"step": "wait_after_compose_click", "result": _safe_call(wait_fn, "", 1)})

        fullscreen_result = _retry(
            "click_compose_fullscreen",
            lambda: _click_compose_fullscreen(run_js_fn),
            steps,
            wait_fn,
            attempts=5,
            interval=1,
        )
        if not fullscreen_result.get("success"):
            return {"success": False, "error": "Failed to click Gmail compose full screen", "steps": steps}
        if fullscreen_result.get("clicked") or fullscreen_result.get("already_fullscreen"):
            steps.append({"step": "wait_after_compose_fullscreen", "result": _safe_call(wait_fn, "", 1)})

        popup_result = _retry(
            "detect_compose_popup",
            lambda: _detect_compose_popup(run_js_fn),
            steps,
            wait_fn,
            attempts=8,
            interval=1,
        )
        if not popup_result.get("success") or not popup_result.get("compose_popup"):
            return {"success": False, "error": "Failed to detect Gmail compose popup", "steps": steps}

        recipient_result = _retry(
            "fill_recipient",
            lambda: _fill_recipient(
                run_js_fn,
                to_email,
                type_text_fn=type_text_fn,
                press_key_fn=press_key_fn,
            ),
            steps,
            wait_fn,
            attempts=5,
            interval=1,
        )
        if not recipient_result.get("success"):
            return {"success": False, "error": "Failed to fill Gmail recipient", "steps": steps}

        subject_result = _retry(
            "fill_subject",
            lambda: _fill_subject(run_js_fn, mail_subject),
            steps,
            wait_fn,
            attempts=5,
            interval=1,
        )
        if not subject_result.get("success"):
            return {"success": False, "error": "Failed to fill Gmail subject", "steps": steps}

        body_result = _retry(
            "fill_body",
            lambda: _fill_body(run_js_fn, mail_body, type_text_fn=type_text_fn),
            steps,
            wait_fn,
            attempts=5,
            interval=1,
        )
        if not body_result.get("success"):
            return {"success": False, "error": "Failed to fill Gmail body", "steps": steps}

        send_result = _retry(
            "click_send",
            lambda: _click_send(run_js_fn),
            steps,
            wait_fn,
            attempts=5,
            interval=1,
        )
        if not send_result.get("success"):
            return {"success": False, "error": "Failed to click Gmail Send", "steps": steps}

        log_fn("Gmail email send action completed")
        return {
            "success": True,
            "recipient": to_email,
            "subject": mail_subject,
            "url": _safe_call(get_url_fn, ""),
            "steps": steps,
            "message": "Gmail email send action completed.",
        }
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        log_fn(f"Gmail send failed: {error}")
        return {"success": False, "error": error, "steps": steps}

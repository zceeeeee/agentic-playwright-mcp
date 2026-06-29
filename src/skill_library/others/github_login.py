"""GitHub login adapter.

This file is loaded in two ways:
- As source text inside the sandboxed ScriptEngine, where controls are injected.
- As a normal Python module in direct tests, where controls can be imported.
"""

try:
    from src.layer_2 import controls as _controls
except Exception:
    _controls = None


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


def _detect_login_status(get_url_fn, get_text_fn, run_js_fn):
    url = str(_safe_call(get_url_fn, "") or "")
    text = str(_safe_call(get_text_fn, "") or "")
    url_lower = url.lower()
    text_lower = text.lower()

    if (
        "sessions/two-factor" in url_lower
        or "two-factor authentication" in text_lower
        or "authentication code" in text_lower
    ):
        return {
            "success": False,
            "requires_2fa": True,
            "error": "GitHub requires two-factor authentication",
            "url": url,
        }

    if (
        "device verification" in text_lower
        or "verify your device" in text_lower
        or "verification code" in text_lower
    ):
        return {
            "success": False,
            "requires_verification": True,
            "error": "GitHub requires extra verification",
            "url": url,
        }

    if "captcha" in text_lower or "verify you are human" in text_lower:
        return {
            "success": False,
            "requires_verification": True,
            "error": "GitHub requires human verification",
            "url": url,
        }

    if (
        "incorrect username or password" in text_lower
        or "invalid username or password" in text_lower
        or "unable to sign in" in text_lower
    ):
        return {
            "success": False,
            "error": "GitHub rejected the username or password",
            "url": url,
        }

    logged_in = bool(
        _safe_call(
            run_js_fn,
            False,
            (
                "Boolean(document.querySelector("
                '\'meta[name="user-login"][content]:not([content=""]), '
                'a[href="/notifications"], '
                'button[aria-label*="user navigation"], '
                'summary[aria-label*="View profile"], '
                'button[data-testid="avatar-button"]\''
                "))"
            ),
        )
    )
    if logged_in:
        return {"success": True, "url": url}

    login_form_present = bool(
        _safe_call(
            run_js_fn,
            False,
            (
                "Boolean(document.querySelector("
                '\'#login_field, input[name="login"], input[type="password"]\''
                "))"
            ),
        )
    )
    if "github.com" in url_lower and not login_form_present:
        if "/login" not in url_lower and "/session" not in url_lower:
            return {"success": True, "url": url}

    return {
        "success": False,
        "error": "Unable to verify GitHub login",
        "url": url,
    }


def run(
    username,
    password,
    wait_seconds=2,
    *,
    goto_fn=None,
    smart_fill_fn=None,
    smart_click_fn=None,
    wait_for_navigation_fn=None,
    wait_fn=None,
    get_url_fn=None,
    get_text_fn=None,
    run_js_fn=None,
    save_cookies_fn=None,
    log_fn=None,
):
    """Log in to GitHub with username/password and save auth only after success."""
    if goto_fn is None:
        goto_fn = _controls.goto if _controls is not None else goto
    if smart_fill_fn is None:
        smart_fill_fn = _controls.smart_fill if _controls is not None else smart_fill
    if smart_click_fn is None:
        smart_click_fn = _controls.smart_click if _controls is not None else smart_click
    if wait_for_navigation_fn is None:
        wait_for_navigation_fn = (
            _controls.wait_for_navigation
            if _controls is not None
            else wait_for_navigation
        )
    if wait_fn is None:
        wait_fn = _controls.wait if _controls is not None else wait
    if get_url_fn is None:
        get_url_fn = _controls.get_page_url if _controls is not None else get_url
    if get_text_fn is None:
        get_text_fn = _controls.get_page_text if _controls is not None else get_text
    if run_js_fn is None:
        run_js_fn = _controls.run_js if _controls is not None else run_js
    if save_cookies_fn is None:
        save_cookies_fn = (
            _controls.save_cookies if _controls is not None else save_cookies
        )

    log_fn = _resolve_log(log_fn)
    steps = []

    try:
        nav_result = goto_fn("https://github.com/login")
        steps.append({"step": "navigate", "result": nav_result})

        initial_status = _detect_login_status(get_url_fn, get_text_fn, run_js_fn)
        if initial_status.get("success"):
            save_result = save_cookies_fn("github")
            steps.append({"step": "save_cookies", "result": save_result})
            log_fn("GitHub login already active")
            return {
                "success": True,
                "already_authenticated": True,
                "steps": steps,
                "url": initial_status.get("url", ""),
            }

        username_result = smart_fill_fn("username", username, "github")
        steps.append({"step": "fill_username", "result": username_result})
        if not username_result.get("success"):
            return {
                "success": False,
                "error": "Failed to fill GitHub username",
                "steps": steps,
            }

        password_result = smart_fill_fn("password", password, "github")
        steps.append({"step": "fill_password", "result": password_result})
        if not password_result.get("success"):
            return {
                "success": False,
                "error": "Failed to fill GitHub password",
                "steps": steps,
            }

        submit_result = smart_click_fn("submit", "github")
        steps.append({"step": "click_submit", "result": submit_result})
        if not submit_result.get("success"):
            return {
                "success": False,
                "error": "Failed to submit GitHub login form",
                "steps": steps,
            }

        wait_result = wait_for_navigation_fn()
        steps.append({"step": "wait_navigation", "result": wait_result})
        if wait_seconds:
            steps.append({"step": "wait", "result": wait_fn(wait_seconds)})

        status = _detect_login_status(get_url_fn, get_text_fn, run_js_fn)
        steps.append({"step": "verify_login", "result": status})
        if not status.get("success"):
            log_fn(f"GitHub login failed: {status.get('error', 'unknown error')}")
            failure = {"success": False, "steps": steps}
            failure.update(status)
            return failure

        save_result = save_cookies_fn("github")
        steps.append({"step": "save_cookies", "result": save_result})
        log_fn(f"GitHub login succeeded: {username}")
        return {"success": True, "steps": steps, "url": status.get("url", "")}

    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        log_fn(f"GitHub login failed: {error}")
        return {"success": False, "error": error, "steps": steps}

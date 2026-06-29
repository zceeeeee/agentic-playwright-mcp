"""Tests for the GitHub login skill adapter."""

from __future__ import annotations

from pathlib import Path

from src.core.script_engine import ScriptEngine
from src.skill_library.others.github_login import run


def _ok_step(*args):
    return {"success": True, "args": args}


def _noop(*args):
    return "ok"


def test_github_login_success_saves_cookies():
    saved = []

    result = run(
        "alice",
        "s3cr3t",
        wait_seconds=0,
        goto_fn=_noop,
        smart_fill_fn=_ok_step,
        smart_click_fn=_ok_step,
        wait_for_navigation_fn=_noop,
        wait_fn=_noop,
        get_url_fn=lambda: "https://github.com/",
        get_text_fn=lambda: "Dashboard",
        run_js_fn=lambda code: "user-login" in code,
        save_cookies_fn=lambda domain: saved.append(domain) or "saved",
        log_fn=_noop,
    )

    assert result["success"] is True
    assert saved == ["github"]


def test_github_login_invalid_password_does_not_save_cookies():
    saved = []

    result = run(
        "alice",
        "bad-password",
        wait_seconds=0,
        goto_fn=_noop,
        smart_fill_fn=_ok_step,
        smart_click_fn=_ok_step,
        wait_for_navigation_fn=_noop,
        wait_fn=_noop,
        get_url_fn=lambda: "https://github.com/session",
        get_text_fn=lambda: "Incorrect username or password.",
        run_js_fn=lambda code: False,
        save_cookies_fn=lambda domain: saved.append(domain) or "saved",
        log_fn=_noop,
    )

    assert result["success"] is False
    assert "rejected" in result["error"]
    assert saved == []


def test_github_login_reports_two_factor():
    result = run(
        "alice",
        "s3cr3t",
        wait_seconds=0,
        goto_fn=_noop,
        smart_fill_fn=_ok_step,
        smart_click_fn=_ok_step,
        wait_for_navigation_fn=_noop,
        wait_fn=_noop,
        get_url_fn=lambda: "https://github.com/sessions/two-factor",
        get_text_fn=lambda: "Two-factor authentication",
        run_js_fn=lambda code: False,
        save_cookies_fn=_noop,
        log_fn=_noop,
    )

    assert result["success"] is False
    assert result["requires_2fa"] is True


def test_github_login_source_runs_inside_script_engine():
    source = Path("src/skill_library/others/github_login.py").read_text(
        encoding="utf-8"
    )
    engine = ScriptEngine()
    engine.register_functions(
        {
            "goto": _noop,
            "smart_fill": _ok_step,
            "smart_click": _ok_step,
            "wait_for_navigation": _noop,
            "wait": _noop,
            "get_url": lambda: "https://github.com/",
            "get_text": lambda: "Dashboard",
            "run_js": lambda code: "user-login" in code,
            "save_cookies": _noop,
        }
    )

    result = engine.execute(
        source + "\nresult = run('alice', 's3cr3t', wait_seconds=0)\nprint(result)"
    )

    assert result.success is True
    assert "'success': True" in result.output

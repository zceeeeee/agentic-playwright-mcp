"""Tests for the Xiaohongshu note comment skill adapter."""

from __future__ import annotations

from pathlib import Path

import pytest
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from src.core.script_engine import ScriptEngine
from src.skill_library.comment.xiaohongshu_comment import (
    _click_send_comment,
    _detect_login_state,
    _fill_comment,
    _find_comment_input,
    run,
)


def _noop(*args):
    return "ok"


def _with_page(html, callback):
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={"width": 1200, "height": 800})
                page.set_content(html)
                return callback(page)
            finally:
                browser.close()
    except PlaywrightError as exc:
        pytest.skip(f"Playwright browser unavailable: {exc}")


def _mock_comment_run_js(comment="dwfebfer"):
    def run_js(code):
        if "PHONE_LOGIN_TEXT" in code:
            return {"success": True, "logged_in": True, "phone_login": False}
        if "fill_xiaohongshu_comment" in code:
            return {"success": True, "value": comment}
        if "Xiaohongshu comment input not found" in code:
            return {"success": True, "selector": "content-textarea"}
        if "Xiaohongshu send comment button not found" in code:
            return {"success": True, "text": "发送", "method": "click_xiaohongshu_send_comment"}
        return {"success": True}

    return run_js


def test_xiaohongshu_comment_detects_phone_login_text():
    html = """
    <body>
      <div style="width:200px;height:40px">手机号登录</div>
    </body>
    """

    def assert_page(page):
        result = _detect_login_state(lambda code: page.evaluate(code))

        assert result["success"] is True
        assert result["phone_login"] is True
        assert result["logged_in"] is False

    _with_page(html, assert_page)


def test_xiaohongshu_comment_dom_flow_fills_and_sends():
    html = """
    <body>
      <div class="engage-bar active">
        <div class="input-box">
          <div class="content-edit">
            <p id="content-textarea" contenteditable="true" class="content-input"></p>
          </div>
        </div>
        <div class="right-btn-area">
          <button class="btn submit gray" disabled>发送</button>
          <button class="btn cancel">取消</button>
        </div>
      </div>
      <div id="sent">no</div>
      <script>
        const input = document.getElementById('content-textarea');
        const submit = document.querySelector('.btn.submit');
        input.addEventListener('input', () => {
          submit.disabled = !input.textContent.trim();
          submit.classList.toggle('gray', submit.disabled);
        });
        submit.addEventListener('click', () => {
          document.getElementById('sent').textContent = input.textContent;
        });
      </script>
    </body>
    """

    def assert_page(page):
        find_result = _find_comment_input(lambda code: page.evaluate(code))
        fill_result = _fill_comment(lambda code: page.evaluate(code), "dwfebfer")
        send_result = _click_send_comment(lambda code: page.evaluate(code))

        assert find_result["success"] is True
        assert fill_result["success"] is True
        assert send_result["success"] is True
        assert page.locator("#sent").text_content() == "dwfebfer"

    _with_page(html, assert_page)


def test_xiaohongshu_comment_run_opens_url_fills_and_sends():
    urls = []
    logs = []
    result = run(
        "dwfebfer",
        note_url="https://www.xiaohongshu.com/explore/698af8b4000000001b01c20b",
        goto_fn=lambda url: urls.append(url) or "ok",
        run_js_fn=_mock_comment_run_js(),
        wait_fn=_noop,
        get_url_fn=lambda: urls[-1],
        get_text_fn=lambda: "",
        log_fn=lambda message: logs.append(message),
    )

    assert result["success"] is True
    assert urls == [
        "https://www.xiaohongshu.com/login",
        "https://www.xiaohongshu.com/explore/698af8b4000000001b01c20b",
    ]
    assert result["comment"] == "dwfebfer"
    assert "detect_login_state" in [step["step"] for step in result["steps"]]
    assert "find_comment_input" in [step["step"] for step in result["steps"]]
    assert logs[-1] == "Xiaohongshu comment sent successfully"


def test_xiaohongshu_comment_waits_for_manual_login_before_opening_note():
    urls = []
    waits = []
    login_checks = {"count": 0}

    def run_js(code):
        if "PHONE_LOGIN_TEXT" in code:
            login_checks["count"] += 1
            if login_checks["count"] <= 2:
                return {"success": True, "logged_in": False, "phone_login": True}
            return {"success": True, "logged_in": True, "phone_login": False}
        return _mock_comment_run_js()(code)

    result = run(
        "dwfebfer",
        note_url="https://www.xiaohongshu.com/explore/698af8b4000000001b01c20b",
        max_wait_seconds=4,
        goto_fn=lambda url: urls.append(url) or "ok",
        run_js_fn=run_js,
        wait_fn=lambda seconds: waits.append(seconds) or "ok",
        get_url_fn=lambda: urls[-1],
        get_text_fn=lambda: "",
        log_fn=lambda message: None,
    )

    assert result["success"] is True
    assert urls == [
        "https://www.xiaohongshu.com/login",
        "https://www.xiaohongshu.com/explore/698af8b4000000001b01c20b",
    ]
    steps = [step["step"] for step in result["steps"]]
    assert "manual_login_completion" in steps
    assert steps.index("manual_login_completion") < steps.index("navigate_note")
    assert waits[:2] == [1, 2]


def test_xiaohongshu_comment_source_runs_inside_script_engine():
    source = Path("src/skill_library/comment/xiaohongshu_comment.py").read_text(
        encoding="utf-8"
    )
    urls = []
    engine = ScriptEngine()
    engine.register_functions(
        {
            "goto": lambda url: urls.append(url) or "ok",
            "run_js": _mock_comment_run_js(),
            "wait": _noop,
            "get_url": lambda: urls[-1] if urls else "",
            "get_text": lambda: "",
        }
    )

    result = engine.execute(
        source
        + "\n\nrun('dwfebfer', note_url='https://www.xiaohongshu.com/explore/abc')"
    )

    assert result.success is True
    assert urls == ["https://www.xiaohongshu.com/login", "https://www.xiaohongshu.com/explore/abc"]

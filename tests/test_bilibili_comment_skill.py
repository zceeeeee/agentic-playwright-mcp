"""Tests for the Bilibili video comment skill adapter."""

from __future__ import annotations

from pathlib import Path

import pytest
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from src.core.script_engine import ScriptEngine
from src.skill_library.comment.bilibili_comment import (
    _click_send_comment,
    _detect_login_state,
    _fill_comment,
    _open_login_panel,
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


def _mock_comment_run_js(comment="test"):
    login_checks = {"count": 0}

    def run_js(code):
        if "logged_in:" in code:
            login_checks["count"] += 1
            if login_checks["count"] == 1:
                return {"success": True, "logged_in": False, "login_entry": True}
            return {"success": True, "logged_in": True, "header_avatar": True}
        if "Bilibili comment input not found" in code:
            return {"success": True, "found": True, "selector": "reply-box-textarea"}
        if "Comment input not found" in code:
            return {"success": True, "value": comment}
        if "Bilibili send comment button not found" in code:
            return {
                "success": True,
                "text": "发布",
                "method": "comment_box_bottom_right_publish_button",
            }
        return {"success": True}

    return run_js


def test_bilibili_comment_waits_20_seconds_after_login_before_commenting():
    urls = []
    waits = []
    logs = []

    result = run(
        "13574133406",
        "test",
        "https://www.bilibili.com/video/BV1oh7b6xE4R/",
        goto_fn=lambda url: urls.append(url) or "ok",
        run_js_fn=_mock_comment_run_js(),
        wait_fn=lambda seconds: waits.append(seconds) or "ok",
        get_url_fn=lambda: "https://www.bilibili.com/video/BV1oh7b6xE4R/",
        get_text_fn=lambda: "",
        log_fn=lambda message: logs.append(message),
    )

    assert result["success"] is True
    assert urls == ["https://www.bilibili.com/video/BV1oh7b6xE4R/"]
    assert waits == [2, 20]
    assert "manual_login_completion" in [step["step"] for step in result["steps"]]
    assert "reload_page" not in [step["step"] for step in result["steps"]]
    assert result["comment"] == "test"
    assert logs[-1] == "Bilibili comment published successfully"


def test_bilibili_comment_full_page_flow_clicks_login_code_and_comment():
    html = """
    <body style="margin:0">
      <div class="right-entry__outside"
        style="position:absolute;right:24px;top:12px;width:64px;height:64px">
        <div id="real-login" class="header-login-entry"
          style="width:54px;height:54px;border-radius:50%;background:#00aeec;color:white;
                 display:flex;align-items:center;justify-content:center;cursor:pointer">
          登录
        </div>
      </div>
      <div id="login-panel" class="bili-mini-login"
        style="display:none;margin-top:90px;width:420px">
        <div id="password-form">
          <input id="account" placeholder="请输入账号" style="width:240px;height:34px" />
        </div>
        <div id="sms-switch" role="button"
          style="width:80px;height:32px;cursor:pointer">短信登录</div>
        <div id="sms-form" style="display:none">
          <div>未注册过哔哩哔哩的手机号，我们将自动帮你注册账号</div>
          <input id="phone" type="tel" placeholder="请输入手机号"
            style="width:240px;height:34px" />
          <div style="margin-top:12px">
            <input id="code" placeholder="请输入验证码"
              style="width:200px;height:34px" />
            <button id="send-code" disabled
              style="width:110px;height:34px;color:#00a1d6">发送验证码</button>
          </div>
        </div>
      </div>
      <div id="comment-area" style="margin-top:420px;width:600px">
        <div id="comment" class="reply-box-textarea" contenteditable="true"
          data-placeholder="发一条友善的评论"
          style="width:500px;height:80px;border:1px solid #ddd"></div>
        <button id="send-comment"
          style="margin-left:420px;width:80px;height:32px;background:#00aeec;color:white">
          发布
        </button>
      </div>
      <div id="code-clicked">no</div>
      <div id="sent-comment">no</div>
      <script>
        document.getElementById('real-login').addEventListener('click', () => {
          document.getElementById('login-panel').style.display = 'block';
        });
        document.getElementById('sms-switch').addEventListener('click', () => {
          document.getElementById('password-form').style.display = 'none';
          document.getElementById('sms-form').style.display = 'block';
        });
        const phone = document.getElementById('phone');
        const codeButton = document.getElementById('send-code');
        phone.addEventListener('input', () => {
          if (phone.value.replace(/\\D/g, '').length >= 11) {
            codeButton.disabled = false;
          }
        });
        codeButton.addEventListener('click', () => {
          document.getElementById('code-clicked').textContent = 'yes';
          document.getElementById('login-panel').style.display = 'none';
          document.getElementById('real-login').style.display = 'none';
          const avatar = document.createElement('img');
          avatar.id = 'header-avatar';
          avatar.className = 'header-avatar';
          avatar.src = 'about:blank';
          avatar.style.width = '36px';
          avatar.style.height = '36px';
          document.querySelector('.right-entry__outside').appendChild(avatar);
        });
        document.getElementById('send-comment').addEventListener('click', () => {
          document.getElementById('sent-comment').textContent =
            document.getElementById('comment').innerText;
        });
      </script>
    </body>
    """

    def assert_page(page):
        waits = []
        result = run(
            "13574133406",
            "test",
            "https://www.bilibili.com/video/BV1oh7b6xE4R/",
            goto_fn=lambda url: "ok",
            run_js_fn=lambda code: page.evaluate(code),
            wait_fn=lambda seconds: waits.append(seconds) or "ok",
            get_url_fn=lambda: "https://www.bilibili.com/video/BV1oh7b6xE4R/",
            get_text_fn=lambda: page.locator("body").inner_text(),
            log_fn=_noop,
        )

        assert result["success"] is True
        assert waits == [2, 20]
        assert page.locator("#phone").input_value() == "13574133406"
        assert page.locator("#code-clicked").text_content() == "yes"
        assert page.locator("#sent-comment").text_content() == "test"

    _with_page(html, assert_page)


def test_bilibili_comment_does_not_treat_video_avatar_as_logged_in():
    html = """
    <body>
      <img class="bili-avatar" src="about:blank"
        style="position:absolute;left:100px;top:260px;width:48px;height:48px" />
    </body>
    """

    def assert_page(page):
        result = _detect_login_state(lambda code: page.evaluate(code))

        assert result["success"] is True
        assert result["logged_in"] is False
        assert result["header_avatar"] is False

    _with_page(html, assert_page)


def test_bilibili_comment_open_login_keeps_clicking_until_sms_marker():
    html = """
    <body style="margin:0">
      <div class="right-entry__outside"
        style="position:absolute;right:24px;top:12px;width:64px;height:64px">
        <div id="real-login" class="header-login-entry"
          style="width:54px;height:54px;border-radius:50%;background:#00aeec;color:white;
                 display:flex;align-items:center;justify-content:center;cursor:pointer">
          登录
        </div>
      </div>
      <div id="login-panel" class="bili-mini-login" style="display:none;margin-top:90px">
        <div id="sms-switch" role="button">短信登录</div>
      </div>
      <div id="click-count">0</div>
      <script>
        document.getElementById('real-login').addEventListener('click', () => {
          const count = Number(document.getElementById('click-count').textContent) + 1;
          document.getElementById('click-count').textContent = String(count);
          if (count >= 3) {
            document.getElementById('login-panel').style.display = 'block';
          }
        });
      </script>
    </body>
    """

    def assert_page(page):
        result = _open_login_panel(lambda code: page.evaluate(code))

        assert result["success"] is True
        assert result["marker_found"] is True
        assert result["attempts"] == 3
        assert page.locator("#click-count").text_content() == "3"

    _with_page(html, assert_page)


def test_bilibili_comment_fill_and_send_helpers():
    html = """
    <body>
      <div id="comment-wrap" style="width:600px">
        <div id="comment" class="reply-box-textarea" contenteditable="true"
          data-placeholder="发一条友善的评论"
          style="width:500px;height:80px;border:1px solid #ddd"></div>
        <button id="send-comment"
          style="margin-left:420px;width:80px;height:32px;background:#00aeec;color:white">
          发布
        </button>
      </div>
      <div id="sent-comment">no</div>
      <script>
        document.getElementById('send-comment').addEventListener('click', () => {
          document.getElementById('sent-comment').textContent =
            document.getElementById('comment').innerText;
        });
      </script>
    </body>
    """

    def assert_page(page):
        fill_result = _fill_comment(lambda code: page.evaluate(code), "test")
        send_result = _click_send_comment(lambda code: page.evaluate(code))

        assert fill_result["success"] is True
        assert send_result["success"] is True
        assert page.locator("#sent-comment").text_content() == "test"

    _with_page(html, assert_page)


def test_bilibili_comment_source_runs_inside_script_engine():
    source = Path("src/skill_library/comment/bilibili_comment.py").read_text(
        encoding="utf-8"
    )
    urls = []
    waits = []
    engine = ScriptEngine()
    engine.register_functions(
        {
            "goto": lambda url: urls.append(url) or "ok",
            "run_js": _mock_comment_run_js("test"),
            "wait": lambda seconds: waits.append(seconds) or "ok",
            "get_url": lambda: "https://www.bilibili.com/video/BV1oh7b6xE4R/",
            "get_text": lambda: "",
        }
    )

    result = engine.execute(
        source
        + "\nresult = run('13574133406', 'test', "
        + "'https://www.bilibili.com/video/BV1oh7b6xE4R/')\nprint(result)"
    )

    assert result.success is True
    assert urls == ["https://www.bilibili.com/video/BV1oh7b6xE4R/"]
    assert waits == [2, 20]
    assert "'success': True" in result.output

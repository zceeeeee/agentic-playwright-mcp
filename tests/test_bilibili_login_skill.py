"""Tests for the Bilibili SMS login skill adapter."""

from __future__ import annotations

from pathlib import Path

import pytest
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from src.core.script_engine import ScriptEngine
from src.skill_library.others.bilibili_login import (
    _click_get_code,
    _click_sms_login,
    _fill_phone,
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


def test_bilibili_login_requests_code_and_stops_for_manual_verification():
    js_calls = []

    def run_js(code):
        js_calls.append(code)
        return {"success": True}

    result = run(
        "13574133406",
        wait_seconds=0,
        goto_fn=_noop,
        run_js_fn=run_js,
        wait_fn=_noop,
        get_url_fn=lambda: "https://www.bilibili.com",
        get_text_fn=lambda: "短信登录 请输入手机号 发送验证码",
        log_fn=_noop,
    )

    assert result["success"] is True
    assert result["requires_manual_verification"] is True
    assert result["requires_manual_code"] is True
    assert result["phone_number"] == "13574133406"
    assert len(js_calls) == 4


def test_bilibili_login_normalizes_china_country_code():
    result = run(
        "+86 135-7413-3406",
        wait_seconds=0,
        goto_fn=_noop,
        run_js_fn=lambda code: {"success": True},
        wait_fn=_noop,
        get_url_fn=lambda: "https://www.bilibili.com",
        get_text_fn=lambda: "",
        log_fn=_noop,
    )

    assert result["success"] is True
    assert result["phone_number"] == "13574133406"


def test_bilibili_login_rejects_invalid_phone_number():
    result = run(
        "12345",
        wait_seconds=0,
        goto_fn=_noop,
        run_js_fn=lambda code: {"success": True},
        wait_fn=_noop,
        get_url_fn=lambda: "https://www.bilibili.com",
        get_text_fn=lambda: "",
        log_fn=_noop,
    )

    assert result["success"] is False
    assert "valid 11-digit phone number" in result["error"]


def test_bilibili_open_login_script_targets_header_login_entry():
    js_calls = []

    result = _open_login_panel(lambda code: js_calls.append(code) or {"success": True})

    assert result["success"] is True
    assert ".header-login-entry" in js_calls[0]
    assert "SMS_LOGIN_TEXT" in js_calls[0]
    assert "top_right_login_icon" in js_calls[0]


def test_bilibili_open_login_retries_until_sms_login_marker_appears():
    html = """
    <body style="margin:0">
      <input id="search" placeholder="搜索" type="text"
        style="position:absolute;left:240px;top:16px;width:300px;height:34px" />
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
          if (count >= 2) {
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
        assert result["attempts"] == 2
        assert page.locator("#click-count").text_content() == "2"
        assert page.locator("#search").input_value() == ""

    _with_page(html, assert_page)


def test_bilibili_click_sms_login_switch():
    html = """
    <body>
      <div id="login-panel" class="bili-mini-login">
        <div id="sms-switch" role="button"
          style="width:80px;height:32px;cursor:pointer">短信登录</div>
      </div>
      <script>
        document.getElementById('sms-switch').addEventListener('click', () => {
          const input = document.createElement('input');
          input.id = 'phone';
          input.type = 'tel';
          input.placeholder = '请输入手机号';
          input.style.width = '240px';
          input.style.height = '34px';
          document.getElementById('login-panel').appendChild(input);
        });
      </script>
    </body>
    """

    def assert_page(page):
        result = _click_sms_login(lambda code: page.evaluate(code))

        assert result["success"] is True
        assert result["method"] == "sms_login_switch"
        assert result["has_phone_input_after"] is True
        assert page.locator("#phone").is_visible()

    _with_page(html, assert_page)


def test_bilibili_fill_phone_does_not_use_search_input_without_login_panel():
    html = """
    <body>
      <input id="search" placeholder="搜索" type="text"
        style="width:300px;height:34px" />
    </body>
    """

    def assert_page(page):
        result = _fill_phone(lambda code: page.evaluate(code), "13574133406")

        assert result["success"] is False
        assert "login panel" in result["error"]
        assert page.locator("#search").input_value() == ""

    _with_page(html, assert_page)


def test_bilibili_fill_phone_targets_login_panel_phone_input():
    html = """
    <body>
      <input id="search" placeholder="搜索" type="text"
        style="width:300px;height:34px" />
      <div id="login-panel" class="bili-mini-login">
        <div>短信登录</div>
        <input id="phone" type="tel" placeholder="请输入手机号"
          style="width:240px;height:34px" />
      </div>
    </body>
    """

    def assert_page(page):
        result = _fill_phone(lambda code: page.evaluate(code), "13574133406")

        assert result["success"] is True
        assert page.locator("#phone").input_value() == "13574133406"
        assert page.locator("#search").input_value() == ""

    _with_page(html, assert_page)


def test_bilibili_clicks_send_code_to_the_right_of_code_input():
    html = """
    <body>
      <div id="login-panel" class="bili-mini-login" style="width:420px">
        <div>短信登录</div>
        <input id="phone" type="tel" placeholder="请输入手机号" value="13574133406"
          style="width:240px;height:34px" />
        <div style="margin-top:12px">
          <input id="code" placeholder="请输入验证码"
            style="width:200px;height:34px" />
          <button id="send-code" style="width:110px;height:34px;color:#00a1d6">
            发送验证码
          </button>
        </div>
      </div>
      <div id="code-clicked">no</div>
      <script>
        document.getElementById('send-code').addEventListener('click', () => {
          document.getElementById('code-clicked').textContent = 'yes';
        });
      </script>
    </body>
    """

    def assert_page(page):
        result = _click_get_code(lambda code: page.evaluate(code))

        assert result["success"] is True
        assert result["method"] == "code_input_right_button"
        assert result["near_code_input"] is True
        assert page.locator("#code-clicked").text_content() == "yes"

    _with_page(html, assert_page)


def test_bilibili_run_opens_sms_mode_fills_and_clicks_code():
    html = """
    <body style="margin:0">
      <input id="search" placeholder="搜索" type="text"
        style="position:absolute;left:240px;top:16px;width:300px;height:34px" />
      <div class="right-entry__outside"
        style="position:absolute;right:24px;top:12px;width:64px;height:64px">
        <div id="real-login" class="header-login-entry"
          style="width:54px;height:54px;border-radius:50%;background:#00aeec;color:white;
                 display:flex;align-items:center;justify-content:center;cursor:pointer">
          登录
        </div>
      </div>
      <div id="login-panel" class="bili-mini-login" style="display:none;margin-top:90px;width:420px">
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
      <div id="code-clicked">no</div>
      <script>
        document.getElementById('real-login').addEventListener('click', () => {
          document.getElementById('login-panel').style.display = 'block';
        });
        document.getElementById('sms-switch').addEventListener('click', () => {
          document.getElementById('password-form').style.display = 'none';
          document.getElementById('sms-form').style.display = 'block';
        });
        const phone = document.getElementById('phone');
        const button = document.getElementById('send-code');
        phone.addEventListener('input', () => {
          if (phone.value.replace(/\\D/g, '').length >= 11) {
            button.disabled = false;
          }
        });
        button.addEventListener('click', () => {
          document.getElementById('code-clicked').textContent = 'yes';
        });
      </script>
    </body>
    """

    def assert_page(page):
        result = run(
            "13574133406",
            wait_seconds=0,
            goto_fn=lambda url: "ok",
            run_js_fn=lambda code: page.evaluate(code),
            wait_fn=lambda seconds: page.wait_for_timeout(int(seconds * 1000)) or "ok",
            get_url_fn=lambda: "https://www.bilibili.com",
            get_text_fn=lambda: page.locator("body").inner_text(),
            log_fn=_noop,
        )

        assert result["success"] is True
        assert result["requires_manual_verification"] is True
        assert page.locator("#phone").input_value() == "13574133406"
        assert page.locator("#code-clicked").text_content() == "yes"
        assert page.locator("#search").input_value() == ""

    _with_page(html, assert_page)


def test_bilibili_login_source_runs_inside_script_engine():
    source = Path("src/skill_library/others/bilibili_login.py").read_text(
        encoding="utf-8"
    )
    engine = ScriptEngine()
    engine.register_functions(
        {
            "goto": _noop,
            "run_js": lambda code: {"success": True},
            "wait": _noop,
            "get_url": lambda: "https://www.bilibili.com",
            "get_text": lambda: "短信登录 请输入手机号 发送验证码",
        }
    )

    result = engine.execute(
        source + "\nresult = run('13574133406', wait_seconds=0)\nprint(result)"
    )

    assert result.success is True
    assert "'requires_manual_verification': True" in result.output

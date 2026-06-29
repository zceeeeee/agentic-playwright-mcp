"""Tests for the Gmail login skill adapter."""

from __future__ import annotations

from pathlib import Path

import pytest
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from src.core.script_engine import ScriptEngine
from src.skill_library.others.gmail_login import (
    _choose_first_signin_method,
    _detect_gmail_loaded,
    _fill_email,
    _fill_password,
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


def _mock_gmail_run_js():
    state = {"loaded_checks": 0}

    def run_js(code):
        if "logged_in:" in code and "gmail_logo:" in code:
            state["loaded_checks"] += 1
            if state["loaded_checks"] == 1:
                return {"success": True, "logged_in": False, "gmail_logo": False}
            return {"success": True, "logged_in": True, "gmail_logo": True}
        if "Gmail email input not found" in code:
            return {"success": True, "value": "che53438@gmail.com"}
        if "Gmail password input not found" in code:
            return {"success": True, "value_length": 8}
        if "Gmail next button not found" in code:
            return {"success": True, "text": "下一步"}
        if "sign-in method prompt" in code:
            return {"success": True, "clicked": True, "text": "短信验证码"}
        return {"success": True}

    return run_js


def test_gmail_login_runs_full_mocked_flow():
    urls = []
    waits = []
    logs = []

    result = run(
        "che53438@gmail.com",
        "8105432a",
        goto_fn=lambda url: urls.append(url) or "ok",
        run_js_fn=_mock_gmail_run_js(),
        wait_fn=lambda seconds: waits.append(seconds) or "ok",
        get_url_fn=lambda: "https://mail.google.com/mail/u/0/#inbox",
        get_text_fn=lambda: "Gmail",
        log_fn=lambda message: logs.append(message),
    )

    assert result["success"] is True
    assert urls == ["https://mail.google.com/mail?hl=zh-CN"]
    assert waits == [2, 2, 2, 2, 30, 3]
    assert result["email"] == "che53438@gmail.com"
    assert logs[-1] == "Gmail login succeeded"


def test_gmail_login_full_page_flow_selects_first_method_and_detects_logo():
    html = """
    <body>
      <main id="stage">
        <input id="identifierId" type="email" name="identifier" />
        <div id="identifierNext" role="button">下一步</div>
      </main>
      <script>
        const stage = document.getElementById('stage');
        let step = 'email';
        stage.addEventListener('click', (event) => {
          if (event.target.id === 'identifierNext') {
            step = 'password';
            stage.innerHTML = `
              <input id="password" type="password" name="Passwd" />
              <div id="passwordNext" role="button">下一步</div>
            `;
          } else if (event.target.id === 'passwordNext') {
            step = 'method';
            stage.innerHTML = `
              <h1>选择您想要使用的登录方式：</h1>
              <div id="method-one" role="link">短信验证码</div>
              <div id="method-two" role="link">备用邮箱</div>
            `;
          } else if (event.target.id === 'method-one') {
            step = 'code';
            stage.innerHTML = `
              <input id="code" aria-label="输入验证码" value="123456" />
              <div id="codeNext" role="button">下一步</div>
            `;
          } else if (event.target.id === 'codeNext') {
            step = 'gmail';
            stage.innerHTML = `
              <img id="gmail-logo" alt="Gmail"
                style="position:absolute;left:20px;top:20px;width:96px;height:40px" />
            `;
          }
        });
      </script>
    </body>
    """

    def assert_page(page):
        waits = []
        result = run(
            "che53438@gmail.com",
            "8105432a",
            goto_fn=lambda url: "ok",
            run_js_fn=lambda code: page.evaluate(code),
            wait_fn=lambda seconds: waits.append(seconds) or "ok",
            get_url_fn=lambda: "https://mail.google.com/mail/u/0/#inbox",
            get_text_fn=lambda: page.locator("body").inner_text(),
            log_fn=_noop,
        )

        assert result["success"] is True
        assert waits == [2, 2, 2, 2, 30, 3]
        assert page.locator("#gmail-logo").is_visible()

    _with_page(html, assert_page)


def test_gmail_login_page_logo_does_not_skip_email_input():
    html = """
    <body>
      <img alt="Gmail" style="position:absolute;left:20px;top:20px;width:96px;height:40px" />
      <main id="stage">
        <h1>登录</h1>
        <input id="identifierId" type="email" name="identifier" />
        <div id="identifierNext" role="button">下一步</div>
      </main>
    </body>
    """

    def assert_page(page):
        state = _detect_gmail_loaded(lambda code: page.evaluate(code))
        fill_result = _fill_email(
            lambda code: page.evaluate(code),
            "che53438@gmail.com",
        )

        assert state["success"] is True
        assert state["gmail_logo"] is True
        assert state["login_page"] is True
        assert state["logged_in"] is False
        assert fill_result["success"] is True
        assert page.locator("#identifierId").input_value() == "che53438@gmail.com"

    _with_page(html, assert_page)


def test_gmail_login_chooses_first_signin_method():
    html = """
    <body>
      <h1>选择您想要使用的登录方式：</h1>
      <div id="first" role="link" style="width:320px;height:48px">短信验证码</div>
      <div id="second" role="link" style="width:320px;height:48px">备用邮箱</div>
      <div id="clicked">none</div>
      <script>
        document.getElementById('first').addEventListener('click', () => {
          document.getElementById('clicked').textContent = 'first';
        });
        document.getElementById('second').addEventListener('click', () => {
          document.getElementById('clicked').textContent = 'second';
        });
      </script>
    </body>
    """

    def assert_page(page):
        result = _choose_first_signin_method(lambda code: page.evaluate(code))

        assert result["success"] is True
        assert result["clicked"] is True
        assert page.locator("#clicked").text_content() == "first"

    _with_page(html, assert_page)


def test_gmail_login_fill_helpers_and_logo_detection():
    html = """
    <body>
      <input id="identifierId" type="email" name="identifier" />
      <input id="password" type="password" name="Passwd" />
      <img alt="Gmail" style="position:absolute;left:20px;top:20px;width:96px;height:40px" />
    </body>
    """

    def assert_page(page):
        email_result = _fill_email(lambda code: page.evaluate(code), "che53438@gmail.com")
        password_result = _fill_password(lambda code: page.evaluate(code), "8105432a")
        login_page_result = _detect_gmail_loaded(lambda code: page.evaluate(code))

        assert email_result["success"] is True
        assert password_result["success"] is True
        assert login_page_result["logged_in"] is False
        assert login_page_result["login_page"] is True
        assert page.locator("#identifierId").input_value() == "che53438@gmail.com"
        assert page.locator("#password").input_value() == "8105432a"
        page.set_content(
            """
            <body>
              <img alt="Gmail"
                style="position:absolute;left:20px;top:20px;width:96px;height:40px" />
            </body>
            """
        )
        loaded_result = _detect_gmail_loaded(lambda code: page.evaluate(code))
        assert loaded_result["logged_in"] is True

    _with_page(html, assert_page)


def test_gmail_login_source_runs_inside_script_engine():
    source = Path("src/skill_library/others/gmail_login.py").read_text(
        encoding="utf-8"
    )
    urls = []
    waits = []
    engine = ScriptEngine()
    engine.register_functions(
        {
            "goto": lambda url: urls.append(url) or "ok",
            "run_js": _mock_gmail_run_js(),
            "wait": lambda seconds: waits.append(seconds) or "ok",
            "get_url": lambda: "https://mail.google.com/mail/u/0/#inbox",
            "get_text": lambda: "Gmail",
        }
    )

    result = engine.execute(
        source
        + "\nresult = run('che53438@gmail.com', '8105432a')\nprint(result)"
    )

    assert result.success is True
    assert urls == ["https://mail.google.com/mail?hl=zh-CN"]
    assert waits == [2, 2, 2, 2, 30, 3]
    assert "'success': True" in result.output

"""Tests for the Gmail send skill adapter."""

from __future__ import annotations

from pathlib import Path

import pytest
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from src.core.script_engine import ScriptEngine
from src.skill_library.send.gmail_send import (
    _detect_logged_in,
    _fill_body,
    _fill_recipient,
    _fill_subject,
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


def _mock_gmail_send_run_js(login_checks_before_success=0):
    state = {"login_checks": 0}

    def run_js(code):
        if "search_mail:" in code and "logged_in:" in code:
            state["login_checks"] += 1
            return {
                "success": True,
                "logged_in": state["login_checks"] > login_checks_before_success,
                "search_mail": state["login_checks"] > login_checks_before_success,
            }
        if "Gmail compose button not found" in code:
            return {"success": True, "text": "Compose"}
        if "Gmail compose full screen button not found" in code:
            return {"success": True, "clicked": True, "text": "Full screen"}
        if "compose_popup:" in code:
            return {
                "success": True,
                "compose_popup": True,
                "popup": True,
                "has_new_message": True,
            }
        if "Gmail recipient input not found" in code:
            return {"success": True, "value": "alice@example.com"}
        if "Gmail subject input not found" in code:
            return {"success": True, "value": "Test subject", "name": "subjectbox"}
        if "Gmail body editor not found" in code:
            return {"success": True, "text": "Test body"}
        if "Gmail send button not found" in code:
            return {"success": True, "text": "Send"}
        return {"success": True}

    return run_js


def _mock_gmail_send_run_js_with_login():
    state = {"next_clicks": 0}

    def run_js(code):
        if "gmail_logo:" in code and "logged_in:" in code:
            logged_in = state["next_clicks"] >= 3
            return {"success": True, "logged_in": logged_in, "gmail_logo": logged_in}
        if "search_mail:" in code and "logged_in:" in code:
            logged_in = state["next_clicks"] >= 3
            return {"success": True, "logged_in": logged_in, "search_mail": logged_in}
        if "Gmail login email input not found" in code:
            return {"success": True, "value": "sender@example.com"}
        if "Gmail login password input not found" in code:
            return {"success": True, "value_length": 8}
        if "Gmail login next button not found" in code:
            state["next_clicks"] += 1
            return {"success": True, "text": "Next"}
        if "Gmail sign-in method option not found" in code:
            return {"success": True, "clicked": True, "text": "Text message"}
        if "Gmail compose button not found" in code:
            return {"success": True, "text": "Compose"}
        if "Gmail compose full screen button not found" in code:
            return {"success": True, "clicked": True, "text": "Full screen"}
        if "compose_popup:" in code:
            return {"success": True, "compose_popup": True, "popup": True}
        if "Gmail recipient input not found" in code:
            return {"success": True, "value": "alice@example.com"}
        if "Gmail subject input not found" in code:
            return {"success": True, "value": "Test subject", "name": "subjectbox"}
        if "Gmail body editor not found" in code:
            return {"success": True, "text": "Test body"}
        if "Gmail send button not found" in code:
            return {"success": True, "text": "Send"}
        return {"success": True}

    return run_js


def test_gmail_send_waits_for_manual_login_then_sends():
    urls = []
    waits = []
    logs = []

    result = run(
        "alice@example.com",
        "Test subject",
        "Test body",
        goto_fn=lambda url: urls.append(url) or "ok",
        run_js_fn=_mock_gmail_send_run_js(login_checks_before_success=2),
        wait_fn=lambda seconds: waits.append(seconds) or "ok",
        get_url_fn=lambda: "https://mail.google.com/mail/u/0/#inbox",
        log_fn=lambda message: logs.append(message),
        max_wait_seconds=4,
        wait_interval_seconds=2,
    )

    assert result["success"] is True
    assert urls == ["https://mail.google.com/mail/u/0/#inbox"]
    assert waits == [2, 2, 1, 1]
    assert any(step["step"] == "manual_login_completion" for step in result["steps"])
    assert logs[-1] == "Gmail email send action completed"


def test_gmail_send_auto_logs_in_with_sender_account_then_sends():
    urls = []
    waits = []

    result = run(
        "alice@example.com",
        "Test subject",
        "Test body",
        sender_email="sender@example.com",
        password="8105432a",
        goto_fn=lambda url: urls.append(url) or "ok",
        run_js_fn=_mock_gmail_send_run_js_with_login(),
        wait_fn=lambda seconds: waits.append(seconds) or "ok",
        get_url_fn=lambda: "https://mail.google.com/mail/u/0/#inbox",
        log_fn=_noop,
    )

    assert result["success"] is True
    assert urls == [
        "https://mail.google.com/mail/u/0/#inbox",
        "https://mail.google.com/mail?hl=zh-CN",
        "https://mail.google.com/mail/u/0/#inbox",
    ]
    step_names = [step["step"] for step in result["steps"]]
    assert "auto_login_completion" in step_names
    assert "click_compose_fullscreen" in step_names
    assert "fill_recipient" in step_names


def test_gmail_send_logged_in_mocked_flow():
    urls = []
    waits = []

    result = run(
        "alice@example.com",
        "Test subject",
        "Test body",
        goto_fn=lambda url: urls.append(url) or "ok",
        run_js_fn=_mock_gmail_send_run_js(login_checks_before_success=0),
        wait_fn=lambda seconds: waits.append(seconds) or "ok",
        get_url_fn=lambda: "https://mail.google.com/mail/u/0/#inbox",
        log_fn=_noop,
    )

    assert result["success"] is True
    assert urls == ["https://mail.google.com/mail/u/0/#inbox"]
    step_names = [step["step"] for step in result["steps"]]
    assert "detect_login_state" in step_names
    assert "click_compose" in step_names
    assert "click_compose_fullscreen" in step_names
    assert "detect_compose_popup" in step_names
    assert "fill_recipient" in step_names
    assert "fill_subject" in step_names
    assert "fill_body" in step_names
    assert "click_send" in step_names


def test_gmail_send_full_page_flow_fills_and_sends():
    html = """
    <body>
      <input aria-label="Search mail" placeholder="Search mail" name="q" />
      <div class="z0">
        <div id="compose" class="T-I T-I-KE L3" role="button" gh="cm">Compose</div>
      </div>
      <div id="compose-window" style="display:none">
        <div class="Hp"><h2 class="a3E"><div class="a3I">Compose:</div><span>New Message</span></h2></div>
        <td class="Hm">
          <img id="fullscreen" class="Hq aUG" role="button" alt="Pop-out"
               aria-label="Full screen (Shift for pop-out)"
               data-tooltip="Full screen (Shift for pop-out)"
               style="width:16px;height:16px;display:inline-block" />
        </td>
        <input id="to" class="agP aFw" aria-label="To recipients" role="combobox" />
        <input id="subject" name="subjectbox" aria-label="Subject" />
        <div id="body" aria-label="Message Body" role="textbox" contenteditable="true"></div>
        <div id="send" class="T-I J-J5-Ji aoO v7 T-I-atl L3" role="button"
             aria-label="Send ‪(Ctrl-Enter)‬" data-tooltip="Send ‪(Ctrl-Enter)‬">Send</div>
      </div>
      <div id="sent">no</div>
      <div id="fullscreen-clicked">no</div>
      <script>
        document.getElementById('compose').addEventListener('click', () => {
          document.getElementById('compose-window').style.display = 'block';
        });
        document.getElementById('fullscreen').addEventListener('click', () => {
          document.getElementById('fullscreen-clicked').textContent = 'yes';
        });
        document.getElementById('send').addEventListener('click', () => {
          document.getElementById('sent').textContent = 'yes';
        });
      </script>
    </body>
    """

    def assert_page(page):
        result = run(
            "alice@example.com",
            "Test subject",
            "Test body",
            goto_fn=lambda url: "ok",
            run_js_fn=lambda code: page.evaluate(code),
            wait_fn=lambda seconds: "ok",
            get_url_fn=lambda: "https://mail.google.com/mail/u/0/#inbox",
            log_fn=_noop,
        )

        assert result["success"] is True
        assert page.locator("#to").input_value() == "alice@example.com"
        assert page.locator("#subject").input_value() == "Test subject"
        assert page.locator("#body").inner_text() == "Test body"
        assert page.locator("#fullscreen-clicked").inner_text() == "yes"
        assert page.locator("#sent").inner_text() == "yes"

    _with_page(html, assert_page)


def test_gmail_send_waits_for_fullscreen_icon_before_filling():
    html = """
    <body>
      <input aria-label="Search mail" placeholder="Search mail" name="q" />
      <div id="compose" class="T-I T-I-KE L3" role="button" gh="cm">Compose</div>
      <div id="compose-window" style="display:none">
        <div class="Hp"><h2 class="a3E"><div class="a3I">Compose:</div><span>New Message</span></h2></div>
        <div id="window-controls" class="Hm"></div>
        <input id="to" class="agP aFw" aria-label="To recipients" role="combobox" />
        <input id="subject" name="subjectbox" aria-label="Subject" />
        <div id="body" aria-label="Message Body" role="textbox" contenteditable="true"></div>
        <div id="send" class="T-I J-J5-Ji aoO v7 T-I-atl L3" role="button"
             aria-label="Send ‪(Ctrl-Enter)‬" data-tooltip="Send ‪(Ctrl-Enter)‬">Send</div>
      </div>
      <div id="fullscreen-clicked">no</div>
      <div id="sent">no</div>
      <script>
        document.getElementById('compose').addEventListener('click', () => {
          document.getElementById('compose-window').style.display = 'block';
        });
        window.addFullscreenButton = () => {
          if (document.getElementById('fullscreen')) return;
          const img = document.createElement('img');
          img.id = 'fullscreen';
          img.className = 'Hq aUG';
          img.setAttribute('role', 'button');
          img.setAttribute('alt', 'Pop-out');
          img.setAttribute('aria-label', 'Full screen (Shift for pop-out)');
          img.setAttribute('data-tooltip', 'Full screen (Shift for pop-out)');
          img.style.cssText = 'width:16px;height:16px;display:inline-block';
          img.addEventListener('click', () => {
            document.getElementById('fullscreen-clicked').textContent = 'yes';
          });
          document.getElementById('window-controls').appendChild(img);
        };
        document.getElementById('send').addEventListener('click', () => {
          document.getElementById('sent').textContent = 'yes';
        });
      </script>
    </body>
    """

    def assert_page(page):
        waits = []

        def wait_and_add_fullscreen(seconds):
            waits.append(seconds)
            if len(waits) == 3:
                page.evaluate("window.addFullscreenButton()")
            return "ok"

        result = run(
            "alice@example.com",
            "Test subject",
            "Test body",
            goto_fn=lambda url: "ok",
            run_js_fn=lambda code: page.evaluate(code),
            wait_fn=wait_and_add_fullscreen,
            get_url_fn=lambda: "https://mail.google.com/mail/u/0/#inbox",
            log_fn=_noop,
        )

        assert result["success"] is True
        assert page.locator("#fullscreen-clicked").inner_text() == "yes"
        assert page.locator("#to").input_value() == "alice@example.com"
        assert page.locator("#subject").input_value() == "Test subject"
        assert page.locator("#body").inner_text() == "Test body"
        assert page.locator("#sent").inner_text() == "yes"
        step_names = [step["step"] for step in result["steps"]]
        assert "click_compose_fullscreen_attempt_2" in step_names

    _with_page(html, assert_page)


def test_gmail_send_fill_helpers_and_login_detection():
    html = """
    <body>
      <input aria-label="Search mail" placeholder="Search mail" name="q" />
      <input id="to" class="agP aFw" aria-label="To recipients" role="combobox" />
      <input id="subject" name="subjectbox" aria-label="Subject" />
      <div id="body" aria-label="Message Body" role="textbox" contenteditable="true"></div>
    </body>
    """

    def assert_page(page):
        assert _detect_logged_in(lambda code: page.evaluate(code))["logged_in"] is True
        assert _fill_recipient(lambda code: page.evaluate(code), "alice@example.com")["success"] is True
        assert _fill_subject(lambda code: page.evaluate(code), "Test subject")["success"] is True
        assert _fill_body(lambda code: page.evaluate(code), "Test body")["success"] is True
        assert page.locator("#to").input_value() == "alice@example.com"
        assert page.locator("#subject").input_value() == "Test subject"
        assert page.locator("#body").inner_text() == "Test body"

    _with_page(html, assert_page)


def test_gmail_send_handles_chinese_compose_fields_with_zero_width_recipient():
    html = """
    <body>
      <input aria-label="Search mail" placeholder="Search mail" name="q" />
      <div id="compose-window">
        <div class="Hp"><h2 class="a3E"><div class="a3I">撰写</div><span>新邮件</span></h2></div>
        <div class="aH9" style="height:36px">
          <input id="to" class="agP aFw" aria-label="收件人" role="combobox"
                 style="width:0;height:0;border:0;padding:0" />
        </div>
        <input id="subject" class="aoT" name="subjectbox" aria-label="主题" />
        <div id="body" aria-label="邮件正文" role="textbox" contenteditable="true"></div>
      </div>
    </body>
    """

    def assert_page(page):
        assert _fill_recipient(lambda code: page.evaluate(code), "alice@example.com")["success"] is True
        assert _fill_subject(lambda code: page.evaluate(code), "测试标题")["success"] is True
        assert _fill_body(lambda code: page.evaluate(code), "测试正文")["success"] is True
        assert page.locator("#to").input_value() == "alice@example.com"
        assert page.locator("#subject").input_value() == "测试标题"
        assert page.locator("#body").inner_text() == "测试正文"

    _with_page(html, assert_page)


def test_gmail_send_fills_gmail_message_body_editable_div():
    html = """
    <body>
      <div id=":sw" class="Am aiL Al editable LW-avf tS-tW" hidefocus="true"
           aria-label="Message Body" writingsuggestions="false" g_editable="true"
           role="textbox" aria-multiline="true" contenteditable="true" tabindex="1"
           style="direction: ltr; min-height: 266px;" spellcheck="false"><br></div>
    </body>
    """

    def assert_page(page):
        result = _fill_body(
            lambda code: page.evaluate(code),
            "测试邮件内容",
            type_text_fn=lambda text: page.keyboard.type(text) or {"success": True},
        )

        assert result["success"] is True
        assert page.locator("[aria-label='Message Body']").inner_text() == "测试邮件内容"

    _with_page(html, assert_page)


def test_gmail_send_recipient_does_not_fill_search_combobox():
    html = """
    <body>
      <input id="search" aria-label="Search mail" placeholder="Search mail" name="q"
             role="combobox" />
      <table><tbody><tr>
        <td class="eV">
          <div class="oj">
            <div class="wO nr l1">
              <div id="to-row" name="to" class="anm" aria-label="To" style="width:408px">
                <div class="aH9" style="height:36px; flex-basis:48px;" role="presentation">
                  <input id="to" class="agP aFw" autocomplete="off" spellcheck="false"
                         aria-label="To recipients" size="0" type="text" role="combobox" />
                  <span class="aIa aFw"></span>
                </div>
              </div>
            </div>
          </div>
        </td>
      </tr></tbody></table>
    </body>
    """

    def assert_page(page):
        assert _fill_recipient(lambda code: page.evaluate(code), "alice@example.com")["success"] is True
        assert page.locator("#search").input_value() == ""
        assert page.locator("#to").input_value() == "alice@example.com"

    _with_page(html, assert_page)


def test_gmail_send_clicks_recipients_row_before_filling_to_input():
    html = """
    <body>
      <div id="recipient-row" class="aoD hl" tabindex="1" style="background-color: transparent;">
        <div class="oL aDm">Recipients</div>
        <div class="bgW"></div>
      </div>
      <div id="input-host"></div>
      <script>
        document.getElementById('recipient-row').addEventListener('click', () => {
          if (!document.getElementById('to')) {
            document.getElementById('input-host').innerHTML = `
              <div name="to" aria-label="To">
                <input id="to" class="agP aFw" aria-label="To recipients"
                       size="0" type="text" role="combobox" />
              </div>
            `;
          }
        });
      </script>
    </body>
    """

    def assert_page(page):
        assert _fill_recipient(lambda code: page.evaluate(code), "alice@example.com")["success"] is True
        assert page.locator("#to").input_value() == "alice@example.com"

    _with_page(html, assert_page)


def test_gmail_send_types_into_active_recipients_row_when_no_input_appears():
    html = """
    <body>
      <div id="recipient-row" class="aoD hl" tabindex="1" style="background-color: transparent;">
        <div class="oL aDm">Recipients</div>
        <div class="bgW"></div>
      </div>
      <script>
        document.getElementById('recipient-row').addEventListener('click', () => {
          document.getElementById('recipient-row').focus();
          document.querySelector('.oL').textContent = 'To';
        });
      </script>
    </body>
    """

    def assert_page(page):
        typed = []

        def type_text(value):
            typed.append(value)
            page.evaluate(
                """value => {
                  document.getElementById('recipient-row').insertAdjacentHTML(
                    'beforeend',
                    `<div class="aQ2">${value}</div>`
                  );
                }""",
                value,
            )
            return {"success": True}

        result = _fill_recipient(
            lambda code: page.evaluate(code),
            "alice@example.com",
            type_text_fn=type_text,
            press_key_fn=lambda key: {"success": True, "key": key},
        )

        assert result["success"] is True
        assert typed == ["alice@example.com"]
        assert page.locator(".aQ2").inner_text() == "alice@example.com"

    _with_page(html, assert_page)


def test_gmail_send_source_runs_inside_script_engine():
    source = Path("src/skill_library/send/gmail_send.py").read_text(encoding="utf-8")
    urls = []
    waits = []
    engine = ScriptEngine()
    engine.register_functions(
        {
            "goto": lambda url: urls.append(url) or "ok",
            "run_js": _mock_gmail_send_run_js(login_checks_before_success=0),
            "wait": lambda seconds: waits.append(seconds) or "ok",
            "get_url": lambda: "https://mail.google.com/mail/u/0/#inbox",
        }
    )

    result = engine.execute(
        source
        + "\nresult = run('alice@example.com', 'Test subject', 'Test body')\nprint(result)"
    )

    assert result.success is True
    assert urls == ["https://mail.google.com/mail/u/0/#inbox"]
    assert waits == [2, 1, 1]
    assert "'success': True" in result.output

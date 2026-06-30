"""Tests for the Xiaohongshu publish skill adapter."""

from __future__ import annotations

from pathlib import Path

import pytest
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from src.core.script_engine import ScriptEngine
from src.skill_library.send.xiaohongshu_publish import (
    DEFAULT_ARTICLE_PUBLISH_URL,
    DEFAULT_IMAGE_PUBLISH_URL,
    DEFAULT_VIDEO_PUBLISH_URL,
    _click_final_publish,
    _click_format_button,
    _click_generate_image,
    _click_new_creation,
    _click_next_step,
    _click_text_to_image,
    _click_upload_image,
    _click_upload_video,
    _detect_image_edit,
    _detect_preview_image,
    _fill_article_content,
    _fill_publish_content,
    _fill_title,
    _normalize_publish_mode,
    _publish_url_for_mode,
    _upload_local_file,
    _upload_video_file,
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


def _mock_publish_run_js(logged_in=True):
    def run_js(code):
        if "phone_login:" in code:
            return {
                "success": True,
                "logged_in": logged_in,
                "phone_login": not logged_in,
            }
        if "ME_BUTTON_TEXT" in code:
            return {
                "success": True,
                "me_button": True,
                "method": "bottom_me_button",
            }
        if "Phone input not found" in code:
            return {"success": True, "value": "13574133406"}
        if "Agreement checkbox not found" in code:
            return {"success": True, "checked": True}
        if "Get-code button not found" in code:
            return {"success": True, "text": "获取验证码"}
        if "ABOUT_US_TEXT" in code:
            return {"success": True, "about_us": True, "lower_left": True}
        if "TEXT_TO_IMAGE_TEXT" in code:
            return {
                "success": True,
                "text": "文字配图",
                "method": "click_text_to_image",
            }
        if "UPLOAD_IMAGE_TEXT" in code:
            return {"success": True, "text": "上传图片", "method": "upload_image_button"}
        if "UPLOAD_VIDEO_TEXT" in code:
            return {"success": True, "text": "上传视频", "method": "upload_video_button"}
        if 'const KIND = "image"' in code or 'const KIND = "video"' in code:
            if 'const KIND = "image"' in code:
                return {
                    "success": True,
                    "selector": 'input[type="file"][data-codex-upload-target="image"]',
                    "accept": "image/*",
                }
            return {
                "success": True,
                "selector": 'input[type="file"][data-codex-upload-target="video"]',
                "accept": "video/*",
            }
        if "NEW_CREATION_TEXT" in code:
            return {"success": True, "text": "新的创作", "method": "new_creation_button"}
        if "FORMAT_TEXT" in code:
            return {"success": True, "text": "一键排版", "method": "format_button"}
        if "title_value" in code:
            return {"success": True, "title_value": "测试标题"}
        if "content_value" in code:
            return {"success": True, "content_value": "测试内容"}
        if "GENERATE_IMAGE_TEXT" in code:
            return {
                "success": True,
                "text": "生成图片",
                "method": "lower_generate_image_button",
            }
        if "PREVIEW_IMAGE_TEXT" in code:
            return {"success": True, "preview_image": True, "top_left": True}
        if "NEXT_STEP_TEXT" in code:
            return {
                "success": True,
                "text": "下一步",
                "method": "lower_left_next_step",
            }
        if "IMAGE_EDIT_TEXT" in code:
            return {"success": True, "image_edit": True, "top": True}
        if "FINAL_PUBLISH_TEXT" in code:
            return {
                "success": True,
                "text": "发布",
                "method": "lower_publish_button",
            }
        return {"success": True}

    return run_js


class TestNormalizePublishMode:
    def test_text_to_image_by_default(self):
        assert _normalize_publish_mode(None, None, None, None) == "text_to_image"
        assert _normalize_publish_mode(None, None, None, "target=image") == "text_to_image"

    def test_article_mode_for_long_article_keywords(self):
        assert _normalize_publish_mode("article", None, None, None) == "article"
        assert _normalize_publish_mode("long_text", None, None, None) == "article"
        assert _normalize_publish_mode("novel", None, None, None) == "article"
        assert _normalize_publish_mode(None, None, None, "target=article") == "article"

    def test_video_mode_for_video_keywords(self):
        assert _normalize_publish_mode("video", None, None, None) == "video"
        assert _normalize_publish_mode(None, None, "D:/video.mp4", None) == "video"
        assert _normalize_publish_mode(None, None, None, "target=video") == "video"

    def test_image_upload_mode_for_upload_keywords(self):
        assert _normalize_publish_mode("image_upload", None, None, None) == "image_upload"
        assert _normalize_publish_mode("upload", None, None, None) == "image_upload"
        assert _normalize_publish_mode(None, "D:/image.jpg", None, None) == "image_upload"


class TestPublishUrlForMode:
    def test_article_url_for_article_mode(self):
        url = _publish_url_for_mode("article", DEFAULT_IMAGE_PUBLISH_URL)
        assert url == DEFAULT_ARTICLE_PUBLISH_URL

    def test_video_url_for_video_mode(self):
        url = _publish_url_for_mode("video", DEFAULT_IMAGE_PUBLISH_URL)
        assert url == DEFAULT_VIDEO_PUBLISH_URL

    def test_image_url_for_text_to_image_mode(self):
        url = _publish_url_for_mode("text_to_image", DEFAULT_IMAGE_PUBLISH_URL)
        assert url == DEFAULT_IMAGE_PUBLISH_URL

    def test_custom_url_is_preserved(self):
        custom_url = "https://example.com/custom"
        url = _publish_url_for_mode("article", custom_url)
        assert url == custom_url


def test_xiaohongshu_publish_runs_when_already_logged_in():
    urls = []
    logs = []

    result = run(
        keyword="测试图文内容",
        max_wait_seconds=0,
        goto_fn=lambda url: urls.append(url) or "ok",
        run_js_fn=_mock_publish_run_js(logged_in=True),
        wait_fn=_noop,
        get_url_fn=lambda: "https://creator.xiaohongshu.com/publish/publish",
        get_text_fn=lambda: "",
        log_fn=lambda message: logs.append(message),
    )

    assert result["success"] is True
    assert urls == [
        "https://www.xiaohongshu.com/login",
        "https://creator.xiaohongshu.com/publish/publish?source=official&from=tab_switch&target=image",
    ]
    assert result["content"] == "测试图文内容"
    assert logs == ["Xiaohongshu publish button clicked"]


def test_xiaohongshu_publish_requests_code_and_waits_for_about_us():
    urls = []
    waits = []
    logs = []

    result = run(
        keyword="测试图文内容",
        phone_number="13574133406",
        max_wait_seconds=0,
        goto_fn=lambda url: urls.append(url) or "ok",
        run_js_fn=_mock_publish_run_js(logged_in=False),
        wait_fn=lambda seconds: waits.append(seconds) or "ok",
        get_url_fn=lambda: "https://www.xiaohongshu.com/explore",
        get_text_fn=lambda: "",
        log_fn=lambda message: logs.append(message),
    )

    assert result["success"] is True
    assert result["phone_number"] == "13574133406"
    assert urls[-1] == (
        "https://creator.xiaohongshu.com/publish/publish"
        "?source=official&from=tab_switch&target=image"
    )
    steps = [step["step"] for step in result["steps"]]
    assert "click_text_to_image" in steps
    assert "fill_publish_content" in steps
    assert steps.index("click_text_to_image") < steps.index("fill_publish_content")
    assert "wait_after_fill_publish_content" in steps
    assert "click_generate_image" in steps
    assert "detect_preview_image" in steps
    assert "click_next_step" in steps
    assert "detect_image_edit" in steps
    assert "click_final_publish" in steps
    assert steps.index("wait_after_fill_publish_content") > steps.index("fill_publish_content")
    assert steps.index("click_generate_image") > steps.index("wait_after_fill_publish_content")
    assert steps.index("detect_preview_image") > steps.index("click_generate_image")
    assert steps.index("click_next_step") > steps.index("detect_preview_image")
    assert steps.index("detect_image_edit") > steps.index("click_next_step")
    assert steps.index("click_final_publish") > steps.index("detect_image_edit")
    assert "fill_phone" in steps
    assert "accept_agreement" in steps
    assert "click_get_code" in steps
    assert any(step.startswith("wait_about_us_attempt_") for step in steps)
    assert logs[0] == "Please enter the Xiaohongshu SMS verification code in the browser."
    assert logs[-1] == "Xiaohongshu publish button clicked"


def test_xiaohongshu_publish_without_phone_waits_for_existing_login():
    result = run(
        keyword="测试图文内容",
        max_wait_seconds=0,
        goto_fn=_noop,
        run_js_fn=_mock_publish_run_js(logged_in=False),
        wait_fn=_noop,
        get_url_fn=lambda: "https://www.xiaohongshu.com/login",
        get_text_fn=lambda: "",
        log_fn=lambda message: None,
    )

    assert result["success"] is True
    steps = [step["step"] for step in result["steps"]]
    assert "fill_phone" not in steps
    assert "click_get_code" not in steps
    assert "login_me_button_confirmation" in steps


def test_xiaohongshu_publish_image_upload_mode():
    urls = []
    uploads = []

    result = run(
        keyword="图片正文",
        mode="image_upload",
        image_path=r"D:\notes\cover.jpg",
        title="图片标题",
        max_wait_seconds=0,
        goto_fn=lambda url: urls.append(url) or "ok",
        run_js_fn=_mock_publish_run_js(logged_in=True),
        wait_fn=_noop,
        upload_file_fn=lambda selector, path: uploads.append((selector, path))
        or {"success": True, "selector": selector, "file_path": path},
        get_url_fn=lambda: "https://creator.xiaohongshu.com/publish/publish",
        get_text_fn=lambda: "",
        log_fn=lambda message: None,
    )

    assert result["success"] is True
    assert result["mode"] == "image_upload"
    assert "target=image" in urls[-1]
    steps = [step["step"] for step in result["steps"]]
    assert "click_upload_image" in steps
    assert "upload_local_image" in steps
    assert uploads == [
        ('input[type="file"][data-codex-upload-target="image"]', r"D:\notes\cover.jpg")
    ]
    assert "click_text_to_image" not in steps
    assert "click_generate_image" not in steps
    assert "click_final_publish" in steps


def test_xiaohongshu_publish_image_upload_fails_when_file_upload_fails():
    result = run(
        keyword="图片正文",
        mode="image_upload",
        image_path=r"D:\notes\missing.jpg",
        max_wait_seconds=0,
        goto_fn=_noop,
        run_js_fn=_mock_publish_run_js(logged_in=True),
        wait_fn=_noop,
        upload_file_fn=lambda selector, path: {
            "success": False,
            "selector": selector,
            "file_path": path,
            "error": "File not found",
        },
        get_url_fn=lambda: "https://creator.xiaohongshu.com/publish/publish",
        get_text_fn=lambda: "",
        log_fn=lambda message: None,
    )

    assert result["success"] is False
    assert result["error"] == "Failed to upload Xiaohongshu image file"
    steps = [step["step"] for step in result["steps"]]
    assert "upload_local_image" in steps
    assert "upload_local_image_dialog" not in steps
    assert "click_final_publish" not in steps


def test_xiaohongshu_publish_video_mode():
    urls = []
    uploads = []
    waits = []

    result = run(
        keyword="视频正文",
        mode="video",
        video_path=r"D:\notes\clip.mp4",
        title="视频标题",
        max_wait_seconds=0,
        goto_fn=lambda url: urls.append(url) or "ok",
        run_js_fn=_mock_publish_run_js(logged_in=True),
        wait_fn=lambda seconds: waits.append(seconds) or "ok",
        upload_file_fn=lambda selector, path: uploads.append((selector, path))
        or {"success": True, "selector": selector, "file_path": path},
        get_url_fn=lambda: "https://creator.xiaohongshu.com/publish/publish",
        get_text_fn=lambda: "",
        log_fn=lambda message: None,
    )

    assert result["success"] is True
    assert result["mode"] == "video"
    assert "target=video" in urls[-1]
    steps = [step["step"] for step in result["steps"]]
    assert "click_upload_video" in steps
    assert "upload_local_video" in steps
    assert uploads == [
        ('input[type="file"][data-codex-upload-target="video"]', r"D:\notes\clip.mp4")
    ]
    assert "wait_for_video_upload" in steps
    assert 10 in waits
    assert steps.index("wait_for_video_upload") < steps.index("click_final_publish")


def test_xiaohongshu_publish_video_upload_fails_when_file_upload_fails():
    result = run(
        keyword="视频正文",
        mode="video",
        video_path=r"D:\notes\missing.mp4",
        max_wait_seconds=0,
        goto_fn=_noop,
        run_js_fn=_mock_publish_run_js(logged_in=True),
        wait_fn=_noop,
        upload_file_fn=lambda selector, path: {
            "success": False,
            "selector": selector,
            "file_path": path,
            "error": "File not found",
        },
        get_url_fn=lambda: "https://creator.xiaohongshu.com/publish/publish",
        get_text_fn=lambda: "",
        log_fn=lambda message: None,
    )

    assert result["success"] is False
    assert result["error"] == "Failed to upload Xiaohongshu video file"
    steps = [step["step"] for step in result["steps"]]
    assert "upload_local_video" in steps
    assert "upload_local_video_dialog" not in steps
    assert "click_final_publish" not in steps


def test_xiaohongshu_publish_article_mode():
    urls = []
    waits = []

    result = run(
        keyword="长文正文",
        mode="article",
        max_wait_seconds=0,
        goto_fn=lambda url: urls.append(url) or "ok",
        run_js_fn=_mock_publish_run_js(logged_in=True),
        wait_fn=lambda seconds: waits.append(seconds) or "ok",
        get_url_fn=lambda: "https://creator.xiaohongshu.com/publish/publish",
        get_text_fn=lambda: "",
        log_fn=lambda message: None,
    )

    assert result["success"] is True
    assert result["mode"] == "article"
    assert "target=article" in urls[-1]
    steps = [step["step"] for step in result["steps"]]
    assert "click_new_creation" in steps
    assert "fill_article_title" in steps
    assert "fill_article_content" in steps
    assert "click_format_button" in steps
    assert "wait_before_publish_article" in steps
    assert 10 in waits
    assert steps.index("wait_before_publish_article") < steps.index("click_final_publish")


def test_xiaohongshu_publish_article_with_title():
    urls = []
    steps_data = []

    result = run(
        keyword="长文正文",
        mode="article",
        title="用户自定义标题",
        max_wait_seconds=0,
        goto_fn=lambda url: urls.append(url) or "ok",
        run_js_fn=_mock_publish_run_js(logged_in=True),
        wait_fn=_noop,
        get_url_fn=lambda: "https://creator.xiaohongshu.com/publish/publish",
        get_text_fn=lambda: "",
        log_fn=lambda message: None,
    )

    assert result["success"] is True
    assert result["mode"] == "article"
    steps = [step["step"] for step in result["steps"]]
    assert "fill_article_title" in steps


def test_xiaohongshu_publish_article_default_title():
    """Test that article mode uses default title when no title is provided."""
    urls = []
    steps_data = []

    def run_js_mock(code):
        result = _mock_publish_run_js(logged_in=True)(code)
        if "title_value" in code:
            return {"success": True, "title_value": "用户未定义标题"}
        return result

    result = run(
        keyword="长文正文",
        mode="article",
        max_wait_seconds=0,
        goto_fn=lambda url: urls.append(url) or "ok",
        run_js_fn=run_js_mock,
        wait_fn=_noop,
        get_url_fn=lambda: "https://creator.xiaohongshu.com/publish/publish",
        get_text_fn=lambda: "",
        log_fn=lambda message: None,
    )

    assert result["success"] is True
    steps = [step["step"] for step in result["steps"]]
    assert "fill_article_title" in steps


def test_xiaohongshu_publish_fill_article_content():
    html = """
    <body>
      <textarea id="other" placeholder="输入标题"></textarea>
      <div class="rich-editor-content">
        <div>
          <div contenteditable="true" spellcheck="false" autocorrect="off"
            autocapitalize="off" autocomplete="off" translate="no"
            class="tiptap ProseMirror" tabindex="0">
            <p><br></p>
          </div>
        </div>
      </div>
    </body>
    """

    def assert_page(page):
        text = "正文内容evfwfvw"
        result = _fill_article_content(lambda code: page.evaluate(code), text)

        assert result["success"] is True
        content = page.locator(".tiptap.ProseMirror").text_content()
        assert "正文内容" in content

    _with_page(html, assert_page)


def test_xiaohongshu_publish_clicks_text_to_image_generates_and_publishes():
    html = """
    <body>
      <input id="search" placeholder="搜索" style="width:240px;height:32px" />
      <button id="mode" role="tab" style="width:120px;height:36px">文字配图</button>
      <textarea id="content" placeholder="请输入图文内容"
        style="display:none;width:600px;height:180px;border:1px solid #ddd"></textarea>
      <button id="generate" style="position:fixed;left:320px;bottom:24px;
        width:120px;height:36px;background:#ff2442;color:white">生成图片</button>
      <h2 id="preview" style="display:none;position:fixed;left:16px;top:20px">预览图片</h2>
      <button id="next" style="display:none;position:fixed;left:24px;bottom:24px;
        width:96px;height:36px;background:#ff2442;color:white">下一步</button>
      <h2 id="image-edit" style="display:none;position:fixed;left:260px;top:20px">图片编辑</h2>
      <button id="publish" style="display:none;position:fixed;left:520px;bottom:24px;
        width:96px;height:36px;background:#ff2442;color:white">发布</button>
      <div id="published">no</div>
      <script>
        document.getElementById('mode').addEventListener('click', () => {
          document.getElementById('content').style.display = 'block';
          document.body.setAttribute('data-mode', 'text-to-image');
        });
        document.getElementById('generate').addEventListener('click', () => {
          document.getElementById('preview').style.display = 'block';
          document.getElementById('next').style.display = 'block';
        });
        document.getElementById('next').addEventListener('click', () => {
          document.getElementById('preview').style.display = 'none';
          document.getElementById('next').style.display = 'none';
          document.getElementById('image-edit').style.display = 'block';
          document.getElementById('publish').style.display = 'block';
        });
        document.getElementById('publish').addEventListener('click', () => {
          document.getElementById('published').textContent =
            document.getElementById('content').value;
        });
      </script>
    </body>
    """

    def assert_page(page):
        mode_result = _click_text_to_image(lambda code: page.evaluate(code))
        fill_result = _fill_publish_content(
            lambda code: page.evaluate(code),
            "第一行图文内容\n第二行图文内容",
        )
        generate_result = _click_generate_image(lambda code: page.evaluate(code))
        preview_result = _detect_preview_image(lambda code: page.evaluate(code))
        next_result = _click_next_step(lambda code: page.evaluate(code))
        image_edit_result = _detect_image_edit(lambda code: page.evaluate(code))
        publish_result = _click_final_publish(lambda code: page.evaluate(code))

        assert mode_result["success"] is True
        assert fill_result["success"] is True
        assert generate_result["success"] is True
        assert preview_result["success"] is True
        assert next_result["success"] is True
        assert image_edit_result["success"] is True
        assert publish_result["success"] is True
        assert page.locator("body").get_attribute("data-mode") == "text-to-image"
        assert page.locator("#content").input_value() == "第一行图文内容\n第二行图文内容"
        assert page.locator("#search").input_value() == ""
        assert "第一行图文内容" in page.locator("#published").text_content()

    _with_page(html, assert_page)


def test_xiaohongshu_publish_source_runs_inside_script_engine():
    source = Path("src/skill_library/send/xiaohongshu_publish.py").read_text(
        encoding="utf-8"
    )
    urls = []
    engine = ScriptEngine()
    engine.register_functions(
        {
            "goto": lambda url: urls.append(url) or "ok",
            "run_js": _mock_publish_run_js(logged_in=True),
            "wait": _noop,
            "get_url": lambda: "https://creator.xiaohongshu.com/publish/publish",
            "get_text": lambda: "",
        }
    )

    result = engine.execute(
        source + "\nresult = run(keyword='测试图文内容', max_wait_seconds=0)\nprint(result)"
    )

    assert result.success is True
    assert urls == [
        "https://www.xiaohongshu.com/login",
        "https://creator.xiaohongshu.com/publish/publish?source=official&from=tab_switch&target=image",
    ]
    assert "'success': True" in result.output

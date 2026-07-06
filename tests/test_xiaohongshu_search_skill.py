"""Tests for the Xiaohongshu search skill adapter."""

from __future__ import annotations

import pytest
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from src.skill_library.search import xiaohongshu_search


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


def test_xiaohongshu_search_treats_recommendation_prompt_as_logged_out(monkeypatch):
    html = """
    <body>
      <div>\u767b\u5f55\u540e\u63a8\u8350\u66f4\u61c2\u4f60\u7684\u7b14\u8bb0</div>
      <a href="/explore/698af8b4000000001b01c20b">note</a>
    </body>
    """

    def assert_page(page):
        monkeypatch.setattr(
            xiaohongshu_search,
            "get_url",
            lambda: "https://www.xiaohongshu.com/search_result_ai?keyword=test",
            raising=False,
        )
        monkeypatch.setattr(
            xiaohongshu_search,
            "run_js",
            lambda code: page.evaluate(code),
            raising=False,
        )

        assert xiaohongshu_search._is_logged_in() is False

    _with_page(html, assert_page)

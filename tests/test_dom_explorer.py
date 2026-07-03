"""Tests for the lightweight DOM explorer."""

from __future__ import annotations

from unittest.mock import MagicMock

from src.core.dom_explorer import summarize_page


def test_summarize_page_formats_interactive_candidates():
    page = MagicMock()
    page.url = "https://example.com/article"
    page.title.return_value = "Example Article"
    page.evaluate.return_value = {
        "elements": [
            {
                "tag": "button",
                "role": "",
                "type": "",
                "text": "评论",
                "selector": "button.comment",
                "x": 10,
                "y": 20,
                "width": 80,
                "height": 32,
            },
            {
                "tag": "textarea",
                "role": "textbox",
                "placeholder": "写下你的评论",
                "selector": "textarea",
            },
        ],
        "counts": {"button": 1, "textbox": 1},
        "state": {
            "hasModal": True,
            "hasDrawer": False,
            "hasDropdown": False,
            "canvasCount": 0,
            "svgCount": 2,
        },
    }

    summary = summarize_page(page)

    assert summary.title == "Example Article"
    assert summary.interactive_count == 2
    assert summary.has_modal is True
    assert summary.svg_count == 2
    text = summary.to_text()
    assert "可交互元素: 2" in text
    assert "Modal" in text
    assert "button text='评论' selector=button.comment" in text
    assert "textbox text='写下你的评论' selector=textarea" in text


def test_summarize_page_falls_back_when_dom_evaluate_fails():
    page = MagicMock()
    page.url = "https://example.com"
    page.title.return_value = "Example"
    page.evaluate.side_effect = RuntimeError("evaluate failed")

    summary = summarize_page(page)

    assert summary.url == "https://example.com"
    assert summary.title == "Example"
    assert summary.interactive_count == 0
    assert "可交互元素: 0" in summary.to_text()


def test_summarize_page_ignores_unexpected_dom_payload():
    page = MagicMock()
    page.url = "https://example.com"
    page.title.return_value = "Example"
    page.evaluate.return_value = "not a dom summary"

    summary = summarize_page(page)

    assert summary.title == "Example"
    assert summary.elements == []

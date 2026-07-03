"""Tests for the Zhihu search skill adapter."""

from __future__ import annotations

from pathlib import Path

from src.core.script_engine import ScriptEngine
from src.skill_library.zhihu.zhihu_search import run


def _noop(*args):
    return "ok"


def _make_engine(goto_fn=None, log_fn=None):
    engine = ScriptEngine()
    engine.register_functions(
        {
            "goto": goto_fn or _noop,
            "wait": _noop,
            "wait_for_navigation": _noop,
            "get_url": lambda: "",
            "log": log_fn or _noop,
        }
    )
    return engine


def test_zhihu_search_navigates_to_search_url(monkeypatch):
    urls = []

    monkeypatch.setitem(run.__globals__, "goto", lambda url: urls.append(url) or "ok")
    monkeypatch.setitem(run.__globals__, "log", _noop)
    monkeypatch.setitem(run.__globals__, "url_quote", lambda value: value)

    run("test")

    assert urls == ["https://www.zhihu.com/search?q=test"]


def test_zhihu_search_encodes_chinese_keyword():
    urls = []
    engine = _make_engine(goto_fn=lambda url: urls.append(url) or "ok")
    source = Path("src/skill_library/zhihu/zhihu_search.py").read_text(
        encoding="utf-8"
    )

    result = engine.execute(source + '\nresult = run("机器学习")\n')

    assert result.success is True
    assert urls == ["https://www.zhihu.com/search?q=%E6%9C%BA%E5%99%A8%E5%AD%A6%E4%B9%A0"]


def test_zhihu_search_logs_completion():
    logs = []
    engine = _make_engine(log_fn=lambda msg: logs.append(msg))
    source = Path("src/skill_library/zhihu/zhihu_search.py").read_text(
        encoding="utf-8"
    )

    result = engine.execute(source + '\nresult = run("test")\n')

    assert result.success is True
    assert logs == ["知乎搜索完成: test"]

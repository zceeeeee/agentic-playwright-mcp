"""Tests for the Bilibili search skill adapter."""

from __future__ import annotations

from pathlib import Path

from src.core.script_engine import ScriptEngine


def test_bilibili_search_source_runs_inside_script_engine():
    source = Path("src/skill_library/search/bilibili_search.py").read_text(
        encoding="utf-8"
    )
    urls = []
    logs = []
    engine = ScriptEngine()
    engine.register_functions(
        {
            "goto": lambda url: urls.append(url) or "ok",
            "log": lambda message: logs.append(message),
        }
    )

    result = engine.execute(source + '\nrun("机器学习")\n')

    assert result.success is True
    assert urls == [
        "https://search.bilibili.com/all?keyword=%E6%9C%BA%E5%99%A8%E5%AD%A6%E4%B9%A0"
    ]
    assert logs == ["Bilibili 搜索完成: 机器学习"]

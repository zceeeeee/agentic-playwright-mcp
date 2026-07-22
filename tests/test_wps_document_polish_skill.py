"""Tests for editing an existing WPS document with AI assistance."""

from pathlib import Path

import yaml

from src.core.script_engine import ScriptEngine
from src.core.skill_router import SkillRouter
from src.skill_library.export.wps_document_polish import run
from src.layer_1.wps_writer import _normalize_windows_path


def test_wps_path_normalization_removes_panel_quotes():
    expected = r"C:\Users\hcy15\Desktop\报告.docx"

    assert _normalize_windows_path(f'"{expected}"') == expected
    assert _normalize_windows_path(f"“{expected}”") == expected


def test_router_routes_existing_wps_document_polish():
    router = SkillRouter(library_dir="src/skill_library")

    decision = router.route(r'WPS文章润色 "D:\docs\报告.docx"')

    assert decision.skill is not None
    assert decision.skill.id == "domain/wps_document_polish"
    assert '"D:\\\\docs\\\\报告.docx"' in decision.script
    assert "wps_document_read" in decision.script
    assert "wps_document_rewrite" in decision.script


def test_router_routes_short_wps_polish_and_confirms_detected_path():
    router = SkillRouter(library_dir="src/skill_library")

    decision = router.route(r'wps润色 "C:\Users\hcy15\Desktop\报告.docx"')

    assert decision.skill is not None
    assert decision.skill.id == "domain/wps_document_polish"
    assert '"C:\\Users\\hcy15\\Desktop\\报告.docx"' in decision.script
    assert "__agentic_prepare_param" in decision.script
    assert "已有 WPS/Word 文档的完整路径" in decision.script


def test_wps_polish_does_not_rewrite_when_user_declines_changes():
    answers = iter(["no", "no"])
    rewrites = []

    result = run(
        document_path=r"D:\docs\报告.docx",
        read_fn=lambda path: {"success": True, "text": "标题\n正文"},
        rewrite_fn=lambda *args, **kwargs: rewrites.append((args, kwargs)),
        prompt_fn=lambda question: next(answers),
        generate_fn=lambda prompt: "should not run",
    )

    assert result["success"] is True
    assert result["modified"] is False
    assert rewrites == []


def test_wps_polish_then_formats_and_rewrites_markdown():
    answers = iter(["yes", "yes", "标题居中，重点使用红色"])
    prompts = []
    rewrites = []

    def generate(prompt):
        prompts.append(prompt)
        if len(prompts) == 1:
            return "# 润色标题\n\n润色后的正文"
        return '# 润色标题\n\n<span style="color: red">润色后的正文</span>'

    result = run(
        document_path=r"D:\docs\报告.docx",
        read_fn=lambda path: {"success": True, "text": "原始标题\n原始正文"},
        rewrite_fn=lambda path, markdown, keep_open=True: rewrites.append(
            (path, markdown, keep_open)
        )
        or {
            "success": True,
            "document_path": path,
            "backup_path": r"D:\docs\报告.backup.docx",
        },
        prompt_fn=lambda question: next(answers),
        generate_fn=generate,
    )

    assert len(prompts) == 2
    assert "润色" in prompts[0]
    assert "不得添加图片、配图建议或任何图片占位符" in prompts[0]
    assert "标题居中，重点使用红色" in prompts[1]
    assert "不得添加图片、配图建议或任何图片占位符" in prompts[1]
    assert rewrites == [
        (
            r"D:\docs\报告.docx",
            '# 润色标题\n\n<span style="color: red">润色后的正文</span>',
            True,
        )
    ]
    assert result["modified"] is True
    assert result["polished"] is True
    assert result["reformatted"] is True


def test_wps_polish_generates_and_inserts_table_when_ai_adds_placeholder():
    answers = iter(["yes", "no"])
    prompts = []
    rewrites = []

    def generate(prompt):
        prompts.append(prompt)
        if len(prompts) == 1:
            return "# 调研报告\n\n主要数据如下。\n\n[[WPS_TABLE_1]]\n\n结论。"
        return (
            '{"tables":[{"placeholder":"[[WPS_TABLE_1]]",'
            '"title":"调研数据","columns":["项目","结果"],'
            '"rows":[["样本数","100"]],'
            '"style":{"header_bold":true,"border":"grid","auto_fit":true}}]}'
        )

    result = run(
        document_path=r"D:\docs\报告.docx",
        read_fn=lambda path: {"success": True, "text": "调研报告\n样本数为100。"},
        rewrite_fn=lambda path, markdown, **kwargs: rewrites.append(
            (path, markdown, kwargs)
        )
        or {
            "success": True,
            "document_path": path,
            "backup_path": r"D:\docs\报告.backup.docx",
            "table_count": 1,
        },
        prompt_fn=lambda question: next(answers),
        generate_fn=generate,
    )

    assert len(prompts) == 2
    assert "是否能明显提升可读性" in prompts[0]
    assert "严格 JSON" in prompts[1]
    assert rewrites[0][1].count("[[WPS_TABLE_1]]") == 1
    assert '"columns":["项目","结果"]' in rewrites[0][2]["table_json"]
    assert rewrites[0][2]["keep_open"] is True
    assert result["table_inserted"] is True


def test_wps_polish_source_runs_inside_script_engine():
    source = Path("src/skill_library/export/wps_document_polish.py").read_text(
        encoding="utf-8"
    )
    answers = iter(["no", "no"])
    engine = ScriptEngine()
    engine.register_functions(
        {
            "wps_document_read": lambda path: {"success": True, "text": "正文"},
            "wps_document_rewrite": lambda *args, **kwargs: {"success": True},
            "panel_prompt": lambda question: next(answers),
            "llm_generate_text": lambda prompt: "unused",
        }
    )

    result = engine.execute(
        source + '\nresult = run(document_path="D:/docs/report.docx")\n'
    )

    assert result.success is True
    assert "No WPS document changes requested" in result.output


def test_wps_polish_skill_yaml_and_source_are_registered():
    data = yaml.safe_load(
        Path("src/skill_library/skills.yaml").read_text(encoding="utf-8")
    )
    skills = {item["id"]: item for item in data["skills"]}
    sources = {item["id"]: item for item in data["sources"]}

    skill = skills["domain/wps_document_polish"]
    assert skill["params"]["document_path"]["required"] is True
    assert sources["domain/wps_document_polish"]["file"] == (
        "export/wps_document_polish.py"
    )

"""Tests for WPS Writer export skill."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from src.core.script_engine import ScriptEngine
from src.core.skill_router import SkillRouter
from src.layer_1.wps_writer import (
    DEFAULT_OUTPUT_DIR,
    PDF_FORMAT,
    _resolve_paths,
    export_article_to_pdf,
)
from src.skill_library.export.wps_writer_export import run


class FakeListFormat:
    def __init__(self) -> None:
        self.applied = 0
        self.removed = 0

    def ApplyNumberDefault(self) -> None:
        self.applied += 1

    def RemoveNumbers(self) -> None:
        self.removed += 1


class FakeInlineShapes:
    def __init__(self) -> None:
        self.pictures: list[str] = []

    def AddPicture(  # noqa: N802
        self, path: str, link_to_file: bool = False, save_with_document: bool = True
    ) -> None:
        self.pictures.append(path)


class FakeSelection:
    def __init__(self) -> None:
        self.Font = SimpleNamespace(
            Name="", Size=0, Bold=0, Italic=0, Underline=0, Color=None
        )
        self.ParagraphFormat = SimpleNamespace(
            Alignment=None,
            FirstLineIndent=None,
            LineSpacingRule=None,
        )
        self.Range = SimpleNamespace(ListFormat=FakeListFormat())
        self.InlineShapes = FakeInlineShapes()
        self.typed: list[str] = []
        self.formatted: list[dict[str, object]] = []

    def TypeText(self, text: str) -> None:
        self.typed.append(text)
        self.formatted.append(
            {
                "text": text,
                "font": self.Font.Name,
                "size": self.Font.Size,
                "bold": self.Font.Bold,
                "italic": self.Font.Italic,
                "underline": self.Font.Underline,
                "color": self.Font.Color,
            }
        )

    def TypeParagraph(self) -> None:
        self.typed.append("\n")


class FakeDocument:
    def __init__(self) -> None:
        self.saved: tuple[str, int | None] | None = None
        self.exported: tuple[str, int] | None = None
        self.closed = False

    def SaveAs2(self, path: str, FileFormat: int | None = None) -> None:  # noqa: N803
        self.saved = (path, FileFormat)

    def ExportAsFixedFormat(self, path: str, fmt: int) -> None:
        self.exported = (path, fmt)

    def Close(self, save_changes: bool) -> None:
        self.closed = bool(save_changes)


class FakeDocuments:
    def __init__(self, app: "FakeApplication") -> None:
        self.app = app

    def Add(self) -> FakeDocument:
        self.app.document = FakeDocument()
        return self.app.document


class FakeApplication:
    def __init__(self) -> None:
        self.Visible = None
        self.Selection = FakeSelection()
        self.Documents = FakeDocuments(self)
        self.document: FakeDocument | None = None
        self.quit_called = False

    def Quit(self) -> None:
        self.quit_called = True


def test_default_wps_output_uses_project_out_directory():
    docx, pdf = _resolve_paths("默认路径测试", file_name="default-output-test")

    assert docx.parent == DEFAULT_OUTPUT_DIR.resolve()
    assert pdf.parent == DEFAULT_OUTPUT_DIR.resolve()


def test_export_article_to_pdf_uses_wps_com_and_exports_pdf(tmp_path):
    app = FakeApplication()
    requested_prog_ids: list[str] = []

    def dispatch(prog_id: str):
        requested_prog_ids.append(prog_id)
        if prog_id != "KWPS.Application":
            raise RuntimeError("unexpected prog id")
        return app

    result = export_article_to_pdf(
        title="测试标题",
        body="第一段\n1. 第一项",
        output_dir=str(tmp_path),
        keep_open=False,
        visible=False,
        font_name="宋体",
        font_size="14",
        dispatch_fn=dispatch,
    )

    assert result["success"] is True
    assert result["provider"] == "KWPS.Application"
    assert requested_prog_ids == ["KWPS.Application"]
    assert app.Visible is False
    assert app.document is not None
    assert app.document.saved is not None
    assert app.document.saved[0].endswith(".docx")
    assert app.document.exported is not None
    assert app.document.exported[1] == PDF_FORMAT
    assert app.document.exported[0].endswith(".pdf")
    assert app.quit_called is True
    assert "测试标题" in app.Selection.typed
    assert "第一段" in app.Selection.typed
    assert "第一项" in app.Selection.typed
    assert app.Selection.Range.ListFormat.applied == 1
    assert app.Selection.Font.Name == "宋体"
    assert app.Selection.Font.Size == 14
    assert result["font_name"] == "宋体"
    assert result["font_size"] == 14


def test_export_article_to_pdf_applies_style_file_name_and_image(tmp_path):
    app = FakeApplication()
    image_path = tmp_path / "screen shot.png"
    image_path.write_bytes(b"fake image")

    result = export_article_to_pdf(
        title="edewvr",
        body="wewret",
        pdf_path=str(tmp_path / "test.pdf"),
        file_name="测试",
        keep_open=True,
        visible=False,
        font_name="斜体红色宋体",
        font_size="14",
        font_color="红色",
        italic="斜体",
        image_path=str(image_path),
        dispatch_fn=lambda prog_id: app,
    )

    assert app.document is not None
    assert app.document.saved is not None
    assert app.document.saved[0] == str((tmp_path / "test.docx").resolve())
    assert app.document.exported is not None
    assert app.document.exported[0] == str((tmp_path / "test.pdf").resolve())
    assert app.Selection.Font.Name == "宋体"
    assert app.Selection.Font.Size == 14
    assert app.Selection.Font.Italic == -1
    assert app.Selection.Font.Color == 255
    assert app.Selection.InlineShapes.pictures == [str(image_path.resolve())]
    assert result["font_color"] == 255
    assert result["italic"] is True
    assert result["image_path"] == str(image_path.resolve())


def test_export_markdown_file_to_wps_applies_headings_and_inline_styles(tmp_path):
    app = FakeApplication()
    md_path = tmp_path / "tmp.md"
    md_path.write_text(
        "# 文档标题\n\n主送机关：\n\n正文包含 **加粗** 和 *斜体*。\n\n## 一级标题\n### 二级标题\n",
        encoding="utf-8",
    )

    result = export_article_to_pdf(
        title="",
        body="",
        markdown_path=str(md_path),
        output_dir=str(tmp_path),
        keep_open=True,
        visible=False,
        dispatch_fn=lambda prog_id: app,
    )

    assert result["success"] is True
    assert result["title"] == "文档标题"
    assert result["font_size"] == 16
    assert result["font_name"] == "仿宋_GB2312"
    assert result["title_font_name"] == "方正小标宋简体"
    assert result["title_font_size"] == 22
    assert result["markdown_path"] == str(md_path.resolve())
    assert result["heading_count"] == 3
    assert result["inline_style_count"] >= 2
    assert "文档标题" in app.Selection.typed
    assert "正文包含 " in app.Selection.typed
    bold = next(item for item in app.Selection.formatted if item["text"] == "加粗")
    italic = next(item for item in app.Selection.formatted if item["text"] == "斜体")
    title = next(item for item in app.Selection.formatted if item["text"] == "文档标题")
    h1 = next(item for item in app.Selection.formatted if item["text"] == "一级标题")
    h2 = next(item for item in app.Selection.formatted if item["text"] == "二级标题")
    assert bold["bold"] == -1
    assert italic["italic"] == -1
    assert title["font"] == "方正小标宋简体"
    assert title["size"] == 22
    assert title["bold"] == 0
    assert h1["font"] == "黑体"
    assert h1["size"] == 16
    assert h1["bold"] == -1
    assert h2["font"] == "楷体_GB2312"
    assert h2["size"] == 16
    assert h2["bold"] == -1
    title_index = app.Selection.typed.index("文档标题")
    assert app.Selection.typed[title_index + 1 : title_index + 4] == ["\n", "\n", "\n"]


def test_export_generated_markdown_body_applies_inline_styles(tmp_path):
    app = FakeApplication()

    result = export_article_to_pdf(
        title="测试文章",
        body="## 核心观点\n正文包含 **加粗内容** 和 *斜体内容*。\n\n- 第一项",
        body_format="markdown",
        output_dir=str(tmp_path),
        keep_open=True,
        visible=False,
        dispatch_fn=lambda prog_id: app,
    )

    assert result["success"] is True
    assert result["body_format"] == "markdown"
    assert result["heading_count"] == 2
    assert result["inline_style_count"] >= 2
    bold = next(item for item in app.Selection.formatted if item["text"] == "加粗内容")
    italic = next(item for item in app.Selection.formatted if item["text"] == "斜体内容")
    assert bold["bold"] == -1
    assert italic["italic"] == -1


def test_export_markdown_supports_nested_underline_and_font_colors(tmp_path):
    app = FakeApplication()

    result = export_article_to_pdf(
        title="Styled article",
        body=(
            "**<u>*World Cup*</u>** and "
            '<span style="color:#FF0000">red text</span> and '
            '<font color="blue"><u>blue underline</u></font>'
        ),
        body_format="markdown",
        output_dir=str(tmp_path),
        keep_open=True,
        visible=False,
        dispatch_fn=lambda prog_id: app,
    )

    assert result["success"] is True
    combined = next(item for item in app.Selection.formatted if item["text"] == "World Cup")
    red = next(item for item in app.Selection.formatted if item["text"] == "red text")
    blue = next(
        item for item in app.Selection.formatted if item["text"] == "blue underline"
    )
    assert combined["bold"] == -1
    assert combined["italic"] == -1
    assert combined["underline"] == 1
    assert red["color"] == 255
    assert blue["color"] == 16711680
    assert blue["underline"] == 1


def test_skill_run_calls_registered_export_function():
    calls = []
    logs = []

    result = run(
        title="标题",
        body="正文",
        output_dir="-1",
        log_fn=lambda message: logs.append(message),
        export_fn=lambda **kwargs: calls.append(kwargs)
        or {
            "success": True,
            "docx_path": "D:\\out\\test.docx",
            "pdf_path": "D:\\out\\test.pdf",
        },
    )

    assert result["success"] is True
    assert calls == [
        {
            "title": "标题",
            "body": "正文",
            "output_dir": None,
            "docx_path": None,
            "pdf_path": None,
            "file_name": None,
            "markdown_path": None,
            "body_format": None,
            "font_name": None,
            "font_size": None,
            "title_font_name": None,
            "title_font_size": None,
            "body_font_name": None,
            "body_font_size": None,
            "font_color": None,
            "italic": None,
            "image_path": None,
            "output_format": "both",
            "keep_open": True,
        }
    ]
    assert any("WPS document saved" in message for message in logs)


def test_wps_skill_source_runs_inside_script_engine():
    source = Path("src/skill_library/export/wps_writer_export.py").read_text(
        encoding="utf-8"
    )
    calls = []
    logs = []
    engine = ScriptEngine()
    engine.register_functions(
        {
            "wps_writer_export": lambda **kwargs: calls.append(kwargs)
            or {
                "success": True,
                "docx_path": "D:\\out\\test.docx",
                "pdf_path": "D:\\out\\test.pdf",
            },
            "log": lambda message: logs.append(message),
        }
    )

    result = engine.execute(source + '\nresult = run(title="标题", body="正文")\n')

    assert result.success is True
    assert calls[0]["title"] == "标题"
    assert calls[0]["body"] == "正文"
    assert any("WPS PDF exported" in message for message in logs)


def test_router_routes_wps_writer_export_to_wps_skill():
    router = SkillRouter(library_dir="src/skill_library")

    decision = router.route("WPS写文章，标题是“测试标题”，内容是“测试正文”，最后导出PDF")

    assert decision.skill is not None
    assert decision.skill.id == "domain/wps_writer_export"
    assert '"测试标题"' in decision.script
    assert '"测试正文"' in decision.script
    assert "__agentic_prepare_wps_title" in decision.script
    assert "__agentic_prepare_wps_body" in decision.script
    assert "body_format=__agentic_wps_body_format" in decision.script
    assert "使用默认值 {default}" in decision.script
    assert "'标题字体'," in decision.script and "方正小标宋简体" in decision.script
    assert "'标题字号'," in decision.script and '"22"' in decision.script
    assert "'正文字体'," in decision.script and "仿宋_GB2312" in decision.script
    assert "'正文字号'," in decision.script and '"16"' in decision.script
    assert "wps_writer_export" in decision.script


def test_router_routes_wps_docx_pdf_path_and_font_request():
    router = SkillRouter(library_dir="src/skill_library")

    decision = router.route(
        "WPS写一个docx文章，标题是“edewvr”，内容是“wewret”，导出为PDF，路径是D:tmptest.pdf，字体是宋体14号"
    )

    assert decision.skill is not None
    assert decision.skill.id == "domain/wps_writer_export"
    assert '"edewvr"' in decision.script
    assert '"wewret"' in decision.script
    assert '"D:tmptest.pdf"' in decision.script
    assert '"宋体"' in decision.script
    assert '"14"' in decision.script
    assert "__param_output_dir, __param_docx_path, __param_pdf_path" in decision.script
    assert "__agentic_prepare_wps_output_format" in decision.script
    assert "output_format=__param_output_format" in decision.script


def test_export_can_generate_word_only(tmp_path):
    app = FakeApplication()

    result = export_article_to_pdf(
        title="Word only",
        body="正文",
        output_dir=str(tmp_path),
        output_format="word",
        keep_open=False,
        dispatch_fn=lambda prog_id: app,
    )

    assert result["output_format"] == "word"
    assert result["docx_path"] is not None
    assert result["pdf_path"] is None
    assert app.document is not None
    assert app.document.saved is not None
    assert app.document.exported is None


def test_export_can_generate_pdf_only(tmp_path):
    app = FakeApplication()

    result = export_article_to_pdf(
        title="PDF only",
        body="正文",
        output_dir=str(tmp_path),
        output_format="pdf",
        keep_open=False,
        dispatch_fn=lambda prog_id: app,
    )

    assert result["output_format"] == "pdf"
    assert result["docx_path"] is None
    assert result["pdf_path"] is not None
    assert app.document is not None
    assert app.document.saved is None
    assert app.document.exported is not None


def test_export_defaults_to_word_and_pdf(tmp_path):
    app = FakeApplication()

    result = export_article_to_pdf(
        title="Both",
        body="正文",
        output_dir=str(tmp_path),
        keep_open=False,
        dispatch_fn=lambda prog_id: app,
    )

    assert result["output_format"] == "both"
    assert result["docx_path"] is not None
    assert result["pdf_path"] is not None
    assert app.document is not None
    assert app.document.saved is not None
    assert app.document.exported is not None


def test_router_routes_wps_style_and_insert_image_request():
    router = SkillRouter(library_dir="src/skill_library")

    decision = router.route(
        r'WPS写文章，文件名是“测试”，标题“edewvr”，内容是“wewret”，路径是"D:/tmp/test.pdf"，字体是斜体红色宋体14，插入图片"D:\Users\qq275\Pictures\Screenshots\屏幕截图 2026-04-07 180134.png"'
    )

    assert decision.skill is not None
    assert decision.skill.id == "domain/wps_writer_export"
    assert '"edewvr"' in decision.script
    assert '"wewret"' in decision.script
    assert 'file_name="测试"' in decision.script
    assert '"D:/tmp/test.pdf"' in decision.script
    assert '"宋体"' in decision.script
    assert '"14"' in decision.script
    assert 'font_color="红色"' in decision.script
    assert 'italic="斜体"' in decision.script
    assert (
        'image_path="D:\\\\Users\\\\qq275\\\\Pictures\\\\Screenshots\\\\屏幕截图 2026-04-07 180134.png"'
        in decision.script
    )


def test_router_routes_markdown_file_to_wps_article():
    router = SkillRouter(library_dir="src/skill_library")

    decision = router.route(r'把"D:\fagougou\doc\tmp.md转换成wps文章，文件名是“fev”')

    assert decision.skill is not None
    assert decision.skill.id == "domain/wps_writer_export"
    assert '"D:\\\\fagougou\\\\doc\\\\tmp.md"' in decision.script
    assert 'file_name="fev"' in decision.script

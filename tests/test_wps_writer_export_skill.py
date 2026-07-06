"""Tests for WPS Writer export skill."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from src.core.script_engine import ScriptEngine
from src.core.skill_router import SkillRouter
from src.layer_1.wps_writer import PDF_FORMAT, export_article_to_pdf
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
        self.Font = SimpleNamespace(Name="", Size=0, Bold=0, Italic=0, Color=None)
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
        "# 一级标题\n\n正文包含 **加粗** 和 *斜体*。\n\n## 二级标题\n##### 五级标题\n",
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
    assert result["title"] == "一级标题"
    assert result["font_size"] == 14
    assert result["markdown_path"] == str(md_path.resolve())
    assert result["heading_count"] == 3
    assert result["inline_style_count"] >= 2
    assert "一级标题" in app.Selection.typed
    assert "正文包含 " in app.Selection.typed
    bold = next(item for item in app.Selection.formatted if item["text"] == "加粗")
    italic = next(item for item in app.Selection.formatted if item["text"] == "斜体")
    h1 = next(item for item in app.Selection.formatted if item["text"] == "一级标题")
    h2 = next(item for item in app.Selection.formatted if item["text"] == "二级标题")
    assert bold["bold"] == -1
    assert italic["italic"] == -1
    assert h1["font"] != h2["font"]


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
            "font_name": None,
            "font_size": None,
            "font_color": None,
            "italic": None,
            "image_path": None,
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
    assert 'title="测试标题"' in decision.script
    assert 'body="测试正文"' in decision.script
    assert "wps_writer_export" in decision.script


def test_router_routes_wps_docx_pdf_path_and_font_request():
    router = SkillRouter(library_dir="src/skill_library")

    decision = router.route(
        "WPS写一个docx文章，标题是“edewvr”，内容是“wewret”，导出为PDF，路径是D:tmptest.pdf，字体是宋体14号"
    )

    assert decision.skill is not None
    assert decision.skill.id == "domain/wps_writer_export"
    assert 'title="edewvr"' in decision.script
    assert 'body="wewret"' in decision.script
    assert 'pdf_path="D:tmptest.pdf"' in decision.script
    assert 'font_name="宋体"' in decision.script
    assert 'font_size="14"' in decision.script


def test_router_routes_wps_style_and_insert_image_request():
    router = SkillRouter(library_dir="src/skill_library")

    decision = router.route(
        r'WPS写文章，文件名是“测试”，标题“edewvr”，内容是“wewret”，路径是"D:/tmp/test.pdf"，字体是斜体红色宋体14，插入图片"D:\Users\qq275\Pictures\Screenshots\屏幕截图 2026-04-07 180134.png"'
    )

    assert decision.skill is not None
    assert decision.skill.id == "domain/wps_writer_export"
    assert 'title="edewvr"' in decision.script
    assert 'body="wewret"' in decision.script
    assert 'file_name="测试"' in decision.script
    assert 'pdf_path="D:/tmp/test.pdf"' in decision.script
    assert 'font_name="宋体"' in decision.script
    assert 'font_size="14"' in decision.script
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
    assert 'markdown_path="D:\\\\fagougou\\\\doc\\\\tmp.md"' in decision.script
    assert 'file_name="fev"' in decision.script

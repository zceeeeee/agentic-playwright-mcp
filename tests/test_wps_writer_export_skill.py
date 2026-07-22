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
    rewrite_wps_document,
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


class FakeCell:
    def __init__(self) -> None:
        self.Range = SimpleNamespace(Text="")


class FakeTable:
    def __init__(self, rows: int, columns: int) -> None:
        self.cells = [
            [FakeCell() for _ in range(columns)] for _ in range(rows)
        ]
        self.Borders = SimpleNamespace(Enable=0)
        self.Range = SimpleNamespace(
            End=100,
            Font=SimpleNamespace(Name="", Size=0),
        )
        header_range = SimpleNamespace(Font=SimpleNamespace(Bold=0))
        self.Rows = SimpleNamespace(Item=lambda index: SimpleNamespace(Range=header_range))
        self.auto_fit = None

    def Cell(self, row: int, column: int) -> FakeCell:  # noqa: N802
        return self.cells[row - 1][column - 1]

    def AutoFitBehavior(self, behavior: int) -> None:  # noqa: N802
        self.auto_fit = behavior


class FakeTables:
    def __init__(self) -> None:
        self.created: list[FakeTable] = []

    def Add(self, selection_range, rows: int, columns: int) -> FakeTable:  # noqa: N802
        table = FakeTable(rows, columns)
        self.created.append(table)
        return table


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
        self.Tables = FakeTables()
        self.Range = SimpleNamespace(ListFormat=FakeListFormat(), Tables=self.Tables)
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

    def SetRange(self, start: int, end: int) -> None:  # noqa: N802
        self.last_range = (start, end)

    def WholeStory(self) -> None:  # noqa: N802
        self.whole_story_selected = True

    def Delete(self) -> None:
        self.deleted = True


class FakeDocument:
    def __init__(self) -> None:
        self.saved: tuple[str, int | None] | None = None
        self.exported: tuple[str, int] | None = None
        self.closed = False
        self.Saved = False
        self.save_calls = 0

    def SaveAs2(self, path: str, FileFormat: int | None = None) -> None:  # noqa: N803
        self.saved = (path, FileFormat)
        self.Saved = True

    def Save(self) -> None:
        self.save_calls += 1
        self.Saved = True

    def Activate(self) -> None:
        self.activated = True

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

    def Open(self, path: str) -> FakeDocument:
        self.app.document = FakeDocument()
        self.app.opened_path = path
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


def test_export_article_inserts_ai_table_at_markdown_placeholder(tmp_path):
    app = FakeApplication()
    table_json = """{
      "tables": [{
        "placeholder": "[[WPS_TABLE_1]]",
        "title": "央视主要频道",
        "columns": ["频道", "定位"],
        "rows": [["CCTV-1", "综合"], ["CCTV-13", "新闻"]],
        "style": {"header_bold": true, "border": "grid", "auto_fit": true}
      }]
    }"""

    result = export_article_to_pdf(
        title="央视简介",
        body="## 频道概览\n\n[[WPS_TABLE_1]]\n\n以上为主要频道。",
        body_format="markdown",
        table_json=table_json,
        output_dir=str(tmp_path),
        keep_open=False,
        dispatch_fn=lambda prog_id: app,
    )

    assert result["table_count"] == 1
    assert len(app.Selection.Tables.created) == 1
    table = app.Selection.Tables.created[0]
    assert table.Cell(1, 1).Range.Text == "频道"
    assert table.Cell(1, 2).Range.Text == "定位"
    assert table.Cell(2, 1).Range.Text == "CCTV-1"
    assert table.Cell(3, 2).Range.Text == "新闻"
    assert table.Borders.Enable == 1
    assert table.auto_fit == 1
    assert "[[WPS_TABLE_1]]" not in app.Selection.typed


def test_export_article_appends_missing_table_placeholder(tmp_path):
    app = FakeApplication()
    table_json = (
        '{"tables":[{"columns":["项目","说明"],'
        '"rows":[["示例","内容"]]}]}'
    )

    result = export_article_to_pdf(
        title="自动补位",
        body="正文没有显式占位符。",
        body_format="markdown",
        table_json=table_json,
        output_dir=str(tmp_path),
        keep_open=False,
        dispatch_fn=lambda prog_id: app,
    )

    assert result["table_count"] == 1
    assert len(app.Selection.Tables.created) == 1


def test_rewrite_existing_document_inserts_ai_table(tmp_path):
    app = FakeApplication()
    document_path = tmp_path / "report.docx"
    document_path.write_bytes(b"fake docx")
    table_json = (
        '{"tables":[{"placeholder":"[[WPS_TABLE_1]]",'
        '"columns":["项目","结果"],"rows":[["样本数","100"]]}]}'
    )

    result = rewrite_wps_document(
        str(document_path),
        "# 调研报告\n\n数据如下。\n\n[[WPS_TABLE_1]]\n\n结论。",
        table_json=table_json,
        keep_open=True,
        visible=False,
        dispatch_fn=lambda prog_id: app,
    )

    assert result["table_count"] == 1
    assert result["backup_path"] != str(document_path)
    assert Path(result["backup_path"]).exists()
    assert len(app.Selection.Tables.created) == 1
    table = app.Selection.Tables.created[0]
    assert table.Cell(1, 1).Range.Text == "项目"
    assert table.Cell(2, 2).Range.Text == "100"
    assert "[[WPS_TABLE_1]]" not in app.Selection.typed
    assert app.document is not None
    assert app.document.save_calls == 1


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


def test_export_markdown_accepts_ai_spaced_underline_tags(tmp_path):
    app = FakeApplication()

    result = export_article_to_pdf(
        title="世界杯",
        body="故事发生在**< u >*英雄加冕的舞台*< /u >**。",
        body_format="markdown",
        output_dir=str(tmp_path),
        keep_open=True,
        visible=False,
        dispatch_fn=lambda prog_id: app,
    )

    assert result["success"] is True
    styled = next(
        item for item in app.Selection.formatted if item["text"] == "英雄加冕的舞台"
    )
    assert styled["bold"] == -1
    assert styled["italic"] == -1
    assert styled["underline"] == 1
    assert "< u >" not in app.Selection.typed
    assert "< /u >" not in app.Selection.typed


def test_export_markdown_removes_ai_image_description_placeholders(tmp_path):
    app = FakeApplication()

    result = export_article_to_pdf(
        title="世界杯",
        body=(
            "第一段正文。\n\n"
            "[图片3：身着各国球衣的中国球迷群体]\n\n"
            "【配图：球场全景】\n\n"
            "第二段正文。"
        ),
        body_format="markdown",
        output_dir=str(tmp_path),
        keep_open=True,
        visible=False,
        dispatch_fn=lambda prog_id: app,
    )

    assert result["success"] is True
    rendered = "".join(app.Selection.typed)
    assert "第一段正文" in rendered
    assert "第二段正文" in rendered
    assert "身着各国球衣" not in rendered
    assert "球场全景" not in rendered


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
            "table_json": None,
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
    assert "__agentic_optional_input('正文字数', '-1', '800', '默认800')" in decision.script
    assert "__agentic_optional_input('标题字数限制', '-1', '20', '默认20')" in decision.script
    assert "body_format=__agentic_wps_body_format" in decision.script
    assert "使用默认值 {default}" in decision.script
    assert "'标题字体'," in decision.script and "方正小标宋简体" in decision.script
    assert "'标题字号'," in decision.script and '"22"' in decision.script
    assert "'正文字体'," in decision.script and "仿宋_GB2312" in decision.script
    assert "'正文字号'," in decision.script and '"16"' in decision.script
    assert "wps_writer_export" in decision.script


def test_wps_ai_topic_prompt_offers_checkbox_requirements():
    router = SkillRouter(library_dir="src/skill_library")

    decision = router.route("WPS写文章")

    assert decision.skill is not None
    assert decision.skill.id == "domain/wps_writer_export"
    assert "def __agentic_wps_topic_input" in decision.script
    assert "'type': 'checkbox_group'" in decision.script
    for label in (
        "部分字体加粗",
        "部分字体下划线",
        "应用不同颜色的字",
        "多级标题",
        "插入表格",
        "部分字体斜体",
    ):
        assert label in decision.script
    assert "当前模型不支持生成图片" in decision.script
    assert "任何图片占位符" in decision.script
    assert "只生成文章正文，不要输出文章标题" in decision.script
    assert "__agentic_strip_generated_body_title" in decision.script
    assert "__agentic_ensure_generated_body_colors" in decision.script
    assert "#C00000" in decision.script
    assert "#1F4E79" in decision.script
    assert "#548235" in decision.script
    assert "需要插入图片，并在正文中预留合适位置" not in decision.script
    assert "topic = __agentic_wps_topic_input(current)" in decision.script


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
    assert app.document.Saved is True
    assert app.document.save_calls == 1
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
    assert app.document.Saved is True
    assert app.document.save_calls == 0
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
    assert app.document.Saved is True
    assert app.document.save_calls == 1
    assert app.document.exported is not None


def test_file_name_overrides_name_from_explicit_save_path(tmp_path):
    app = FakeApplication()
    old_path = tmp_path / "原来的名字.docx"

    result = export_article_to_pdf(
        title="文章标题",
        body="正文",
        docx_path=str(old_path),
        file_name="修改后的名字",
        output_format="both",
        keep_open=False,
        dispatch_fn=lambda prog_id: app,
    )

    assert Path(result["docx_path"]).name == "修改后的名字.docx"
    assert Path(result["pdf_path"]).name == "修改后的名字.pdf"
    assert Path(result["docx_path"]).parent == tmp_path.resolve()
    assert Path(result["pdf_path"]).parent == tmp_path.resolve()


def test_router_routes_wps_style_and_insert_image_request():
    router = SkillRouter(library_dir="src/skill_library")

    decision = router.route(
        r'WPS写文章，文件名是“测试”，标题“edewvr”，内容是“wewret”，路径是"D:/tmp/test.pdf"，字体是斜体红色宋体14，插入图片"D:\Users\qq275\Pictures\Screenshots\屏幕截图 2026-04-07 180134.png"'
    )

    assert decision.skill is not None
    assert decision.skill.id == "domain/wps_writer_export"
    assert '"edewvr"' in decision.script
    assert '"wewret"' in decision.script
    assert '__agentic_prepare_wps_file_name("测试", __param_title)' in decision.script
    assert "file_name=__param_file_name" in decision.script
    assert '"D:/tmp/test.pdf"' in decision.script
    assert '"宋体"' in decision.script
    assert '"14"' in decision.script
    assert 'font_color="红色"' in decision.script
    assert 'italic="斜体"' in decision.script
    assert "__agentic_prepare_wps_image" in decision.script
    assert "D:\\\\Users\\\\qq275\\\\Pictures\\\\Screenshots" in decision.script
    assert "image_path=__param_image_path" in decision.script


def test_wps_image_prompt_keeps_missing_values_as_minus_one():
    router = SkillRouter(library_dir="src/skill_library")

    decision = router.route("WPS写文章，标题是测试，内容是正文")

    assert decision.skill is not None
    assert decision.skill.id == "domain/wps_writer_export"
    assert '__agentic_prepare_wps_image("-1", "-1")' in decision.script
    assert "是否在 WPS 文档末尾插入图片" in decision.script
    assert "[yes] [no]" in decision.script


def test_wps_image_prompt_initializes_yes_and_image_path_from_task():
    router = SkillRouter(library_dir="src/skill_library")

    decision = router.route(
        r'WPS写文章，标题是测试，内容是正文，插入图片 "D:\Pictures\cover.png"'
    )

    assert decision.skill is not None
    assert decision.skill.id == "domain/wps_writer_export"
    expected = '__agentic_prepare_wps_image("true", "D:\\\\Pictures\\\\cover.png")'
    assert expected in decision.script
    assert "image_path=__param_image_path" in decision.script


def test_wps_image_prompt_initializes_no_without_a_path():
    router = SkillRouter(library_dir="src/skill_library")

    decision = router.route("WPS写文章，标题是测试，内容是正文，不要插入图片")

    assert decision.skill is not None
    assert decision.skill.id == "domain/wps_writer_export"
    assert '__agentic_prepare_wps_image("false", "-1")' in decision.script


def test_wps_image_prompt_extracts_path_after_chinese_shi():
    router = SkillRouter(library_dir="src/skill_library")

    decision = router.route(
        'wps写文章 要插入图片 图片地址时'
        '"C:\\Users\\hcy15\\Desktop\\7e68b7c7055d48965a12e5a64ae0bc3.jpg"'
    )

    assert decision.skill is not None
    assert decision.skill.id == "domain/wps_writer_export"
    expected_path = (
        '"C:\\\\Users\\\\hcy15\\\\Desktop\\\\'
        '7e68b7c7055d48965a12e5a64ae0bc3.jpg"'
    )
    assert expected_path in decision.script
    image_prompt = decision.script.index("__param_image_path =")
    save_prompt = decision.script.index("__param_output_dir, __param_docx_path")
    assert image_prompt < save_prompt


def test_wps_file_name_prompt_is_last_export_option_and_uses_title_default():
    router = SkillRouter(library_dir="src/skill_library")

    decision = router.route("WPS写文章，标题是季度总结，内容是本季度工作内容")

    assert decision.skill is not None
    assert decision.skill.id == "domain/wps_writer_export"
    assert "def __agentic_prepare_wps_file_name" in decision.script
    assert "'default_value': default_name" in decision.script
    assert "else '新建文档'" in decision.script
    assert '__agentic_prepare_wps_file_name("-1", __param_title)' in decision.script
    output_format = decision.script.index("__param_output_format =")
    file_name = decision.script.index("__param_file_name =")
    run_call = decision.script.index("\nrun(\n")
    assert output_format < file_name < run_call


def test_wps_ai_body_passes_user_requirements_without_forced_styles():
    router = SkillRouter(library_dir="src/skill_library")

    decision = router.route("WPS写文章，标题是测试，内容是只要文字，不要加粗和下划线")

    assert decision.skill is not None
    assert decision.skill.id == "domain/wps_writer_export"
    assert "用户原始要求" in decision.script
    assert "不要擅自添加用户未要求的格式" in decision.script
    assert "仅当用户原始要求明确提出对应格式时" in decision.script
    assert '不同颜色使用 <span style="color:#RRGGBB">文字</span>' in decision.script
    assert "用户未要求的格式不得添加" in decision.script
    assert "关键观点可加粗" not in decision.script
    assert "下划线使用 <u>文字</u>" not in decision.script


def test_wps_ai_body_supports_single_table_requirement_prompt_and_json():
    router = SkillRouter(library_dir="src/skill_library")

    decision = router.route(
        "WPS写文章，标题是央视介绍，内容是介绍央视并生成主要频道表格"
    )

    assert decision.skill is not None
    assert decision.skill.id == "domain/wps_writer_export"
    assert "__agentic_wps_requests_table" in decision.script
    assert "请输入表格内容、列名、数据或样式要求" in decision.script
    assert "如无额外要求请输入“无”" in decision.script
    assert "table_answer.lower() in {'无', '无要求', '没有', 'none', 'no'}" in decision.script
    assert "[[WPS_TABLE_1]]" in decision.script
    assert "只返回严格 JSON" in decision.script
    assert "__param_table_json = __agentic_prepare_wps_tables(__param_body)" in decision.script
    assert "table_json=__param_table_json" in decision.script


def test_wps_table_prompt_is_not_enabled_for_unrelated_ai_body():
    router = SkillRouter(library_dir="src/skill_library")

    decision = router.route("WPS写文章，标题是春天，内容是描写春天的散文")

    assert decision.skill is not None
    assert decision.skill.id == "domain/wps_writer_export"
    assert "if __agentic_wps_requests_table(topic):" in decision.script
    assert "__agentic_wps_table_requested = False" in decision.script


def test_router_routes_markdown_file_to_wps_article():
    router = SkillRouter(library_dir="src/skill_library")

    decision = router.route(r'把"D:\fagougou\doc\tmp.md转换成wps文章，文件名是“fev”')

    assert decision.skill is not None
    assert decision.skill.id == "domain/wps_writer_export"
    assert '"D:\\\\fagougou\\\\doc\\\\tmp.md"' in decision.script
    assert '__agentic_prepare_wps_file_name("fev", __param_title)' in decision.script
    assert "file_name=__param_file_name" in decision.script

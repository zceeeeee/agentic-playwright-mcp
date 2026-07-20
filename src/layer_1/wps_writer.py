"""Local WPS Writer / Word automation helpers."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

WPS_PROG_IDS = (
    "KWPS.Application",
    "KWPS.Application.9",
    "WPS.Application",
    "Word.Application",
)

DOCX_FORMAT = 16
PDF_FORMAT = 17
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "out"

WORD_COLOR_VALUES = {
    "black": 0,
    "blue": 16711680,
    "gray": 8421504,
    "grey": 8421504,
    "green": 32768,
    "red": 255,
    "white": 16777215,
    "yellow": 65535,
    "黑色": 0,
    "蓝色": 16711680,
    "灰色": 8421504,
    "绿色": 32768,
    "红色": 255,
    "白色": 16777215,
    "黄色": 65535,
}

KNOWN_FONT_NAMES = (
    "Microsoft YaHei",
    "Times New Roman",
    "Arial",
    "SimSun",
    "方正小标宋简体",
    "小标宋体",
    "宋体",
    "黑体",
    "楷体",
    "楷体_GB2312",
    "仿宋",
    "仿宋_GB2312",
    "微软雅黑",
)

FONT_STYLE_TOKENS = (
    "italic",
    "斜体",
    "红色",
    "蓝色",
    "绿色",
    "黑色",
    "白色",
    "黄色",
    "灰色",
    "字体",
    "font",
)

MARKDOWN_HEADING_STYLES = {
    1: {"font": "黑体", "size": 16, "bold": True},
    2: {"font": "楷体_GB2312", "size": 16, "bold": True},
    3: {"font": "仿宋_GB2312", "size": 16, "bold": True},
    4: {"font": "仿宋_GB2312", "size": 16, "bold": True},
}


def _clean_text(value: str | None) -> str:
    return str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()


def _safe_filename(value: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", value).strip(" ._")
    name = re.sub(r"\s+", "_", name)
    return (name[:60] or "wps_article").strip(" ._")


def _safe_file_stem(value: str) -> str:
    text = _clean_text(value)
    if not text:
        return ""
    text = re.sub(r"\.(?:docx?|pdf)$", "", text, flags=re.IGNORECASE)
    return _safe_filename(text)


def _normalize_windows_path(value: str | None) -> str | None:
    text = _clean_text(value)
    if not text:
        return None
    if re.match(r"^[A-Za-z]:[^\\/]", text):
        return f"{text[:2]}\\{text[2:]}"
    return text


def _int_or_default(value: int | str | None, default: int) -> int:
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    return number if number > 0 else default


def _normalize_font_name(value: str | None) -> str | None:
    text = _clean_text(value)
    if not text:
        return None
    lowered = text.lower()
    for font in KNOWN_FONT_NAMES:
        if font.lower() in lowered:
            return font
    for token in FONT_STYLE_TOKENS:
        text = re.sub(re.escape(token), "", text, flags=re.IGNORECASE)
    text = re.sub(r"\d+\s*号?", "", text).strip()
    return text or None


def _is_italic(value: bool | str | None) -> bool:
    if isinstance(value, bool):
        return value
    text = _clean_text(value).lower()
    return text in {"1", "true", "yes", "on"} or "italic" in text or "斜体" in text


def _font_color_value(value: int | str | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    text = _clean_text(value)
    if not text:
        return None
    lowered = text.lower()
    for name, color in WORD_COLOR_VALUES.items():
        if name.lower() in lowered:
            return color
    rgb_match = re.search(
        r"rgb\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*\)",
        text,
        re.IGNORECASE,
    )
    if rgb_match:
        red, green, blue = (min(255, int(value)) for value in rgb_match.groups())
        return red + (green << 8) + (blue << 16)
    hex_match = re.search(r"#?([0-9a-fA-F]{6})", text)
    if hex_match:
        rgb = int(hex_match.group(1), 16)
        red = (rgb >> 16) & 255
        green = (rgb >> 8) & 255
        blue = rgb & 255
        return red + (green << 8) + (blue << 16)
    try:
        return int(text)
    except ValueError:
        return None


def _paragraphs(body: str) -> list[str]:
    lines = []
    for line in _clean_text(body).split("\n"):
        text = line.strip()
        if text:
            lines.append(text)
    return lines


def _resolve_paths(
    title: str,
    output_dir: str | None = None,
    docx_path: str | None = None,
    pdf_path: str | None = None,
    file_name: str | None = None,
) -> tuple[Path, Path]:
    normalized_output_dir = _normalize_windows_path(output_dir)
    normalized_docx_path = _normalize_windows_path(docx_path)
    normalized_pdf_path = _normalize_windows_path(pdf_path)
    base_dir = (
        Path(normalized_output_dir).expanduser()
        if normalized_output_dir
        else DEFAULT_OUTPUT_DIR
    )
    base_dir.mkdir(parents=True, exist_ok=True)

    file_stem = _safe_file_stem(file_name or "")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    random_suffix = uuid.uuid4().hex[:6]
    base_name = file_stem or f"{_safe_filename(title)}_{stamp}_{random_suffix}"
    docx = (
        Path(normalized_docx_path).expanduser()
        if normalized_docx_path
        else Path(normalized_pdf_path).expanduser().with_suffix(".docx")
        if normalized_pdf_path
        else base_dir / f"{base_name}.docx"
    )
    pdf = (
        Path(normalized_pdf_path).expanduser()
        if normalized_pdf_path
        else Path(normalized_docx_path).expanduser().with_suffix(".pdf")
        if normalized_docx_path
        else base_dir / f"{base_name}.pdf"
    )
    docx.parent.mkdir(parents=True, exist_ok=True)
    pdf.parent.mkdir(parents=True, exist_ok=True)
    return docx.resolve(strict=False), pdf.resolve(strict=False)


def _dispatch_writer(
    dispatch_fn: Callable[[str], Any] | None = None,
) -> tuple[Any, str]:
    dispatchers: list[Callable[[str], Any]]
    if dispatch_fn is None:
        try:
            import win32com.client  # type: ignore[import-not-found]
        except Exception as exc:  # pragma: no cover - depends on Windows env
            raise RuntimeError(
                "WPS desktop export requires pywin32 on Windows."
            ) from exc
        dispatchers = [
            getattr(win32com.client, "DispatchEx", win32com.client.Dispatch),
            win32com.client.Dispatch,
        ]
    else:
        dispatchers = [dispatch_fn]

    errors: list[str] = []
    for prog_id in WPS_PROG_IDS:
        for current_dispatch in dispatchers:
            try:
                return current_dispatch(prog_id), prog_id
            except Exception as exc:
                errors.append(f"{prog_id}: {type(exc).__name__}: {exc}")

    detail = "; ".join(errors)
    raise RuntimeError(f"Unable to start WPS Writer or Word via COM. Tried {detail}")


def _set_attr(obj: Any, name: str, value: Any) -> None:
    try:
        setattr(obj, name, value)
    except Exception:
        pass


def _call(obj: Any, name: str, *args: Any, **kwargs: Any) -> Any:
    method = getattr(obj, name, None)
    if method is None:
        raise AttributeError(name)
    return method(*args, **kwargs)


def _set_font(
    selection: Any,
    font_name: str,
    size: int,
    bold: bool,
    italic: bool = False,
    underline: bool = False,
    color: int | None = None,
) -> None:
    font = getattr(selection, "Font", None)
    if font is None:
        return
    _set_attr(font, "Name", font_name)
    _set_attr(font, "Size", size)
    _set_attr(font, "Bold", -1 if bold else 0)
    _set_attr(font, "Italic", -1 if italic else 0)
    _set_attr(font, "Underline", 1 if underline else 0)
    if color is not None:
        _set_attr(font, "Color", color)


def _set_paragraph(selection: Any, alignment: int, first_line_indent: int = 0) -> None:
    paragraph = getattr(selection, "ParagraphFormat", None)
    if paragraph is None:
        return
    _set_attr(paragraph, "Alignment", alignment)
    _set_attr(paragraph, "FirstLineIndent", first_line_indent)
    _set_attr(paragraph, "LineSpacingRule", 5)


def _apply_numbering(selection: Any) -> bool:
    try:
        list_format = selection.Range.ListFormat
        list_format.ApplyNumberDefault()
        return True
    except Exception:
        return False


def _remove_numbering(selection: Any) -> None:
    try:
        selection.Range.ListFormat.RemoveNumbers()
    except Exception:
        pass


def _active_document(app: Any, fallback: Any) -> Any:
    try:
        active = app.ActiveDocument
        if active is not None:
            return active
    except Exception:
        pass
    return fallback


def _type_paragraph(selection: Any, text: str, numbered: bool = False) -> None:
    applied_numbering = _apply_numbering(selection) if numbered else False
    _call(selection, "TypeText", text)
    _call(selection, "TypeParagraph")
    if applied_numbering:
        _remove_numbering(selection)


def _markdown_inline_segments(text: str) -> list[dict[str, Any]]:
    """Parse supported Markdown and inline HTML into nested style segments."""

    patterns = (
        ("underline", re.compile(r"<u\b[^>]*>(.*?)</u\s*>", re.IGNORECASE | re.DOTALL)),
        (
            "span_color",
            re.compile(
                r"(<span\b[^>]*\bstyle\s*=\s*['\"][^'\"]*\bcolor\s*:[^'\"]*['\"][^>]*>)(.*?)</span\s*>",
                re.IGNORECASE | re.DOTALL,
            ),
        ),
        (
            "font_color",
            re.compile(
                r"(<font\b[^>]*\bcolor\s*=\s*(?:['\"][^'\"]+['\"]|[^\s>]+)[^>]*>)(.*?)</font\s*>",
                re.IGNORECASE | re.DOTALL,
            ),
        ),
        ("bold_italic", re.compile(r"\*\*\*(.+?)\*\*\*", re.DOTALL)),
        ("bold", re.compile(r"\*\*(.+?)\*\*", re.DOTALL)),
        ("bold_underscore", re.compile(r"__(.+?)__", re.DOTALL)),
        ("italic", re.compile(r"(?<!\*)\*([^*\n]+?)\*(?!\*)")),
        ("italic_underscore", re.compile(r"(?<!_)_([^_\n]+?)_(?!_)")),
    )

    def parse_color(opening_tag: str) -> int | None:
        match = re.search(r"\bcolor\s*:\s*([^;'\"]+)", opening_tag, re.IGNORECASE)
        if not match:
            match = re.search(
                r"\bcolor\s*=\s*['\"]?([^'\"\s>]+)",
                opening_tag,
                re.IGNORECASE,
            )
        return _font_color_value(match.group(1)) if match else None

    def append_segment(
        target: list[dict[str, Any]], content: str, style: dict[str, Any]
    ) -> None:
        if not content:
            return
        segment = {"text": content, **style}
        if target and all(
            target[-1].get(key) == segment.get(key)
            for key in ("bold", "italic", "underline", "color")
        ):
            target[-1]["text"] += content
        else:
            target.append(segment)

    def parse(value: str, inherited: dict[str, Any]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        cursor = 0
        while cursor < len(value):
            candidates = []
            for priority, (kind, pattern) in enumerate(patterns):
                match = pattern.search(value, cursor)
                if match:
                    candidates.append((match.start(), priority, kind, match))
            if not candidates:
                append_segment(result, value[cursor:], inherited)
                break

            _, _, kind, match = min(candidates, key=lambda item: (item[0], item[1]))
            append_segment(result, value[cursor : match.start()], inherited)
            nested_style = dict(inherited)
            if kind == "underline":
                nested_style["underline"] = True
                inner = match.group(1)
            elif kind in {"span_color", "font_color"}:
                parsed_color = parse_color(match.group(1))
                if parsed_color is not None:
                    nested_style["color"] = parsed_color
                inner = match.group(2)
            elif kind == "bold_italic":
                nested_style["bold"] = True
                nested_style["italic"] = True
                inner = match.group(1)
            elif kind in {"bold", "bold_underscore"}:
                nested_style["bold"] = True
                inner = match.group(1)
            else:
                nested_style["italic"] = True
                inner = match.group(1)

            for segment in parse(inner, nested_style):
                append_segment(result, segment["text"], segment)
            cursor = match.end()
        return result

    return parse(
        text,
        {"bold": False, "italic": False, "underline": False, "color": None},
    )


def _type_rich_paragraph(
    selection: Any,
    text: str,
    font_name: str,
    size: int,
    *,
    bold: bool = False,
    italic: bool = False,
    color: int | None = None,
    alignment: int = 0,
    first_line_indent: int = 0,
    numbered: bool = False,
) -> int:
    _set_paragraph(selection, alignment=alignment, first_line_indent=first_line_indent)
    applied_numbering = _apply_numbering(selection) if numbered else False
    inline_styles = 0
    for segment in _markdown_inline_segments(text):
        segment_bold = bool(segment.get("bold"))
        segment_italic = bool(segment.get("italic"))
        segment_underline = bool(segment.get("underline"))
        segment_color = segment.get("color")
        if segment_bold or segment_italic or segment_underline or segment_color is not None:
            inline_styles += 1
        _set_font(
            selection,
            font_name,
            size,
            bold or segment_bold,
            italic=italic or segment_italic,
            underline=segment_underline,
            color=segment_color if segment_color is not None else color,
        )
        _call(selection, "TypeText", segment["text"])
    _call(selection, "TypeParagraph")
    if applied_numbering:
        _remove_numbering(selection)
    return inline_styles


def _type_document_title(
    selection: Any,
    text: str,
    font_name: str,
    size: int,
    *,
    color: int | None = None,
) -> int:
    inline_styles = _type_rich_paragraph(
        selection,
        text,
        font_name,
        size,
        bold=False,
        color=color,
        alignment=1,
    )
    # 公文标题下空两行，再开始正文或主送机关。
    _call(selection, "TypeParagraph")
    _call(selection, "TypeParagraph")
    return inline_styles


def _read_markdown_file(markdown_path: str | None) -> tuple[str, str] | None:
    normalized = _normalize_windows_path(markdown_path)
    if not normalized:
        return None
    path = Path(normalized).expanduser().resolve(strict=False)
    if not path.exists():
        raise FileNotFoundError(f"Markdown file does not exist: {path}")
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return path.read_text(encoding=encoding), str(path)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace"), str(path)


def _first_markdown_heading(markdown_text: str) -> str | None:
    for line in markdown_text.splitlines():
        match = re.match(r"^\s{0,3}#{1,5}\s+(.+?)\s*#*\s*$", line)
        if match:
            return re.sub(r"[*_`]+", "", match.group(1)).strip() or None
    return None


def _without_first_markdown_heading(markdown_text: str) -> str:
    lines = markdown_text.splitlines()
    for index, line in enumerate(lines):
        if re.match(r"^\s{0,3}#\s+(.+?)\s*#*\s*$", line):
            return "\n".join(lines[:index] + lines[index + 1 :])
    return markdown_text


def _is_markdown_format(body_format: str | None) -> bool:
    value = _clean_text(body_format).lower()
    return value in {"markdown", "md", "markdown格式", "带格式"}


def _render_markdown(
    selection: Any,
    markdown_text: str,
    *,
    body_font: str,
    body_size: int,
    font_color: int | None = None,
    base_italic: bool = False,
) -> dict[str, int]:
    paragraph_count = 0
    heading_count = 0
    inline_style_count = 0
    list_item_pattern = re.compile(r"^\s*(?:\d+[.)、]|[-*•])\s+(.+)$")

    for raw_line in markdown_text.splitlines():
        line = raw_line.strip()
        if not line:
            _call(selection, "TypeParagraph")
            continue

        heading = re.match(r"^\s{0,3}(#{1,5})\s+(.+?)\s*#*\s*$", raw_line)
        if heading:
            level = len(heading.group(1))
            outline_level = 1 if level <= 2 else min(level - 1, 4)
            style = MARKDOWN_HEADING_STYLES[outline_level]
            inline_style_count += _type_rich_paragraph(
                selection,
                heading.group(2).strip(),
                str(style["font"]),
                int(style["size"]),
                bold=bool(style["bold"]),
                color=font_color,
            )
            heading_count += 1
            paragraph_count += 1
            continue

        list_item = list_item_pattern.match(line)
        if list_item:
            inline_style_count += _type_rich_paragraph(
                selection,
                list_item.group(1).strip(),
                body_font,
                body_size,
                italic=base_italic,
                color=font_color,
                first_line_indent=24,
                numbered=True,
            )
        else:
            inline_style_count += _type_rich_paragraph(
                selection,
                line,
                body_font,
                body_size,
                italic=base_italic,
                color=font_color,
                first_line_indent=24,
            )
        paragraph_count += 1

    return {
        "paragraph_count": paragraph_count,
        "heading_count": heading_count,
        "inline_style_count": inline_style_count,
    }


def _insert_image(selection: Any, image_path: str | None) -> str | None:
    normalized = _normalize_windows_path(image_path)
    if not normalized:
        return None
    path = Path(normalized).expanduser().resolve(strict=False)
    if not path.exists():
        raise FileNotFoundError(f"WPS image path does not exist: {path}")

    _call(selection, "TypeParagraph")
    containers = [
        getattr(selection, "InlineShapes", None),
        getattr(getattr(selection, "Range", None), "InlineShapes", None),
    ]
    for inline_shapes in containers:
        if inline_shapes is None:
            continue
        add_picture = getattr(inline_shapes, "AddPicture", None)
        if add_picture is None:
            continue
        try:
            add_picture(str(path), False, True)
        except TypeError:
            add_picture(str(path))
        _call(selection, "TypeParagraph")
        return str(path)
    raise RuntimeError("WPS Writer selection does not support InlineShapes.AddPicture")


def _save_docx(doc: Any, docx_path: Path) -> None:
    try:
        doc.SaveAs2(str(docx_path), FileFormat=DOCX_FORMAT)
        return
    except TypeError:
        pass
    except Exception:
        try:
            doc.SaveAs2(str(docx_path))
            return
        except Exception:
            pass

    try:
        doc.SaveAs(str(docx_path), FileFormat=DOCX_FORMAT)
    except TypeError:
        doc.SaveAs(str(docx_path))


def _export_pdf(doc: Any, pdf_path: Path) -> None:
    try:
        doc.ExportAsFixedFormat(str(pdf_path), PDF_FORMAT)
        return
    except Exception:
        pass

    try:
        doc.SaveAs2(str(pdf_path), FileFormat=PDF_FORMAT)
    except TypeError:
        doc.SaveAs2(str(pdf_path), PDF_FORMAT)


def export_article_to_pdf(
    title: str,
    body: str,
    output_dir: str | None = None,
    docx_path: str | None = None,
    pdf_path: str | None = None,
    file_name: str | None = None,
    markdown_path: str | None = None,
    body_format: str | None = None,
    keep_open: bool = True,
    visible: bool = True,
    font_name: str | None = None,
    font_size: int | str | None = None,
    title_font_name: str | None = None,
    title_font_size: int | str | None = None,
    body_font_name: str | None = None,
    body_font_size: int | str | None = None,
    font_color: int | str | None = None,
    italic: bool | str | None = None,
    image_path: str | None = None,
    output_format: str | None = "both",
    dispatch_fn: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    """Create a formatted WPS/Word document and save the requested output files."""

    markdown_data = _read_markdown_file(markdown_path)
    markdown_text = markdown_data[0] if markdown_data else None
    normalized_markdown_path = markdown_data[1] if markdown_data else None
    body_is_markdown = _is_markdown_format(body_format)
    markdown_title = _first_markdown_heading(markdown_text) if markdown_text else None

    title_text = _clean_text(title) or markdown_title or "未命名文档"
    body_text = _clean_text(body)
    if not body_text and markdown_text is None:
        raise ValueError("WPS export requires article body content")
    legacy_font = _normalize_font_name(font_name)
    body_font = _normalize_font_name(body_font_name) or legacy_font or "仿宋_GB2312"
    body_size_source = body_font_size if body_font_size is not None else font_size
    body_size = _int_or_default(body_size_source, 16)
    title_font = _normalize_font_name(title_font_name) or legacy_font or "方正小标宋简体"
    title_size = _int_or_default(title_font_size, 22)
    font_color_value = _font_color_value(font_color)
    italic_enabled = _is_italic(italic)
    normalized_output_format = str(output_format or "both").strip().lower()
    output_format_aliases = {
        "pdf": "pdf",
        "word": "word",
        "doc": "word",
        "docx": "word",
        "both": "both",
        "all": "both",
        "两种": "both",
        "两种形式": "both",
        "pdf和word": "both",
        "pdf 和 word": "both",
    }
    normalized_output_format = output_format_aliases.get(normalized_output_format)
    if normalized_output_format is None:
        raise ValueError("output_format must be one of: pdf, word, both")

    docx, pdf = _resolve_paths(title_text, output_dir, docx_path, pdf_path, file_name)
    app, provider = _dispatch_writer(dispatch_fn)
    _set_attr(app, "Visible", bool(visible))
    _set_attr(app, "DisplayAlerts", 0)

    doc = _active_document(app, app.Documents.Add())
    selection = app.Selection

    paragraph_count = 0
    heading_count = 0
    inline_style_count = 0
    if markdown_text is not None:
        inline_style_count += _type_document_title(
            selection,
            title_text,
            title_font,
            title_size,
            color=font_color_value,
        )
        paragraph_count += 1
        heading_count += 1
        markdown_body = (
            _without_first_markdown_heading(markdown_text)
            if markdown_title
            else markdown_text
        )
        markdown_result = _render_markdown(
            selection,
            markdown_body,
            body_font=body_font,
            body_size=body_size,
            font_color=font_color_value,
            base_italic=italic_enabled,
        )
        paragraph_count += markdown_result["paragraph_count"]
        heading_count += markdown_result["heading_count"]
        inline_style_count += markdown_result["inline_style_count"]
    elif body_is_markdown:
        inline_style_count += _type_document_title(
            selection,
            title_text,
            title_font,
            title_size,
            color=font_color_value,
        )
        paragraph_count += 1
        heading_count += 1
        markdown_result = _render_markdown(
            selection,
            body_text,
            body_font=body_font,
            body_size=body_size,
            font_color=font_color_value,
            base_italic=italic_enabled,
        )
        paragraph_count += markdown_result["paragraph_count"]
        heading_count += markdown_result["heading_count"]
        inline_style_count += markdown_result["inline_style_count"]
    else:
        _type_document_title(
            selection,
            title_text,
            title_font,
            title_size,
            color=font_color_value,
        )

        _set_font(
            selection,
            body_font,
            body_size,
            False,
            italic=italic_enabled,
            color=font_color_value,
        )
        _set_paragraph(selection, alignment=0, first_line_indent=24)

        list_item_pattern = re.compile(r"^\s*(?:\d+[.)、]|[-*•])\s*(.+)$")
        for paragraph in _paragraphs(body_text):
            match = list_item_pattern.match(paragraph)
            if match:
                _type_paragraph(selection, match.group(1).strip(), numbered=True)
            else:
                _type_paragraph(selection, paragraph)
            paragraph_count += 1

    inserted_image_path = _insert_image(selection, image_path)

    saved_docx = None
    saved_pdf = None
    if normalized_output_format in {"word", "both"}:
        _save_docx(doc, docx)
        saved_docx = str(docx)
    if normalized_output_format in {"pdf", "both"}:
        _export_pdf(doc, pdf)
        saved_pdf = str(pdf)

    if not keep_open:
        try:
            doc.Close(False)
        finally:
            try:
                app.Quit()
            except Exception:
                pass

    return {
        "success": True,
        "provider": provider,
        "title": title_text,
        "docx_path": saved_docx,
        "pdf_path": saved_pdf,
        "output_format": normalized_output_format,
        "paragraph_count": paragraph_count,
        "heading_count": heading_count,
        "inline_style_count": inline_style_count,
        "font_name": body_font,
        "font_size": body_size,
        "title_font_name": title_font,
        "title_font_size": title_size,
        "body_font_name": body_font,
        "body_font_size": body_size,
        "font_color": font_color_value,
        "italic": italic_enabled,
        "image_path": inserted_image_path,
        "markdown_path": normalized_markdown_path,
        "body_format": "markdown" if body_is_markdown else "plain",
        "keep_open": keep_open,
    }

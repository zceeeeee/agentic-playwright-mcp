"""WPS Writer article creation and PDF export skill."""


def _default_log(message):
    print(f"[LOG] {message}")


def _resolve_log(log_fn=None):
    if log_fn is not None:
        return log_fn
    try:
        return log
    except Exception:
        return _default_log


def _value(value):
    if value is None:
        return None
    text = str(value).strip()
    if not text or text == "-1":
        return None
    return text


def run(
    title="-1",
    body="-1",
    output_dir="-1",
    docx_path="-1",
    pdf_path="-1",
    file_name="-1",
    markdown_path="-1",
    font_name="-1",
    font_size="-1",
    font_color="-1",
    italic="-1",
    image_path="-1",
    keep_open=True,
    log_fn=None,
    export_fn=None,
):
    """Create a WPS/Word article document, save it, and export it as PDF."""

    logger = _resolve_log(log_fn)
    md_path = _value(markdown_path)
    title_text = _value(title) or ("" if md_path else "未命名文档")
    body_text = _value(body)
    if not body_text and not md_path:
        raise ValueError("WPS export requires body content")

    if export_fn is None:
        try:
            export_fn = wps_writer_export
        except Exception as exc:
            raise RuntimeError("wps_writer_export is not registered") from exc

    logger("Opening WPS Writer and creating formatted document")
    result = export_fn(
        title=title_text,
        body=body_text,
        output_dir=_value(output_dir),
        docx_path=_value(docx_path),
        pdf_path=_value(pdf_path),
        file_name=_value(file_name),
        markdown_path=md_path,
        font_name=_value(font_name),
        font_size=_value(font_size),
        font_color=_value(font_color),
        italic=_value(italic),
        image_path=_value(image_path),
        keep_open=keep_open,
    )
    if not result or not result.get("success"):
        raise RuntimeError("WPS Writer export failed")

    logger(f"WPS document saved: {result.get('docx_path')}")
    logger(f"WPS PDF exported: {result.get('pdf_path')}")
    return result

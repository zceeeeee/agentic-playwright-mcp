"""Polish and reformat an existing local WPS Writer document."""


def _default_log(message):
    print(f"[LOG] {message}")


def _is_yes(answer):
    value = str(answer or "").strip().lower()
    return value in ("yes", "y", "1", "true", "是", "需要", "要", "确认")


def _strip_markdown_fence(text):
    value = str(text or "").strip()
    if value.startswith("```"):
        first_newline = value.find("\n")
        if first_newline >= 0:
            value = value[first_newline + 1 :]
        if value.rstrip().endswith("```"):
            value = value.rstrip()[:-3]
    return value.strip()


def _generate_markdown(source_text, instruction, generate_fn):
    chunk_size = 5000
    parts = []
    total = len(source_text)
    start = 0
    part_number = 1
    while start < total:
        chunk = source_text[start : start + chunk_size]
        structure_note = (
            "这是文档开头；若第一行是标题，请使用 # 标记文档标题。"
            if part_number == 1
            else "这是文档后续部分；不要新增或重复文档总标题。"
        )
        prompt = (
            f"{instruction}\n\n"
            f"这是文档第 {part_number} 部分。只返回处理后的 Markdown 正文，"
            f"不要使用代码块，不要解释，不要遗漏原文信息。{structure_note}\n\n"
            f"原文：\n{chunk}"
        )
        generated = _strip_markdown_fence(generate_fn(prompt))
        if not generated:
            raise RuntimeError(f"LLM returned empty text for document part {part_number}")
        parts.append(generated)
        start += chunk_size
        part_number += 1
    return "\n\n".join(parts)


def _normalize_table_placeholder(markdown):
    placeholder = "[[WPS_TABLE_1]]"
    if placeholder not in markdown:
        return markdown
    before, after = markdown.split(placeholder, 1)
    after = after.replace(placeholder, "")
    return before.rstrip() + "\n\n" + placeholder + "\n\n" + after.lstrip()


def _generate_table_json(markdown, generate_fn):
    prompt = (
        "下面是一篇已经润色的 WPS 文档，其中 [[WPS_TABLE_1]] 表示需要插入真实表格的位置。\n"
        "请结合全文生成该表格的数据。只返回严格 JSON，不要使用 Markdown 代码块，不要解释。\n"
        "JSON 必须采用以下结构："
        '{"tables":[{"placeholder":"[[WPS_TABLE_1]]",'
        '"title":"表格标题","columns":["列1","列2"],'
        '"rows":[["值1","值2"]],'
        '"style":{"header_bold":true,"border":"grid","auto_fit":true}}]}。\n'
        "要求：只生成一个表格；列数 2 到 8；数据行不超过 20；"
        "每行列数必须与 columns 一致；只能使用原文已有信息或明确标注为概括，"
        "不得编造精确数据。\n\n"
        f"文档内容：\n{markdown}"
    )
    table_json = _strip_markdown_fence(generate_fn(prompt))
    if '"tables"' not in table_json or "[[WPS_TABLE_1]]" not in table_json:
        raise RuntimeError("LLM returned invalid WPS table JSON")
    return table_json


def run(
    document_path="-1",
    keep_open=True,
    log_fn=None,
    read_fn=None,
    rewrite_fn=None,
    prompt_fn=None,
    generate_fn=None,
):
    """Optionally polish and format one existing WPS document in place."""

    logger = log_fn
    if logger is None:
        try:
            logger = log
        except Exception:
            logger = _default_log
    reader = read_fn
    if reader is None:
        try:
            reader = wps_document_read
        except Exception as exc:
            raise RuntimeError("wps_document_read is not registered") from exc
    rewriter = rewrite_fn
    if rewriter is None:
        try:
            rewriter = wps_document_rewrite
        except Exception as exc:
            raise RuntimeError("wps_document_rewrite is not registered") from exc
    prompt = prompt_fn
    if prompt is None:
        try:
            prompt = panel_prompt
        except Exception as exc:
            raise RuntimeError("panel_prompt is not registered") from exc
    generate = generate_fn
    if generate is None:
        try:
            generate = llm_generate_text
        except Exception as exc:
            raise RuntimeError("llm_generate_text is not registered") from exc

    path = str(document_path or "").strip()
    if not path or path == "-1":
        path = str(prompt("请输入已有 WPS 文档的完整路径：") or "").strip()
    if not path:
        raise ValueError("WPS document path is required")

    logger(f"Reading WPS document: {path}")
    read_result = reader(path)
    source_text = str((read_result or {}).get("text") or "").strip()
    if not source_text:
        raise ValueError("The WPS document contains no readable text")

    polish = _is_yes(prompt("是否需要 AI 润色文档文字？[yes] [no]（默认 no）"))
    reformat = _is_yes(prompt("是否需要 AI 修改文档格式？[yes] [no]（默认 no）"))

    markdown = source_text
    table_json = "-1"
    if polish:
        markdown = _generate_markdown(
            markdown,
            (
                "请润色下面的中文文档：改善语句、衔接和用词，纠正病句与错别字，"
                "但不得虚构事实、改变原意或删除关键信息。保留标题和段落结构。"
                "同时判断把原文中的信息整理成一个表格是否能明显提升可读性。"
                "仅在确实适合插入表格时，在最合适的位置单独输出一行 "
                "[[WPS_TABLE_1]]；不要输出 Markdown 表格。若不适合则不要输出占位符。"
                "当前模型不支持生成图片；不得添加图片、配图建议或任何图片占位符。"
            ),
            generate,
        )
        markdown = _normalize_table_placeholder(markdown)

    format_requirements = ""
    if reformat:
        format_requirements = str(
            prompt(
                "请输入格式要求；可直接回车使用默认公文格式（标题二号小标宋居中，"
                "正文三号仿宋，一级标题三号黑体，二级标题三号楷体加粗）："
            )
            or ""
        ).strip()
        if not format_requirements:
            format_requirements = (
                "标题使用二号小标宋并居中，标题下空二行；正文使用三号仿宋；"
                "一级标题使用三号黑体；二级标题使用三号楷体并加粗。"
            )
        markdown = _generate_markdown(
            markdown,
            (
                "请在不改变文字内容和顺序的前提下，将文档转换为完整 Markdown。"
                "使用 #、##、### 表示标题层级，使用 **粗体**、*斜体*、<u>下划线</u> "
                "和 <span style=\"color: ...\">彩色文字</span> 表达需要的行内格式。"
                "如果正文中存在 [[WPS_TABLE_1]]，必须原样保留且不能移动。"
                "不得添加图片、配图建议或任何图片占位符。"
                f"用户格式要求：{format_requirements}"
            ),
            generate,
        )

    if polish and "[[WPS_TABLE_1]]" in markdown:
        markdown = _normalize_table_placeholder(markdown)
        table_json = _generate_table_json(markdown, generate)

    if not polish and not reformat:
        logger("No WPS document changes requested")
        return {
            "success": True,
            "modified": False,
            "document_path": path,
            "backup_path": None,
        }

    logger("Backing up and rewriting the WPS document")
    if table_json == "-1":
        result = rewriter(path, markdown, keep_open=keep_open)
    else:
        result = rewriter(
            path,
            markdown,
            table_json=table_json,
            keep_open=keep_open,
        )
    if not result or not result.get("success"):
        raise RuntimeError("WPS document rewrite failed")
    result["modified"] = True
    result["polished"] = polish
    result["reformatted"] = reformat
    result["table_inserted"] = table_json != "-1"
    result["format_requirements"] = format_requirements
    logger(f"WPS document updated: {result.get('document_path')}")
    logger(f"Original document backup: {result.get('backup_path')}")
    return result

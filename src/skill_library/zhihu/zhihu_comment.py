SIGN_URL="https://www.zhihu.com/signin"

def _js_string(value: str) -> str:
    text = str(value)
    text = text.replace("\\", "\\\\")
    text = text.replace('"', '\\"')
    text = text.replace("\n", "\\n")
    text = text.replace("\r", "\\r")
    return f'"{text}"'


def _is_ai_mode(answer) -> bool:
    text = str(answer or "").strip().lower()
    if not text:
        return False
    for token in ("手动", "manual", "confirm", "确认"):
        if token in text:
            return False
    for token in ("ai", "生成", "智能", "auto", "yes", "true", "1"):
        if token in text:
            return True
    return False


def _extract_article_text() -> str:
    script = """(() => {
        const clean = (value) => String(value || "")
            .replace(/\\s+/g, " ")
            .trim();

        const isVisible = (el) => {
            if (!el) return false;
            const style = window.getComputedStyle(el);
            if (style.display === "none" || style.visibility === "hidden") return false;
            const rect = el.getBoundingClientRect();
            return rect.width > 0 && rect.height > 0;
        };

        const paragraphSelectors = [
            "span#content p",
            "#content p",
            ".RichContent p",
            ".RichContent-inner p",
            ".Post-RichText p",
            ".QuestionRichText p",
            "article p",
        ];

        const paragraphs = [];
        for (const selector of paragraphSelectors) {
            for (const el of document.querySelectorAll(selector)) {
                if (!isVisible(el)) continue;
                const text = clean(el.innerText || el.textContent);
                if (text) paragraphs.push(text);
            }
            if (paragraphs.length >= 2) break;
        }

        if (paragraphs.length) {
            return paragraphs.join("\\n").slice(0, 6000);
        }

        const containerSelectors = [
            "span#content",
            "#content",
            ".RichContent .RichText",
            ".RichContent",
            ".Post-RichText",
            ".QuestionRichText",
            "article",
        ];
        for (const selector of containerSelectors) {
            const el = document.querySelector(selector);
            if (!isVisible(el)) continue;
            const text = clean(el.innerText || el.textContent);
            if (text) return text.slice(0, 6000);
        }

        return "";
    })()"""
    last_error = ""
    for _ in range(10):
        try:
            text = run_js(script)
            text = str(text or "").strip()
            if text:
                return text
        except Exception as exc:
            last_error = str(exc)
        wait(1)
    if last_error:
        log(f"Zhihu article text extract retry failed: {last_error}")
    return ""


def _generate_comment_from_article(current_keyword: str, requirement_text: str = "") -> str:
    article_text = _extract_article_text()
    if not article_text:
        if current_keyword and current_keyword != "-1":
            return current_keyword
        raise RuntimeError("Zhihu article text not found for AI comment generation")

    prompt = (
        "请根据下面的知乎文章内容生成一条中文评论。\n"
        "要求：自然、具体、像真人评论，不要提到你是 AI，不要复述整篇文章。\n"
        f"用户额外要求：{requirement_text or '无'}\n\n"
        f"文章内容：\n{article_text}\n\n"
        "只输出评论正文。"
    )
    try:
        comment = str(llm_generate_text(prompt) or "").strip()
    except Exception as exc:
        if current_keyword and current_keyword != "-1":
            return current_keyword
        raise RuntimeError(f"AI comment generation failed: {exc}")

    if comment:
        return comment

    if current_keyword and current_keyword != "-1":
        return current_keyword
    raise RuntimeError("AI comment generation returned empty text")


def _prepare_comment_request(keyword: str):
    current = str(keyword or "").strip()
    try:
        panel_show()
    except Exception:
        pass
    mode = panel_prompt("知乎评论内容请选择输入方式：[AI生成] [手动输入/确认]")
    if _is_ai_mode(mode):
        requirement = panel_prompt(
            "请输入评论生成要求（可选，直接回车跳过）。例如：简短、赞同作者、提出不同观点："
        )
        return True, current, str(requirement or "").strip()

    elif not current or current == "-1":
        current = str(panel_prompt("请输入要发布的知乎评论内容：") or "").strip()

    if not current or current == "-1":
        raise RuntimeError("Missing Zhihu comment content")
    return False, current, ""


def run(keyword: str, article_url: str = ""):
    """Open Zhihu article page and fill the comment editor with keyword."""
    article_url = str(article_url or "").strip()
    if not article_url:
        raise RuntimeError("Missing Zhihu article URL for comment")

    if not ensure_auth("zhihu", SIGN_URL):
        log("Zhihu login state not confirmed; skip comment")
        return

    use_ai, keyword, requirement_text = _prepare_comment_request(keyword)

    goto(article_url)
    wait_for_element(".RichContent, #content, article, .Post-RichText", timeout=30)
    wait(2)
    if use_ai:
        keyword = _generate_comment_from_article(keyword, requirement_text)

    editor_selector = ".Comments-container .public-DraftEditor-content[contenteditable='true']"
    wait_for_element(editor_selector, timeout=20)

    review_text = _js_string(keyword)
    run_js(
        f"""(() => {{
            const text = {review_text};
            const editor =
                document.querySelector("{editor_selector}") ||
                document.querySelector(".Comments-container [role='textbox'][contenteditable='true']");
            if (!editor) return "Zhihu review editor not found";

            editor.focus();

            const offsetSpan = editor.querySelector(
                "div[data-contents='true'] .Editable-unstyled " +
                "div[data-offset-key] > span[data-offset-key]"
            );
            if (!offsetSpan) return "Zhihu review offset span not found";

            const offsetKey = offsetSpan.getAttribute("data-offset-key") || "";
            offsetSpan.innerHTML = "";

            const textSpan = document.createElement("span");
            textSpan.setAttribute("data-text", "true");
            if (offsetKey) {{
                textSpan.setAttribute("data-offset-key", offsetKey);
            }}
            textSpan.textContent = text;
            offsetSpan.appendChild(textSpan);

            editor.dispatchEvent(new InputEvent("input", {{
                bubbles: true,
                cancelable: true,
                inputType: "insertText",
                data: text,
            }}));
            editor.dispatchEvent(new Event("change", {{ bubbles: true }}));
            return textSpan.outerHTML;
        }})()"""
    )
    wait_for_element(editor_selector, timeout=100)
    click(editor_selector)

    publish_selector = "button.Button.Button--primary.Button--blue.css-pbx6oc"
    wait_for_element(publish_selector, timeout=100)
    click(publish_selector)
    wait(2)

    log(f"Zhihu review published: {keyword}")

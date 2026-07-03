REVIEW_URL = "https://zhuanlan.zhihu.com/p/2055675816818774461"
SIGN_URL="https://www.zhihu.com/signin"

def _js_string(value: str) -> str:
    text = str(value)
    text = text.replace("\\", "\\\\")
    text = text.replace('"', '\\"')
    text = text.replace("\n", "\\n")
    text = text.replace("\r", "\\r")
    return f'"{text}"'


def run(keyword: str):
    """Open Zhihu article page and fill the comment editor with keyword."""
    if not ensure_auth("zhihu", SIGN_URL):
        log("Zhihu login state not confirmed; skip comment")
        return

    goto(REVIEW_URL)

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

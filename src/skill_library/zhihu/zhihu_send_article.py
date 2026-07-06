"""Zhihu article publishing adapter.
目前 我需要上层给我发的标题 和内容 """


WRITE_URL = "https://zhuanlan.zhihu.com/write"
SIGN_URL="https://www.zhihu.com/signin"

def _js_string(value: str) -> str:
    text = str(value)
    text = text.replace("\\", "\\\\")
    text = text.replace('"', '\\"')
    text = text.replace("\n", "\\n")
    text = text.replace("\r", "\\r")
    return f'"{text}"'


def run(title: str, keyword: str):
    """Open Zhihu writer, fill article title/body, and click publish."""
    if not ensure_auth("zhihu", SIGN_URL):
        log("Zhihu login state not confirmed; skip article publish")
        return

    goto(WRITE_URL)
    wait_for_element("div.WriteIndex-pageTitle", timeout=300)

    fill(
        "textarea.Input.i7cW1UcwT6ThdhTakqFm",
        title,
        "textarea[placeholder*='100']",
    )

    wait_for_element(".DraftEditor-root", timeout=15)
    body_text = _js_string(keyword)
    run_js(
        f"""(() => {{
            const text = {body_text};
            const root = document.querySelector(".DraftEditor-root");
            if (!root) return "DraftEditor root not found";

            const editor =
                root.querySelector("[contenteditable='true']") ||
                root.querySelector(".public-DraftEditor-content");
            if (!editor) return "DraftEditor content not found";

            editor.focus();
            const offsetSpan = editor.querySelector(
                "div[data-contents='true'] .Editable-unstyled " +
                "div[data-offset-key] > span[data-offset-key]"
            );
            if (!offsetSpan) return "DraftEditor offset span not found";

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

    wait_for_element("button.Button--primary", timeout=15)
    click("button.Button--primary")
    wait(2)

    log(f"Zhihu article publish clicked: {title}")

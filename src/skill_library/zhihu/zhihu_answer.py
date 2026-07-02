ANSWER_URL = "https://www.zhihu.com/question/2054905087156342820"


def _js_string(value: str) -> str:
    text = str(value)
    text = text.replace("\\", "\\\\")
    text = text.replace('"', '\\"')
    text = text.replace("\n", "\\n")
    text = text.replace("\r", "\\r")
    return f'"{text}"'


def run(keyword: str):
    """Open Zhihu question page, write an answer, and publish it."""
    goto(ANSWER_URL)

    answer_button = "button.Button.Button--blue"
    wait_for_element(answer_button, timeout=20)
    run_js(
        """(() => {
            const buttons = Array.from(document.querySelectorAll("button.Button.Button--blue"));
            const button = buttons.find((item) => {
                const text = (item.textContent || "").trim();
                const label = (item.getAttribute("aria-label") || "").trim();
                return text.includes("写回答") || label.includes("写回答");
            });
            if (!button) return "Zhihu answer button not found";
            button.scrollIntoView({ block: "center", inline: "center" });
            button.click();
            return "Zhihu answer button clicked";
        })()"""
    )

    editor_selector = ".AnswerForm .public-DraftEditor-content[contenteditable='true']"
    wait_for_element(editor_selector, timeout=20)

    answer_text = _js_string(keyword)
    run_js(
        f"""(() => {{
            const text = {answer_text};
            const editor =
                document.querySelector("{editor_selector}") ||
                document.querySelector(".AnswerForm [role='textbox'][contenteditable='true']");
            if (!editor) return "Zhihu answer editor not found";

            editor.focus();

            const offsetSpan = editor.querySelector(
                "div[data-contents='true'] .Editable-unstyled " +
                "div[data-offset-key] > span[data-offset-key]"
            );
            if (!offsetSpan) return "Zhihu answer offset span not found";

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
    wait_for_element(editor_selector, timeout=20)
    click(editor_selector)
    wait(2)

    publish_selector = "button.Button.Button--primary.Button--blue.css-78nr5c"
    wait_for_element(publish_selector, timeout=20)
    click(publish_selector)
    wait(2)

    log(f"Zhihu answer published: {keyword}")
    close_browser()

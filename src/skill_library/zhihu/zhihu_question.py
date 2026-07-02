"""知乎提问题适配器。"""

def run(keyword: str = "-1"):
    """打开知乎首页，填写问题并发布。"""
    goto("https://www.zhihu.com/")

    wait_for_element("body", timeout=20)
    run_js(
        """(() => {
            const candidates = Array.from(document.querySelectorAll("div, button, a"));
            const target = candidates.find((item) => {
                const text = (item.textContent || "").trim();
                const label = (item.getAttribute("aria-label") || "").trim();
                return text === "提问题" || label === "提问题";
            });
            if (!target) return "Zhihu question button not found";
            target.scrollIntoView({ block: "center", inline: "center" });
            target.click();
            return "Zhihu question button clicked";
        })()"""
    )

    question_input = "textarea.Input[required]"
    wait_for_element(question_input, timeout=20)

    click(question_input)
    fill(question_input, keyword)
    click(question_input)

    publish_button = "button.Button.Button--primary.Button--blue"
    wait_for_element(publish_button, timeout=20)
    run_js(
        """(() => {
            const buttons = Array.from(document.querySelectorAll("button.Button.Button--primary.Button--blue"));
            const button = buttons.find((item) => {
                const text = (item.textContent || "").trim();
                const label = (item.getAttribute("aria-label") || "").trim();
                return text.includes("发布问题") || label.includes("发布问题");
            });
            if (!button) return "Zhihu publish question button not found";
            button.scrollIntoView({ block: "center", inline: "center" });
            button.click();
            return "Zhihu publish question button clicked";
        })()"""
    )

    log(f"Zhihu question published: {keyword}")
    close_browser()

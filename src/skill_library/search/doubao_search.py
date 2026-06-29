"""Doubao search/chat adapter."""


def run(keyword: str):
    """Open Doubao chat, type the keyword into the chat box, and submit it."""
    goto("https://www.doubao.com/chat/")
    wait_for_element("textarea.semi-input-textarea", timeout=15)

    click("textarea.semi-input-textarea")
    wait(0.5)
    fill(
        "textarea.semi-input-textarea",
        keyword,
        "textarea[placeholder*='发消息']",
        "textarea[role='textbox']",
    )
    wait(0.5)
    wait_for_element("#flow-end-msg-send", timeout=10)
    click("#flow-end-msg-send")
    wait(2)

    log(f"Doubao input submitted: {keyword}")

""""doubao 搜索适配器"""
def run(keyword: str):
    """在doubao搜索关键词。

    Args:
        keyword: 搜索关键词。

    流程:
        
    """
    goto("https://www.doubao.com/chat/")
    wait_for_navigation()
    fill(
        "textarea.semi-input-textarea",
        keyword,
        "textarea[placeholder*='发消息']",
        "textarea[role='textbox']"
    )
    press("Enter")

    wait_for_navigation()
    log(f"输入完成: {keyword}")

"""知乎 搜索适配器。"""

SIGN_URL="https://www.zhihu.com/signin"

def run(keyword: str):
    """在知乎搜索关键词。

    Args:
        keyword: 搜索关键词。

    流程:
        1. 构造知乎搜索结果页 URL
        2. 直接导航到结果页
    """
    encoded_keyword = url_quote(keyword)
    target_url = f"https://www.zhihu.com/search?q={encoded_keyword}"

    if not ensure_auth("zhihu", SIGN_URL):
        log("Zhihu login state not confirmed; skip search navigation")
        return

    goto(target_url)
    log(f"知乎搜索完成: {keyword}")

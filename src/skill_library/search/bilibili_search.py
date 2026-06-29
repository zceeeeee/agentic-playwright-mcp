"""Bilibili search adapter."""


def run(keyword: str):
    """Search Bilibili for a keyword.

    Args:
        keyword: Search keyword.
    """
    query = url_quote(keyword)
    goto(f"https://search.bilibili.com/all?keyword={query}")
    log(f"Bilibili 搜索完成: {keyword}")


# Selector fallback notes for interactive search mode:
# search_input: .nav-search-input -> input[placeholder*='搜索']
# search_button: .nav-search-btn -> .search-btn

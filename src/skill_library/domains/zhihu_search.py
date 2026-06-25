"""知乎搜索适配器。"""


def run(keyword: str):
    """在知乎搜索。

    Args:
        keyword: 搜索关键词。

    流程:
        1. 构造知乎搜索结果页 URL
        2. 直接导航到结果页
    """
    query = url_quote(keyword)
    goto(f"https://www.zhihu.com/search?type=content&q={query}")
    log(f"知乎搜索完成: {keyword}")


# 选择器备选方案:
# search_input: .Input-wrapper input → input[name='q'] → #Popover1-toggle
# search_button: .SearchBar-searchButton → button[type='submit']

""""淘宝 搜索适配器"""
def run(keyword: str):
    """在淘宝搜索关键词。

    Args:
        keyword: 搜索关键词。

    流程:
        1. 构造b站搜索结果页 URL
        2. 直接导航到结果页
    """
    goto(f"https://s.taobao.com/search?q={keyword}")
    log(f"淘宝搜索完成: {keyword}")
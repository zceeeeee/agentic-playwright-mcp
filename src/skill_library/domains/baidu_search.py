"""百度搜索适配器 —— 直接执行或作为范例参考。"""


def run(keyword: str):
    """在百度搜索关键词。

    Args:
        keyword: 搜索关键词。

    流程:
        1. 构造百度搜索结果页 URL
        2. 直接导航到结果页
    """
    query = url_quote(keyword)
    goto(f"https://www.baidu.com/s?wd={query}")
    log(f"百度搜索完成: {keyword}")


# 选择器备选方案（注释即文档）:
# search_input: #kw → input[name='wd'] → .s_ipt
# search_button: #su → input[type='submit'] → .btn-search

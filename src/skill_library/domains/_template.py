"""【技能名称】适配器 —— 直接执行或作为范例参考。

使用方法:
    1. 复制本文件，重命名为 {site_name}.py
    2. 修改 run() 函数实现
    3. 在 skills.yaml 中注册
    4. 创建 domains/{site_name}.yaml 域配置
    5. 运行测试: python -m pytest tests/test_skill_{site_name}.py
"""


def run(keyword: str):
    """【功能描述】。

    Args:
        keyword: 【参数说明】。

    流程:
        1. 导航到目标页面
        2. 【步骤2】
        3. 【步骤3】
        4. 等待结果
    """
    # 1. 导航
    goto("https://example.com")
    wait_for_navigation()

    # 2. 填写搜索框
    fill("#search", keyword)           # 主选择器

    # 3. 点击按钮
    click("#search-btn")               # 主选择器

    # 4. 等待结果
    wait_for_navigation()
    log(f"操作完成: {keyword}")


# 选择器备选方案（注释即文档）:
# search_input: #search → input[name='q'] → .search-input
# search_button: #search-btn → button[type='submit'] → .btn-search

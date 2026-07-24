"""BOSS 直聘搜索适配器。

在 BOSS 直聘搜索指定关键词，支持城市筛选、多页数据采集、
LLM 分析总结和 PDF 报告导出。

注意：此文件在脚本沙箱中执行，不能使用 import。
所有正则和复杂逻辑在 layer_3/boss_results.py 中处理。
"""


def _jobs_to_text(jobs: list) -> str:
    """将职位列表格式化为文本，供 LLM 分析。"""
    lines = []
    for i, job in enumerate(jobs, 1):
        parts = [str(i) + ". " + str(job.get("title", ""))]
        if job.get("company"):
            parts.append("   公司: " + str(job["company"]))
        if job.get("salary"):
            parts.append("   薪资: " + str(job["salary"]))
        if job.get("area"):
            parts.append("   地点: " + str(job["area"]))
        if job.get("tags"):
            parts.append("   要求: " + str(job["tags"]))
        lines.append("\n".join(parts))
    return "\n\n".join(lines)


def run(keyword: str, max_pages=5):
    """在 BOSS 直聘搜索职位，滚动采集数据，分析并导出 PDF 报告。

    BOSS 直聘使用无限滚动加载，没有翻页按钮。
    max_pages 按每页约 4 个卡片换算目标数量（如 max_pages=5 → 目标 20 个卡片）。

    Args:
        keyword: 搜索内容，包含城市和职位关键词（如 "深圳的AI产品经理"）。
        max_pages: 逻辑页数，默认 5（目标 5×4=20 个卡片）。
    """
    # 1. 解析关键词
    keyword = str(keyword or "").strip()
    if not keyword or keyword == "-1":
        raise ValueError("BOSS直聘搜索需要职位关键词")

    # 确保 max_pages 是整数（技能路由可能传入字符串）
    try:
        max_pages = int(max_pages)
    except (TypeError, ValueError):
        max_pages = 5

    search_url, city, pure_keyword = build_boss_search_url(keyword)

    # 2. 登录检查 — 先打开 BOSS 首页，等待用户完成登录
    goto("https://www.zhipin.com")
    wait(2)
    panel_show()
    panel_prompt(
        "请在浏览器中完成 BOSS 直聘登录，"
        "登录完成后请点击 [确认] 继续。"
        "\n首次登录会自动保存，后续无需重复登录。"
    )
    log("登录确认完成，开始搜索")

    # 3. 导航到搜索页，等待页面加载
    goto(search_url)
    wait(3)
    # 等待职位卡片加载（实际 DOM: li.job-card-box）
    result_msg = wait_for_element("li.job-card-box", timeout=10)
    if "已出现" not in str(result_msg):
        # 降级尝试
        result_msg = wait_for_element("[class*='job-card-box']", timeout=5)
    log("职位卡片: " + str(result_msg))
    wait(1)
    log("BOSS直聘搜索: " + pure_keyword + " (" + city + ")")

    # 4. 滚动采集（BOSS 直聘无限滚动，每 "页" 约 4 个卡片）
    target_count = max_pages * 4
    log("目标采集: " + str(target_count) + " 个职位 (" + str(max_pages) + "页 × 4)")
    result = boss_collect_jobs(pure_keyword, max_pages=max_pages)
    jobs = result.get("jobs", [])
    log("采集完成: 共 " + str(len(jobs)) + " 个职位")

    # 输出卡片级调试日志（始终显示前3条）
    debug_log = result.get("debug_log", [])
    for entry in debug_log:
        log("卡片: 标题=" + str(entry.get("title", ""))[:30]
            + " 公司=" + str(entry.get("company", ""))[:20]
            + " PUA薪资=" + str(entry.get("salary_pua", ""))
            + " 子元素=" + str(entry.get("card_children", "")))

    if not jobs:
        debug_classes = result.get("debug_classes", [])
        body_preview = result.get("body_text_preview", "")
        if debug_classes:
            log("调试: 页面类名 = " + str(debug_classes[:15]))
        if body_preview:
            log("调试: 页面文本 = " + str(body_preview)[:200])
        log("未采集到职位数据，跳过分析和导出")
        return result

    # 5. LLM 分析总结
    jobs_text = _jobs_to_text(jobs)
    stats_text = ""
    if result.get("salary_stats"):
        s = result["salary_stats"]
        stats_text = (
            "\n薪资统计: 共 " + str(s["count"]) + " 个岗位, "
            "最低 " + str(s["min"]) + "K, 最高 " + str(s["max"]) + "K, "
            "平均 " + str(s["average"]) + "K, 中位数 " + str(s["median"]) + "K"
        )
    top_text = ""
    if result.get("top_companies"):
        companies = [str(c["name"]) + "(" + str(c["count"]) + "个)" for c in result["top_companies"][:5]]
        top_text = "\n招聘岗位最多的公司: " + ", ".join(companies)

    analysis_prompt = (
        "请对以下 BOSS 直聘 '" + pure_keyword + "' (" + city + ") 职位数据进行分析总结，"
        "包括：岗位概况、薪资分布特点、招聘趋势、值得关注的公司和岗位。\n\n"
        "数据概览: 共 " + str(len(jobs)) + " 个职位" + stats_text + top_text + "\n\n"
        "详细数据:\n" + jobs_text
    )
    analysis = llm_generate_text(analysis_prompt)
    log("LLM 分析完成")

    # 6. WPS 导出 PDF
    columns = ["序号", "职位", "公司", "薪资", "地点", "要求"]
    rows = []
    for i, job in enumerate(jobs, 1):
        rows.append([
            str(i),
            str(job.get("title", "")),
            str(job.get("company", "")),
            str(job.get("salary", "")),
            str(job.get("area", "")),
            str(job.get("tags", "")),
        ])

    table_json = [{"title": "职位列表", "columns": columns, "rows": rows}]
    export_result = wps_writer_export(
        title="BOSS直聘 " + pure_keyword + "(" + city + ") 职位分析报告",
        body=analysis,
        table_json=table_json,
        output_format="pdf",
    )
    log("PDF 导出完成")

    result["analysis"] = analysis
    result["export"] = export_result
    return result

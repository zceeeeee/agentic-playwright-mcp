"""Layer 3 helpers for extracting and presenting BOSS Zhipin job results."""

from __future__ import annotations

import re
from typing import Any


class BossResultError(RuntimeError):
    """Raised when the BOSS result page cannot be read."""


# ---------------------------------------------------------------------------
# City parsing (moved from boss_search.py to avoid import re in sandbox)
# ---------------------------------------------------------------------------

_CITY_CODES = {
    "全国": "100010000",
    "北京": "101010100",
    "上海": "101020100",
    "广州": "101280100",
    "深圳": "101280600",
    "杭州": "101210100",
    "成都": "101270100",
    "南京": "101190100",
    "武汉": "101200100",
    "西安": "101110100",
    "苏州": "101190400",
    "长沙": "101250100",
    "天津": "101030100",
    "重庆": "101040100",
    "郑州": "101180100",
    "东莞": "101281600",
    "青岛": "101120200",
    "合肥": "101220100",
    "厦门": "101230200",
    "昆明": "101290100",
    "大连": "101070200",
    "珠海": "101280700",
    "佛山": "101280800",
    "宁波": "101210400",
}

_ALL_CITIES = "|".join(_CITY_CODES.keys())


def parse_boss_keyword(keyword: str) -> tuple[str, str, str]:
    """Parse a BOSS keyword string into (city, city_code, pure_keyword).

    Args:
        keyword: Raw keyword like "深圳的AI产品经理" or "AI产品经理".

    Returns:
        (city_name, city_code, pure_keyword) tuple.
    """
    keyword = str(keyword or "").strip()
    if not keyword:
        return "全国", _CITY_CODES["全国"], ""

    # 去掉逗号及后面的内容（如 "AI产品经理岗位，分析前5页" → "AI产品经理岗位"）
    keyword = re.split(r"[，,。.;；]", keyword, maxsplit=1)[0].strip()

    # Match "深圳的AI产品经理" or "深圳AI产品经理" or "深圳地区的AI产品经理"
    match = re.search(rf"({_ALL_CITIES})(?:地区的?|的|地|\s)*(.+)", keyword)
    if match:
        city = match.group(1)
        pure = match.group(2).strip()
        return city, _CITY_CODES.get(city, _CITY_CODES["全国"]), pure

    # Match "AI产品经理在深圳"
    match = re.search(rf"(.+?)(?:在|去|到)({_ALL_CITIES})$", keyword)
    if match:
        city = match.group(2)
        pure = match.group(1).strip()
        return city, _CITY_CODES.get(city, _CITY_CODES["全国"]), pure

    return "全国", _CITY_CODES["全国"], keyword


def build_boss_search_url(keyword: str) -> tuple[str, str, str]:
    """Build the BOSS Zhipin search URL from a keyword string.

    Args:
        keyword: Raw keyword like "深圳的AI产品经理".

    Returns:
        (url, city, pure_keyword) tuple.
    """
    from urllib.parse import quote_plus

    city, city_code, pure_keyword = parse_boss_keyword(keyword)
    url = f"https://www.zhipin.com/web/geek/jobs?city={city_code}&query={quote_plus(pure_keyword)}"
    return url, city, pure_keyword


# ---------------------------------------------------------------------------
# JavaScript extractors
# ---------------------------------------------------------------------------

BOSS_RESULT_SCRIPT = r"""
(maxItems) => {
  const limit = Math.max(1, Number(maxItems) || 30);
  const clean = (s) => String(s || "").replace(/\s+/g, " ").trim();

  // PUA 私用区字符检测 — BOSS 直聘用自定义字体渲染薪资数字
  const hasPUA = (s) => {
    if (!s) return false;
    for (let i = 0; i < s.length; i++) {
      const c = s.charCodeAt(i);
      if ((c >= 0xE000 && c <= 0xF8FF) || (c >= 0xF0000 && c <= 0xFFFFF)) return true;
    }
    return false;
  };

  // ── 精确选择器：直接匹配 BOSS 直聘实际 DOM ──
  // 卡片容器: li.job-card-box
  //   ├── div.job-info
  //   │   ├── div.job-title > a.job-name (职位名) + span.job-salary (薪资 PUA)
  //   │   └── ul.tag-list > li (标签)
  //   └── div.job-card-footer
  //       ├── a.boss-info > span.boss-name (公司名)
  //       └── span.company-location (地点)
  const cards = Array.from(document.querySelectorAll("li.job-card-box"));
  let matchedSelector = "li.job-card-box";

  // 降级
  if (cards.length === 0) {
    const fallback = document.querySelectorAll(
      ".job-card-box, [class*='job-card-box'], .job-card-wrap li"
    );
    if (fallback.length > 0) {
      cards.push(...fallback);
      matchedSelector = "fallback-job-card-box";
    }
  }

  const jobs = [];
  const seen = new Set();
  const debugLog = [];

  for (const card of cards) {
    if (jobs.length >= limit) break;

    // ── 职位名 ──
    const titleEl = card.querySelector("a.job-name, .job-name, [class*='job-name']");
    const title = clean(titleEl ? (titleEl.innerText || titleEl.textContent || "") : "");
    if (!title) continue;

    // ── 职位链接 ──
    const jobUrl = titleEl && titleEl.href ? titleEl.href : "";

    // ── 公司名（.boss-name，不是 .company-name）──
    const bossNameEl = card.querySelector(".boss-name, [class*='boss-name']");
    let company = clean(bossNameEl ? (bossNameEl.innerText || bossNameEl.textContent) : "");

    // 降级：从 footer 的链接中找
    if (!company) {
      const footerLinks = card.querySelectorAll(".job-card-footer a, .boss-info");
      for (const a of footerLinks) {
        const text = clean(a.innerText || a.textContent || "");
        // 排除 "查看更多信息"、"举报" 等非公司名文本
        if (text && text !== title && text.length >= 2 && text.length <= 30
            && !text.includes("查看") && !text.includes("举报") && !text.includes("更多")
            && !text.includes("APP") && !text.includes("搜索")) {
          company = text;
          break;
        }
      }
    }

    // 去重
    const key = title + "|" + company;
    if (seen.has(key)) continue;
    seen.add(key);

    // ── 薪资（.job-salary，含 PUA 字符）──
    const salaryEl = card.querySelector(".job-salary, [class*='job-salary']");
    const salaryRaw = salaryEl ? (salaryEl.innerText || salaryEl.textContent || "") : "";
    const salaryClean = clean(salaryRaw);
    const salary_needs_ocr = hasPUA(salaryRaw) || /^[\s\-~Kk万千元\/天月]*$/.test(salaryClean.replace(/\d+/g, ""));

    // ── 地点（.company-location）──
    const areaEl = card.querySelector(".company-location, [class*='company-location']");
    const area = clean(areaEl ? (areaEl.innerText || areaEl.textContent) : "");

    // ── 标签（.tag-list li）──
    const tagLis = card.querySelectorAll(".tag-list li, [class*='tag-list'] li");
    const tagParts = [];
    for (const li of tagLis) {
      const t = clean(li.innerText || li.textContent || "");
      if (t) tagParts.push(t);
    }
    const tags = tagParts.join(" ");

    // 公司链接
    const bossLinkEl = card.querySelector("a.boss-info, .boss-info");
    const companyUrl = bossLinkEl && bossLinkEl.href ? bossLinkEl.href : "";

    // 调试
    if (debugLog.length < 3) {
      debugLog.push({
        title: title.substring(0, 40),
        company: company.substring(0, 20),
        salary_raw: salaryClean.substring(0, 20),
        salary_pua: salary_needs_ocr,
        area: area.substring(0, 20),
        tags: tags.substring(0, 30),
      });
    }

    jobs.push({
      title: title, company: company,
      salary: salaryClean, salary_needs_ocr: salary_needs_ocr,
      area: area, tags: tags,
      job_url: jobUrl, company_url: companyUrl,
    });
  }

  return {
    jobs: jobs,
    total_cards: cards.length,
    matched_selector: matchedSelector,
    debug_log: debugLog,
  };
}
"""


# ---------------------------------------------------------------------------
# Python helpers
# ---------------------------------------------------------------------------


def _clean(value: Any) -> str:
    """Collapse whitespace and strip."""
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _parse_salary_range(salary_text: str) -> dict[str, Any]:
    """Parse salary text like '15-25K' or '15-25K·13薪' into structured data."""
    text = _clean(salary_text)
    if not text:
        return {"text": "", "min": None, "max": None, "months": None}

    months_match = re.search(r"[·.]\s*(\d+)\s*薪", text)
    months = int(months_match.group(1)) if months_match else None

    range_match = re.search(r"(\d+(?:\.\d+)?)\s*[-~]\s*(\d+(?:\.\d+)?)\s*([Kk万千]?)", text)
    if not range_match:
        return {"text": text, "min": None, "max": None, "months": months}

    low = float(range_match.group(1))
    high = float(range_match.group(2))
    unit = range_match.group(3).upper()

    if unit in ("万",):
        low *= 10
        high *= 10

    return {"text": text, "min": low, "max": high, "months": months}


def _normalize_job(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize a raw job dict into a clean structure."""
    if not isinstance(raw, dict):
        return None
    title = _clean(raw.get("title"))
    if not title:
        return None

    salary_info = _parse_salary_range(raw.get("salary", ""))

    return {
        "title": title,
        "company": _clean(raw.get("company")),
        "salary": salary_info["text"],
        "salary_min": salary_info["min"],
        "salary_max": salary_info["max"],
        "salary_months": salary_info["months"],
        "salary_needs_ocr": bool(raw.get("salary_needs_ocr", False)),
        "area": _clean(raw.get("area")),
        "tags": _clean(raw.get("tags")),
        "job_url": _clean(raw.get("job_url")),
        "company_url": _clean(raw.get("company_url")),
    }


def extract_boss_jobs(page: Any, *, max_items: int = 30) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Extract visible job cards from a BOSS Zhipin result page.

    Returns:
        Tuple of (jobs_list, debug_info_dict).
        debug_info contains matched_selector, debug_classes, debug_html_snippets, body_text_preview.
    """
    debug_info: dict[str, Any] = {}
    if page is None or not hasattr(page, "evaluate"):
        raise BossResultError("BOSS result page is unavailable")
    try:
        payload = page.evaluate(BOSS_RESULT_SCRIPT, max(1, int(max_items)))
    except Exception as exc:
        raise BossResultError(f"Failed to extract BOSS results: {exc}") from exc

    if not isinstance(payload, dict):
        raise BossResultError(f"Unexpected payload type: {type(payload)}")

    raw_jobs = payload.get("jobs", [])
    if not isinstance(raw_jobs, list):
        raw_jobs = []

    # 收集调试信息
    debug_info["matched_selector"] = payload.get("matched_selector", "")
    debug_info["debug_classes"] = payload.get("debug_classes", [])
    debug_info["debug_log"] = payload.get("debug_log", [])
    debug_info["body_text_preview"] = payload.get("body_text_preview", "")

    # 始终记录提取日志
    import logging
    logger = logging.getLogger(__name__)
    logger.info("BOSS extract: %d raw jobs, selector=%r", len(raw_jobs), debug_info["matched_selector"])
    for entry in debug_info.get("debug_log", []):
        logger.info("BOSS card: title=%r company=%r tag=%s class=%s children=%d salary_pua=%s",
                     entry.get("title"), entry.get("company"),
                     entry.get("card_tag"), entry.get("card_class"),
                     entry.get("card_children"), entry.get("salary_pua"))
    if not raw_jobs:
        logger.warning("BOSS extract: 0 jobs. classes=%s", debug_info["debug_classes"][:10])
        if debug_info["body_text_preview"]:
            logger.warning("BOSS body: %s", debug_info["body_text_preview"][:300])

    jobs: list[dict[str, Any]] = []
    for raw in raw_jobs[: max(1, int(max_items))]:
        normalized = _normalize_job(raw)
        if normalized:
            jobs.append(normalized)
    return jobs, debug_info


def _ocr_salary_from_card(page: Any, card_index: int) -> str:
    """Screenshot a single job card's salary element and OCR it.

    Args:
        page: Playwright page object.
        card_index: Zero-based index of the job card on the page.

    Returns:
        Salary text extracted via OCR, or empty string if failed.
    """
    import asyncio
    import logging

    from src.core.ocr import get_ocr_module

    logger = logging.getLogger(__name__)

    ocr = get_ocr_module()
    if ocr is None:
        logger.warning("BOSS OCR[%d]: ocr module is None", card_index)
        return ""

    # 先用 JS 定位第 N 个卡片内的薪资元素，滚动到可见区域后取 bounding box
    box_info = page.evaluate("""(index) => {
        const cards = document.querySelectorAll('li.job-card-box');
        if (index >= cards.length) return null;
        const card = cards[index];
        const salaryEl = card.querySelector('.job-salary, [class*="job-salary"]');
        if (!salaryEl) return {found: false, card_text: (card.innerText || '').substring(0, 100)};
        // 先滚动到元素可见
        salaryEl.scrollIntoView({block: 'center'});
        // 等一帧让滚动生效后再取坐标
        const rect = salaryEl.getBoundingClientRect();
        return {
            found: true,
            x: rect.x, y: rect.y, width: rect.width, height: rect.height,
            text: (salaryEl.innerText || '').substring(0, 50),
            visible: rect.width > 0 && rect.height > 0,
        };
    }""", card_index)

    # 等滚动动画完成
    page.wait_for_timeout(300)

    if not box_info:
        logger.warning("BOSS OCR[%d]: card not found", card_index)
        return ""

    if not box_info.get("found"):
        logger.info("BOSS OCR[%d]: no .job-salary in card, card_text=%r",
                     card_index, box_info.get("card_text", ""))
        return ""

    if not box_info.get("visible"):
        logger.info("BOSS OCR[%d]: salary element not visible (w=%s h=%s)",
                     card_index, box_info.get("width"), box_info.get("height"))
        return ""

    logger.info("BOSS OCR[%d]: salary box=(%s,%s,%s,%s) text=%r",
                card_index,
                box_info.get("x"), box_info.get("y"),
                box_info.get("width"), box_info.get("height"),
                box_info.get("text"))

    # 用坐标截图（更可靠，不依赖 Playwright locator 的索引逻辑）
    try:
        x = box_info["x"]
        y = box_info["y"]
        w = box_info["width"]
        h = box_info["height"]
        screenshot_bytes = page.screenshot(
            clip={"x": x, "y": y, "width": w, "height": h}
        )
    except Exception as exc:
        logger.warning("BOSS OCR[%d]: screenshot failed: %s", card_index, exc)
        return ""

    if not screenshot_bytes:
        logger.warning("BOSS OCR[%d]: screenshot is empty", card_index)
        return ""

    logger.info("BOSS OCR[%d]: screenshot %d bytes, running OCR...", card_index, len(screenshot_bytes))

    try:
        result = asyncio.run(ocr.recognize(screenshot_bytes))
    except RuntimeError:
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, ocr.recognize(screenshot_bytes))
            result = future.result(timeout=10)
    except Exception as exc:
        logger.warning("BOSS OCR[%d]: recognize failed: %s", card_index, exc)
        return ""

    text = (result.raw_text or "").strip()
    logger.info("BOSS OCR[%d]: result text=%r", card_index, text)

    # Match salary patterns: "15-25K", "2-4万·13薪", "面议" etc.
    salary_match = re.search(
        r"(\d+(?:\.\d+)?)\s*[-~]\s*(\d+(?:\.\d+)?)\s*[Kk万千](?:\s*[·.]\s*\d+\s*薪)?",
        text,
    )
    if salary_match:
        return salary_match.group(0).strip()

    if "面议" in text:
        return "面议"

    # Fallback: return whatever OCR found (cleaned)
    cleaned = re.sub(r"[^\d\-~Kk万千·薪面议]", "", text).strip()
    return cleaned if len(cleaned) >= 2 else ""


def enrich_boss_salaries(page: Any, jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fill in missing or obfuscated salaries via OCR.

    BOSS 直聘用 PUA 私用区字符 + 自定义字体渲染薪资数字，
    DOM 中的 innerText 是无意义的 PUA 字符（清理后只剩 "-K"）。
    对以下两种情况触发 OCR：
    1. 薪资字段为空
    2. JS 标记 salary_needs_ocr=True（检测到 PUA 字符或无效值）

    Args:
        page: Playwright page object (must be on the BOSS search results page).
        jobs: List of job dicts (may have empty or obfuscated salary fields).

    Returns:
        The same list with salary fields updated in-place.
    """
    import logging
    logger = logging.getLogger(__name__)

    if page is None or not hasattr(page, "locator"):
        return jobs

    for i, job in enumerate(jobs):
        salary = _clean(job.get("salary"))
        needs_ocr = job.get("salary_needs_ocr", False)

        # 已有有效薪资（包含数字）且无需 OCR → 跳过
        if salary and not needs_ocr and re.search(r"\d", salary):
            continue

        logger.info("BOSS enrich[%d]: salary=%r needs_ocr=%s → triggering OCR", i, salary, needs_ocr)
        ocr_salary = _ocr_salary_from_card(page, i)
        if ocr_salary:
            job["salary"] = ocr_salary
            salary_info = _parse_salary_range(ocr_salary)
            job["salary_min"] = salary_info["min"]
            job["salary_max"] = salary_info["max"]
            job["salary_months"] = salary_info["months"]

    return jobs


def build_boss_search_result(
    keyword: str,
    jobs: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a structured result artifact from collected jobs."""
    normalized = [item for item in (_normalize_job(j) for j in jobs) if item]
    # 清除内部标记
    for item in normalized:
        item.pop("salary_needs_ocr", None)

    salaries = [j["salary_min"] for j in normalized if j.get("salary_min") is not None]
    salary_stats = None
    if salaries:
        from statistics import mean, median
        salary_stats = {
            "count": len(salaries),
            "min": min(salaries),
            "max": max(salaries),
            "average": round(mean(salaries), 1),
            "median": round(median(salaries), 1),
        }

    company_counts: dict[str, int] = {}
    for j in normalized:
        name = j.get("company", "")
        if name:
            company_counts[name] = company_counts.get(name, 0) + 1
    top_companies = sorted(company_counts.items(), key=lambda x: x[1], reverse=True)[:10]

    return {
        "type": "boss_job_search",
        "keyword": _clean(keyword),
        "total_jobs": len(normalized),
        "jobs": normalized,
        "salary_stats": salary_stats,
        "top_companies": [{"name": name, "count": count} for name, count in top_companies],
    }

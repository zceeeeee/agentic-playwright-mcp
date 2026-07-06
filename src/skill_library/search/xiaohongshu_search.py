"""Xiaohongshu search adapter."""


SEARCH_URL_TEMPLATE = "https://www.xiaohongshu.com/search_result_ai?keyword={query}"


def _is_logged_in() -> bool:
    """Best-effort login check using page state available inside the skill."""
    url = get_url().lower()
    if "login" in url or "passport" in url:
        return False

    return bool(
        run_js(
            """() => {
                const text = document.body ? document.body.innerText : "";
                const needsLoginRecommendation = text.includes("登录后推荐更懂你的笔记");
                const hasLoginText =
                    text.includes("登录") ||
                    text.includes("验证码") ||
                    text.includes("手机号");
                const hasLoginInput =
                    document.querySelector("input[type='tel']") ||
                    document.querySelector("input[placeholder*='手机号']") ||
                    document.querySelector("input[placeholder*='验证码']");
                const hasLoginButton =
                    Array.from(document.querySelectorAll("button")).some(
                        (button) => button.innerText && button.innerText.includes("登录")
                    );
                const hasSearchPage = location.href.includes("/search_result");
                const hasContent =
                    document.querySelector("[class*='feeds']") ||
                    document.querySelector("[class*='note']") ||
                    document.querySelector("a[href*='/explore/']") ||
                    document.querySelector("a[href*='/user/profile/']");

                if (needsLoginRecommendation || hasLoginInput || (hasLoginText && hasLoginButton && !hasContent)) {
                    return false;
                }
                return Boolean(hasSearchPage || hasContent);
            }"""
        )
    )


def _wait_until_logged_in(timeout_seconds: int = 180) -> bool:
    waited = 0
    while waited < timeout_seconds:
        if _is_logged_in():
            return True
        wait(2)
        waited += 2
    return False


def run(keyword: str):
    """Open Xiaohongshu search, wait for login if needed, then reopen the search URL."""
    query = url_quote(keyword)
    target_url = SEARCH_URL_TEMPLATE.format(query=query)

    goto(target_url)
    wait_for_navigation()
    wait(2)

    if not _is_logged_in():
        log("Xiaohongshu is not logged in yet. Please finish login in the browser.")
        if not _wait_until_logged_in():
            raise RuntimeError("Xiaohongshu login timed out; search URL was not reopened.")

        log("Xiaohongshu login detected; reopening original search URL.")
        goto(target_url)
        wait_for_navigation()
        wait(2)

    if "search_result" not in get_url():
        goto(target_url)
        wait_for_navigation()
        wait(2)

    log(f"Xiaohongshu search opened: {keyword}")

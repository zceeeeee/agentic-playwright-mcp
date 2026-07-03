# 我需要文章的网址信息
# 类似https://zhuanlan.zhihu.com/p/2049017245020558481

APPROVE_URL="https://zhuanlan.zhihu.com/p/2049017245020558481"
SIGN_URL="https://www.zhihu.com/signin"

def _js_string(value: str) -> str:
    text = str(value)
    text = text.replace("\\", "\\\\")
    text = text.replace('"', '\\"')
    text = text.replace("\n", "\\n")
    text = text.replace("\r", "\\r")
    return f'"{text}"'


def run(keyword: str):
    """Open Zhihu writer, fill title/body with keyword, and click publish."""
    if not ensure_auth("zhihu", SIGN_URL):
        log("Zhihu login state not confirmed; skip approve")
        return

    goto(APPROVE_URL)
 

    wait_for_element("button.VoteButton[aria-label^='赞同']", timeout=15)
    click("button.VoteButton[aria-label^='赞同']")
    wait(2)

    log(f"finish approve")
    close_browser()

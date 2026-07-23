"""WeChat desktop Moments like skill."""


def _default_log(message):
    print(f"[LOG] {message}")


def _resolve_log(log_fn=None):
    if log_fn is not None:
        return log_fn
    try:
        return log
    except Exception:
        return _default_log


def _value(value):
    if value is None:
        return None
    text = str(value).strip()
    if not text or text == "-1":
        return None
    return text


def run(
    author_name="-1",
    target="first",
    launch_path="-1",
    log_fn=None,
    like_fn=None,
):
    """Like the newest Moments post or the newest post by one author."""

    logger = _resolve_log(log_fn)
    author = _value(author_name)
    mode = str(target or "first").strip().lower()
    if author:
        mode = "author"
    elif mode in {"第一条", "第一天", "1", "first"}:
        mode = "first"
    else:
        raise ValueError("WeChat Moments like target must be first or author")

    if like_fn is None:
        try:
            like_fn = wechat_like_moment
        except Exception as exc:
            raise RuntimeError("wechat_like_moment is not registered") from exc

    logger(
        f"Opening WeChat Moments and locating: "
        f"{author if author else 'first post'}"
    )
    result = like_fn(
        author_name=author,
        target=mode,
        launch_path=_value(launch_path),
    )
    if not result or not result.get("success"):
        raise RuntimeError("WeChat Moments like failed")
    logger(f"WeChat Moments like status: {result.get('status', 'unknown')}")
    return result

"""WeChat desktop official account follow skill."""


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
    account_name="-1",
    message="-1",
    launch_path="-1",
    log_fn=None,
    follow_fn=None,
):
    """Open WeChat desktop, search an official account, and follow it."""

    logger = _resolve_log(log_fn)
    account = _value(account_name)
    if not account:
        raise ValueError("WeChat follow requires account_name")

    if follow_fn is None:
        try:
            follow_fn = wechat_follow_official_account
        except Exception as exc:
            raise RuntimeError("wechat_follow_official_account is not registered") from exc

    logger(f"Opening WeChat and searching official account: {account}")
    result = follow_fn(
        account_name=account,
        message=_value(message),
        launch_path=_value(launch_path),
    )
    if not result or not result.get("success"):
        raise RuntimeError("WeChat official account follow failed")
    logger(f"WeChat official account handled: {account}")
    return result

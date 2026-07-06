"""WeChat desktop official account private message skill."""


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
    send_fn=None,
):
    """Open WeChat desktop, search an official account, and send a message."""

    logger = _resolve_log(log_fn)
    account = _value(account_name)
    text = _value(message)
    if not account:
        raise ValueError("WeChat send requires account_name")
    if not text:
        raise ValueError("WeChat send requires message")

    if send_fn is None:
        try:
            send_fn = wechat_send_official_account_message
        except Exception as exc:
            raise RuntimeError(
                "wechat_send_official_account_message is not registered"
            ) from exc

    logger(f"Opening WeChat official account chat: {account}")
    result = send_fn(
        account_name=account,
        message=text,
        launch_path=_value(launch_path),
    )
    if not result or not result.get("success"):
        raise RuntimeError("WeChat official account message failed")
    logger(f"WeChat message sent to official account: {account}")
    return result

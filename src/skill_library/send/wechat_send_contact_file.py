"""WeChat desktop contact file sending skill."""


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
    recipient_name="-1",
    file_path="-1",
    launch_path="-1",
    log_fn=None,
    send_fn=None,
):
    """Send one local file to a WeChat contact or group."""

    logger = _resolve_log(log_fn)
    recipient = _value(recipient_name)
    path = _value(file_path)
    if not recipient:
        raise ValueError("WeChat file sending requires recipient_name")
    if not path:
        raise ValueError("WeChat file sending requires file_path")

    if send_fn is None:
        try:
            send_fn = wechat_send_contact_file
        except Exception as exc:
            raise RuntimeError("wechat_send_contact_file is not registered") from exc

    logger(f"Preparing WeChat file send to: {recipient}")
    result = send_fn(
        recipient_name=recipient,
        file_path=path,
        launch_path=_value(launch_path),
    )
    if not result:
        raise RuntimeError("WeChat contact file sending returned no result")
    if not result.get("success"):
        if result.get("status") in {"cancelled", "unknown"}:
            logger(str(result.get("message") or result.get("status")))
            return result
        raise RuntimeError(
            str(result.get("message") or "WeChat contact file sending failed")
        )
    logger(f"WeChat file submitted to: {recipient}")
    return result

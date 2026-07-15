"""WeChat desktop contact message skill."""


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


def _looks_like_windows_file_path(value):
    text = str(value or "")
    for index in range(max(0, len(text) - 2)):
        if text[index].isalpha() and text[index + 1 : index + 3] in {":\\", ":/"}:
            return True
    return text.strip().startswith("\\\\")


def run(
    contact_name="-1",
    message="-1",
    launch_path="-1",
    log_fn=None,
    send_fn=None,
):
    """Open WeChat desktop, search a contact, and send a message."""

    logger = _resolve_log(log_fn)
    contact = _value(contact_name)
    text = _value(message)
    if not contact:
        raise ValueError("WeChat send requires contact_name")
    if not text:
        raise ValueError("WeChat send requires message")
    if _looks_like_windows_file_path(text):
        raise ValueError("Local file path must use wechat_send_contact_file")

    if send_fn is None:
        try:
            send_fn = wechat_send_contact_message
        except Exception as exc:
            raise RuntimeError("wechat_send_contact_message is not registered") from exc

    logger(f"Opening WeChat contact chat: {contact}")
    result = send_fn(
        contact_name=contact,
        message=text,
        launch_path=_value(launch_path),
    )
    if not result or not result.get("success"):
        raise RuntimeError("WeChat contact message failed")
    logger(f"WeChat message sent to contact: {contact}")
    return result

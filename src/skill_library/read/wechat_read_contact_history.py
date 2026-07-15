"""Read local WeChat history using the project-local wx-cli runtime."""


def _clean_value(value):
    if value is None:
        return None
    text = str(value).strip()
    if not text or text == "-1":
        return None
    return text


def _default_log(message):
    print(f"[LOG] {message}")


def run(
    chat_name="-1",
    limit="50",
    offset="0",
    since="-1",
    until="-1",
    message_type="-1",
    output_mode="display",
    log_fn=None,
    read_fn=None,
):
    """Read a local WeChat conversation without returning raw messages."""

    logger = log_fn or _default_log
    chat = _clean_value(chat_name)
    if not chat:
        raise ValueError(
            "读取微信历史记录需要指定联系人或群聊。例如："
            "读取我和张三最近 50 条微信聊天记录。"
        )
    if read_fn is None:
        try:
            read_fn = wechat_read_contact_history
        except Exception as exc:
            raise RuntimeError("wechat_read_contact_history 未注册") from exc

    logger("正在检查本地 wx-cli 并解析指定微信会话")
    result = read_fn(
        chat_name=chat,
        limit=_clean_value(limit) or "50",
        offset=_clean_value(offset) or "0",
        since=_clean_value(since),
        until=_clean_value(until),
        message_type=_clean_value(message_type),
        output_mode=_clean_value(output_mode) or "display",
    )
    if not result or not result.get("success"):
        raise RuntimeError(
            result.get("message", "微信历史记录读取失败")
            if isinstance(result, dict)
            else "微信历史记录读取失败"
        )
    logger(
        f"已读取 {result.get('count', 0)} 条微信记录；聊天原文未写入任务日志或历史"
    )
    print(
        "已读取微信历史聊天记录，原文未保存。"
        f"记录数量：{result.get('count', 0)}；"
        f"完整性状态：{result.get('meta_status', 'unknown')}。"
    )
    return {
        "success": True,
        "sensitive_result_id": result.get("sensitive_result_id"),
        "chat": result.get("chat"),
        "chat_type": result.get("chat_type"),
        "count": result.get("count", 0),
        "meta_status": result.get("meta_status", "unknown"),
        "raw_messages_omitted": True,
        "summary_requested": result.get("summary_requested", False),
        "summary_generated": result.get("summary_generated", False),
    }

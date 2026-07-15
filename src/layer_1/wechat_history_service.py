"""Read-only orchestration for local WeChat history queries."""

from __future__ import annotations

import threading
from dataclasses import dataclass, replace
from typing import Any, Callable

from src.layer_1.wx_cli_client import (
    WxChatCandidate,
    WxCliClient,
    WxCliError,
    WxHistoryQuery,
    WxHistoryResult,
    normalize_history_query,
    query_with_chat,
)


@dataclass(frozen=True)
class PreparedWxHistoryQuery:
    requested_query: WxHistoryQuery
    candidate: WxChatCandidate
    input_warnings: tuple[str, ...]
    fuzzy_match: bool


class WechatHistoryService:
    def __init__(self, client: WxCliClient | None = None) -> None:
        self.client = client or WxCliClient()

    def prepare(
        self,
        *,
        chat_name: Any,
        limit: Any = 50,
        offset: Any = 0,
        since: Any = None,
        until: Any = None,
        message_type: Any = None,
        cancel_event: threading.Event | None = None,
        candidate_selector: Callable[[list[WxChatCandidate]], WxChatCandidate]
        | None = None,
    ) -> PreparedWxHistoryQuery:
        query, warnings = normalize_history_query(
            chat_name=chat_name,
            limit=limit,
            offset=offset,
            since=since,
            until=until,
            message_type=message_type,
        )
        status = self.client.check_status(cancel_event=cancel_event)
        if not status.installed or not status.compatible or not status.initialized:
            raise WxCliError(
                code=status.error_code or "WX_CLI_NOT_INITIALIZED",
                message=status.message,
                user_action_required=True,
            )
        candidates = self.client.find_chat_candidates(
            query.chat_name, cancel_event=cancel_event
        )
        candidate = self._select_unambiguous_candidate(
            query.chat_name,
            candidates,
            candidate_selector=candidate_selector,
        )
        return PreparedWxHistoryQuery(
            requested_query=query,
            candidate=candidate,
            input_warnings=warnings,
            fuzzy_match=not candidate.exact_match,
        )

    def read(
        self,
        prepared: PreparedWxHistoryQuery,
        *,
        cancel_event: threading.Event | None = None,
    ) -> WxHistoryResult:
        query = query_with_chat(
            prepared.requested_query, prepared.candidate.username
        )
        result = self.client.history(query, cancel_event=cancel_event)
        warnings = tuple(
            dict.fromkeys((*prepared.input_warnings, *result.warnings))
        )
        return replace(
            result,
            chat=prepared.candidate.display_name,
            username=prepared.candidate.username,
            is_group=prepared.candidate.is_group,
            chat_type=prepared.candidate.chat_type or result.chat_type,
            warnings=warnings,
        )

    def read_more(
        self,
        *,
        username: str,
        display_name: str,
        chat_type: str,
        limit: int,
        offset: int,
        since: str | None,
        until: str | None,
        message_type: str | None,
        cancel_event: threading.Event | None = None,
    ) -> WxHistoryResult:
        query, warnings = normalize_history_query(
            chat_name=username,
            limit=limit,
            offset=offset,
            since=since,
            until=until,
            message_type=message_type,
        )
        result = self.client.history(query, cancel_event=cancel_event)
        return replace(
            result,
            chat=display_name,
            username=username,
            is_group=chat_type == "group" or username.endswith("@chatroom"),
            chat_type=chat_type or result.chat_type,
            warnings=tuple(dict.fromkeys((*warnings, *result.warnings))),
        )

    @staticmethod
    def _select_unambiguous_candidate(
        requested_name: str,
        candidates: list[WxChatCandidate],
        *,
        candidate_selector: Callable[[list[WxChatCandidate]], WxChatCandidate]
        | None = None,
    ) -> WxChatCandidate:
        exact = [candidate for candidate in candidates if candidate.exact_match]
        if len(exact) == 1:
            return exact[0]
        relevant = exact or candidates
        if len(relevant) == 1:
            return relevant[0]
        if not relevant:
            raise WxCliError(
                code="CHAT_NOT_FOUND",
                message=(
                    f"没有找到名为“{requested_name}”的微信会话。"
                    "请检查微信备注名、群聊全名，或提供微信 ID。"
                ),
                user_action_required=True,
            )
        if candidate_selector is not None:
            selected = candidate_selector(relevant)
            if selected in relevant:
                return selected
            raise WxCliError(
                code="CHAT_AMBIGUOUS",
                message="选择的微信会话无效，请重新读取。",
                user_action_required=True,
            )
        raise WxCliError(
            code="CHAT_AMBIGUOUS",
            message="找到多个匹配的微信会话，请选择后重新读取。",
            details={
                "candidates": [
                    {
                        "display_name": candidate.display_name,
                        "chat_type": candidate.chat_type,
                    }
                    for candidate in relevant
                ]
            },
            user_action_required=True,
        )

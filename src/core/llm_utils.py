"""Shared helpers for structured LLM calls."""

from __future__ import annotations

from typing import Any, Dict


def _is_json_parse_error(exc: RuntimeError) -> bool:
    message = str(exc).lower()
    return "parse json" in message or "json" in message and "parse" in message


def chat_json_with_retry(
    client: Any,
    prompt: str,
    *,
    system_prompt: str | None = None,
    schema: Dict[str, Any] | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> Dict[str, Any]:
    """Call LLMClient.chat_json and retry once after JSON parse failures."""
    try:
        return client.chat_json(
            prompt,
            system_prompt=system_prompt,
            schema=schema,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    except RuntimeError as exc:
        if not _is_json_parse_error(exc):
            raise

    retry_prompt = (
        f"{prompt}\n\n"
        "重要：请严格按 JSON Schema 返回，不要包含任何额外文字、解释、markdown 或代码块。"
    )
    return client.chat_json(
        retry_prompt,
        system_prompt=system_prompt,
        schema=schema,
        temperature=temperature,
        max_tokens=max_tokens,
    )

"""Token usage tracking for LLM API calls.

Provides:
  - TokenUsage: dataclass holding token counts for a single API call
  - TokenTracker: global accumulator that sums usage across calls,
    separating text tokens from vision tokens

Usage::

    from src.core.token_tracker import get_token_tracker

    tracker = get_token_tracker()
    tracker.reset()                       # start a new task
    # ... LLM calls happen (auto-recorded via LLMClient / VisionModule) ...
    print(tracker.summary())              # {text: {...}, vision: {...}, total: {...}}
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TokenUsage:
    """Token counts from a single LLM API call."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    reasoning_tokens: int = 0
    vision_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0

    def __iadd__(self, other: TokenUsage) -> TokenUsage:
        """Accumulate another usage into this one."""
        self.prompt_tokens += other.prompt_tokens
        self.completion_tokens += other.completion_tokens
        self.total_tokens += other.total_tokens
        self.reasoning_tokens += other.reasoning_tokens
        self.vision_tokens += other.vision_tokens
        self.cache_read_tokens += other.cache_read_tokens
        self.cache_creation_tokens += other.cache_creation_tokens
        return self

    def __add__(self, other: TokenUsage) -> TokenUsage:
        return TokenUsage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
            reasoning_tokens=self.reasoning_tokens + other.reasoning_tokens,
            vision_tokens=self.vision_tokens + other.vision_tokens,
            cache_read_tokens=self.cache_read_tokens + other.cache_read_tokens,
            cache_creation_tokens=self.cache_creation_tokens + other.cache_creation_tokens,
        )

    def is_empty(self) -> bool:
        return self.total_tokens == 0

    def to_dict(self) -> dict[str, int]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "vision_tokens": self.vision_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_creation_tokens": self.cache_creation_tokens,
        }


def parse_openai_usage(data: dict[str, Any]) -> TokenUsage:
    """Extract TokenUsage from an OpenAI-compatible API response dict."""
    usage = data.get("usage") or {}
    details = usage.get("completion_tokens_details") or {}
    prompt_details = usage.get("prompt_tokens_details") or {}
    return TokenUsage(
        prompt_tokens=usage.get("prompt_tokens", 0),
        completion_tokens=usage.get("completion_tokens", 0),
        total_tokens=usage.get("total_tokens", 0),
        reasoning_tokens=details.get("reasoning_tokens", 0),
        cache_read_tokens=prompt_details.get("cached_tokens", 0),
    )


def parse_anthropic_usage(data: dict[str, Any]) -> TokenUsage:
    """Extract TokenUsage from an Anthropic API response dict."""
    usage = data.get("usage") or {}
    return TokenUsage(
        prompt_tokens=usage.get("input_tokens", 0),
        completion_tokens=usage.get("output_tokens", 0),
        total_tokens=usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
        cache_read_tokens=usage.get("cache_read_input_tokens", 0),
        cache_creation_tokens=usage.get("cache_creation_input_tokens", 0),
    )


class TokenTracker:
    """Global accumulator that tracks token usage across LLM calls.

    Separates text tokens (normal LLM calls) from vision tokens
    (screenshot/image analysis calls).
    """

    def __init__(self) -> None:
        self.text = TokenUsage()
        self.vision = TokenUsage()
        self._step_snapshots: list[dict[str, Any]] = []

    def record(self, usage: TokenUsage, *, is_vision: bool = False) -> None:
        """Record a single API call's usage."""
        if is_vision:
            self.vision += usage
        else:
            self.text += usage

    def snapshot_step(self, step_number: int, label: str = "") -> dict[str, Any]:
        """Take a snapshot of current totals (for per-step tracking).

        Returns a dict with the accumulated totals at this point.
        Call after each step to record its contribution.
        """
        snap = {
            "step": step_number,
            "label": label,
            "text": self.text.to_dict(),
            "vision": self.vision.to_dict(),
            "total": self.total.to_dict(),
        }
        self._step_snapshots.append(snap)
        return snap

    @property
    def total(self) -> TokenUsage:
        """Combined text + vision usage."""
        return self.text + self.vision

    @property
    def step_snapshots(self) -> list[dict[str, Any]]:
        return list(self._step_snapshots)

    def summary(self) -> dict[str, Any]:
        """Return a summary dict suitable for JSON output."""
        return {
            "text": self.text.to_dict(),
            "vision": self.vision.to_dict(),
            "total": self.total.to_dict(),
            "steps": self._step_snapshots,
        }

    def format_summary(self) -> str:
        """Human-readable one-line summary."""
        t = self.total
        parts = []
        if t.total_tokens > 0:
            parts.append(
                f"tokens: {t.total_tokens:,} "
                f"(prompt: {t.prompt_tokens:,}, completion: {t.completion_tokens:,})"
            )
        if self.vision.total_tokens > 0:
            parts.append(f"vision: {self.vision.total_tokens:,}")
        if t.reasoning_tokens > 0:
            parts.append(f"reasoning: {t.reasoning_tokens:,}")
        if t.cache_read_tokens > 0:
            parts.append(f"cache_hit: {t.cache_read_tokens:,}")
        return " | ".join(parts) if parts else "no LLM calls"

    def reset(self) -> None:
        """Reset all counters (start a new task)."""
        self.text = TokenUsage()
        self.vision = TokenUsage()
        self._step_snapshots.clear()


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------

_tracker: TokenTracker | None = None


def get_token_tracker() -> TokenTracker:
    """Get the process-wide TokenTracker instance."""
    global _tracker
    if _tracker is None:
        _tracker = TokenTracker()
    return _tracker


def reset_token_tracker() -> None:
    """Reset the process-wide TokenTracker."""
    global _tracker
    _tracker = None

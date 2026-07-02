"""Tests for structured LLM JSON routing and parsing."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.core.agent_loop import AgentLoop
from src.core.intent_parser import LLMIntentParser
from src.core.llm_utils import chat_json_with_retry
from src.core.skill_router import SkillRouter, SkillRouterInfo


class FakeJsonClient:
    def __init__(self, *responses):
        self.available = True
        self.responses = list(responses)
        self.calls = []

    def chat_json(self, prompt, **kwargs):
        self.calls.append({"prompt": prompt, **kwargs})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def chat(self, *args, **kwargs):
        raise AssertionError("free-text chat should not be used")


class FakeJsonCaller:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def call_json(self, prompt, **kwargs):
        self.calls.append({"prompt": prompt, **kwargs})
        return self.response

    def call(self, *args, **kwargs):
        raise AssertionError("free-text call should not be used")


def test_chat_json_with_retry_retries_once_after_parse_failure():
    client = FakeJsonClient(
        RuntimeError("Failed to parse JSON from LLM response: nope"),
        {"skill_id": "domain/google_search", "confidence": 0.9},
    )

    result = chat_json_with_retry(
        client,
        "pick a skill",
        schema={"type": "object"},
    )

    assert result["skill_id"] == "domain/google_search"
    assert len(client.calls) == 2
    assert "严格按 JSON Schema 返回" in client.calls[1]["prompt"]


def test_chat_json_with_retry_does_not_retry_api_failures():
    client = FakeJsonClient(RuntimeError("OpenAI API error 500: unavailable"))

    with pytest.raises(RuntimeError):
        chat_json_with_retry(client, "pick a skill")

    assert len(client.calls) == 1


def test_intent_parser_uses_chat_json_schema():
    client = FakeJsonClient(
        {
            "action": "search",
            "target": "python",
            "engine": "baidu",
            "confidence": 0.95,
        }
    )

    intent = LLMIntentParser(client=client).parse("帮我搜索 python")

    assert intent is not None
    assert intent.action == "search"
    assert intent.target == "python"
    assert intent.parameters["engine"] == "baidu"
    assert client.calls[0]["schema"]["required"] == ["action", "target", "confidence"]


def test_skill_router_llm_rank_uses_chat_json_schema():
    skill = SkillRouterInfo(
        id="domain/google_search",
        name="Google 搜索",
        description="Search Google",
    )
    caller = FakeJsonCaller(
        {
            "skill_id": "domain/google_search",
            "confidence": 0.91,
            "reason": "user asked for Google",
        }
    )
    router = SkillRouter(llm_caller=caller)

    decision = router._llm_rank("google 搜索 python", [(skill, 0.4)])

    assert decision is not None
    assert decision.skill is skill
    assert decision.source == "llm"
    assert caller.calls[0]["schema"]["required"] == ["skill_id", "confidence"]
    assert "返回 JSON" not in caller.calls[0]["prompt"]
    assert "只返回 JSON" not in caller.calls[0]["prompt"]


def test_skill_router_param_extraction_uses_chat_json_schema():
    skill = SkillRouterInfo(
        id="domain/demo",
        name="Demo",
        description="Demo skill",
        params={
            "keyword": {"type": "string", "description": "search keyword"},
            "url": {"type": "url", "description": "target url"},
        },
    )
    caller = FakeJsonCaller({"keyword": "python", "url": "-1"})
    router = SkillRouter(llm_caller=caller)

    result = router._extract_params_with_llm(skill, "搜索 python", {"keyword": "-1", "url": "-1"})

    assert result == {"keyword": "python", "url": "-1"}
    assert caller.calls[0]["schema"]["required"] == ["keyword", "url"]


def test_agent_loop_skill_arbitration_uses_chat_json_with_retry():
    client = FakeJsonClient(
        RuntimeError("Failed to parse JSON from LLM response: bad"),
        {"skill_id": "domain/bilibili_search", "confidence": 0.9},
    )
    agent = AgentLoop(max_steps=3)
    agent._llm_parser = SimpleNamespace(_client=client)
    skills = [
        SimpleNamespace(id="domain/google_search", name="Google 搜索", description="Search Google"),
        SimpleNamespace(id="domain/bilibili_search", name="Bilibili 搜索", description="Search Bilibili"),
    ]

    selected = agent._resolve_skill_with_llm("B站搜索 Python", skills)

    assert selected is skills[1]
    assert len(client.calls) == 2
    assert client.calls[0]["schema"]["required"] == ["skill_id", "confidence"]

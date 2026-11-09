"""Construcao do modelo: offline sem chave e restricao de retencao zero."""

from __future__ import annotations

import json

import httpx
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from src.agent.llm import build_model
from src.config import Settings

ONLINE_SETTINGS = Settings(
    CHAT_PROVIDER="openrouter",
    OPENROUTER_API_KEY="fake",
    OPENROUTER_BASE_URL="https://openrouter.ai/api/v1",
    _env_file=None,
)
DEEPSEEK_SETTINGS = Settings(DEEPSEEK_API_KEY="fake", _env_file=None)

ZERO_RETENTION = {"zdr": True, "data_collection": "deny"}

CHAT_COMPLETION_BODY = {
    "id": "x",
    "object": "chat.completion",
    "created": 1,
    "model": "openai/gpt-4o-mini",
    "provider": "Azure",
    "choices": [
        {
            "index": 0,
            "finish_reason": "stop",
            "native_finish_reason": "stop",
            "message": {"role": "assistant", "content": "ok"},
        }
    ],
    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
}


def test_build_model_without_key_returns_test_model():
    model = build_model(Settings(OPENROUTER_API_KEY="", _env_file=None))

    assert isinstance(model, TestModel)


async def test_build_model_calls_deepseek_without_openrouter_restriction():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=CHAT_COMPLETION_BODY)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        model = build_model(DEEPSEEK_SETTINGS, "deepseek-flash", http_client=client)
        await Agent(model, instructions="x").run("oi")

    assert requests[0].url.host == "api.deepseek.com"
    body = json.loads(requests[0].content)
    assert body["model"] == "deepseek-flash"
    assert "provider" not in body


def test_build_model_applies_zero_retention_provider():
    model = build_model(ONLINE_SETTINGS, "openai/gpt-4o-mini")

    assert model.settings == {"openrouter_provider": ZERO_RETENTION}


async def test_build_model_sends_provider_restriction_on_the_wire():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=CHAT_COMPLETION_BODY)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        model = build_model(ONLINE_SETTINGS, "openai/gpt-4o-mini", http_client=client)
        await Agent(model, instructions="x").run("oi")

    assert json.loads(requests[0].content)["provider"] == ZERO_RETENTION

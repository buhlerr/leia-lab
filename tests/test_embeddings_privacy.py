"""O embedding online tambem envia a restricao de retencao zero."""

from __future__ import annotations

import json

import httpx
import respx

from src.config import Settings
from src.rag.embeddings import EMBEDDING_DIM, get_embedding

ZERO_RETENTION = {"zdr": True, "data_collection": "deny"}


async def _sent_body(settings: Settings) -> dict:
    with respx.mock(assert_all_called=True) as mock:
        route = mock.post("https://openrouter.ai/api/v1/embeddings").mock(
            return_value=httpx.Response(
                200, json={"data": [{"embedding": [0.0] * EMBEDDING_DIM}]}
            )
        )
        await get_embedding("oi", settings)
    return json.loads(route.calls[0].request.content)


def _settings(**overrides) -> Settings:
    return Settings(
        OPENROUTER_API_KEY="fake",
        OPENROUTER_BASE_URL="https://openrouter.ai/api/v1",
        _env_file=None,
        **overrides,
    )


async def test_get_embedding_sends_provider_restriction_when_enabled():
    body = await _sent_body(_settings(EMBEDDING_ZERO_RETENTION=True))
    assert body["provider"] == ZERO_RETENTION


async def test_get_embedding_has_no_restriction_by_default():
    body = await _sent_body(_settings())
    assert "provider" not in body

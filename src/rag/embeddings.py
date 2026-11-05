"""Async embeddings client for the RAG layer.

Wraps the OpenAI-compatible ``/embeddings`` endpoint exposed by OpenRouter
(``settings.OPENROUTER_BASE_URL``). When no API key is configured the module
falls back to a deterministic, offline embedding so that tests, demos and
local development keep working without credentials.
"""

from __future__ import annotations

import hashlib
import logging

import httpx

from src.config import Settings

logger = logging.getLogger(__name__)

EMBEDDING_DIM = 1536
EMBEDDING_TIMEOUT_SECONDS = 30.0


def _deterministic_embedding(text: str, dim: int = EMBEDDING_DIM) -> list[float]:
    """Derive a stable pseudo-embedding from ``text`` using SHA-256.

    The result is L2-normalized, so cosine similarity between two fallback
    vectors stays meaningful (0.0 for unrelated texts, 1.0 for identical ones).
    This is a development/test fallback, never a semantic replacement.
    """
    values: list[float] = []
    seed = text.encode("utf-8")
    counter = 0
    while len(values) < dim:
        digest = hashlib.sha256(seed + counter.to_bytes(4, "big")).digest()
        for offset in range(0, len(digest), 4):
            chunk = digest[offset : offset + 4]
            values.append((int.from_bytes(chunk, "big") / 0xFFFFFFFF) * 2.0 - 1.0)
        counter += 1

    vector = values[:dim]
    norm = sum(value * value for value in vector) ** 0.5
    if norm == 0.0:
        return vector
    return [value / norm for value in vector]


async def get_embedding(text: str, settings: Settings | None = None) -> list[float]:
    """Return a 1536-dimension embedding for ``text``.

    Falls back to :func:`_deterministic_embedding` when ``settings`` has no
    ``OPENROUTER_API_KEY`` (offline / test mode).
    """
    if not text or not text.strip():
        raise ValueError("text must be a non-empty string")

    settings = settings or Settings()

    if not settings.OPENROUTER_API_KEY:
        logger.debug("OPENROUTER_API_KEY not set: using deterministic fallback embedding")
        return _deterministic_embedding(text)

    url = f"{settings.OPENROUTER_BASE_URL.rstrip('/')}/embeddings"
    payload = {
        "model": settings.EMBEDDING_MODEL,
        "input": text,
        "dimensions": EMBEDDING_DIM,
    }
    headers = {"Authorization": f"Bearer {settings.OPENROUTER_API_KEY}"}

    async with httpx.AsyncClient(timeout=httpx.Timeout(EMBEDDING_TIMEOUT_SECONDS)) as client:
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()

    try:
        embedding = data["data"][0]["embedding"]
    except (KeyError, IndexError, TypeError) as exc:  # pragma: no cover - defensive
        raise ValueError("Malformed embeddings response from provider") from exc

    if len(embedding) != EMBEDDING_DIM:
        raise ValueError(
            f"Embedding dimension mismatch: expected {EMBEDDING_DIM}, got {len(embedding)}"
        )

    return [float(value) for value in embedding]

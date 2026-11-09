"""Ferramentas do agente de analise de minutas."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import asyncpg
from pydantic_ai import ModelRetry, RunContext

from src.config import Settings
from src.rag.embeddings import get_embedding
from src.rag.hybrid_search import hybrid_search_rrf

MIN_TOP_K = 1
MAX_TOP_K = 10


@dataclass
class AnalysisDeps:
    pool: asyncpg.Pool
    settings: Settings


async def search_kb(
    ctx: RunContext[AnalysisDeps],
    query: str,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """Busca na base de conhecimento trechos relevantes para a consulta."""
    if not query.strip():
        raise ModelRetry("Informe um texto de busca.")

    top_k = max(MIN_TOP_K, min(MAX_TOP_K, top_k))
    vector = await get_embedding(query, ctx.deps.settings)
    results = await hybrid_search_rrf(ctx.deps.pool, query, vector, top_k=top_k)

    return [
        {
            "title": item["title"],
            "content": item["content"],
            "score": item["score"],
        }
        for item in results
    ]

"""A busca na base de conhecimento roda como ferramenta do agente."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic_ai import Agent, ModelRetry
from pydantic_ai.models.test import TestModel

from src.agent.tools import AnalysisDeps, search_kb
from src.db.connection import init_db


async def _insert_chunk(pool, title: str, content: str) -> None:
    doc_id = await pool.fetchval(
        "INSERT INTO kb_docs (title) VALUES ($1) RETURNING id", title
    )
    await pool.execute(
        "INSERT INTO kb_chunks (doc_id, content, sequence_order) VALUES ($1, $2, 1)",
        doc_id,
        content,
    )


async def test_search_kb_is_called_by_the_agent(pool, settings):
    await init_db(pool)
    await _insert_chunk(
        pool,
        "Contrato de servicos",
        "Clausula de rescisao com aviso previo de 30 dias.",
    )
    agent = Agent(
        TestModel(custom_output_text="ok"),
        deps_type=AnalysisDeps,
        tools=[search_kb],
    )

    result = await agent.run("oi", deps=AnalysisDeps(pool, settings))

    assert result.output == "ok"


async def test_search_kb_rejects_blank_query(pool, settings):
    ctx = SimpleNamespace(deps=AnalysisDeps(pool, settings))

    with pytest.raises(ModelRetry):
        await search_kb(ctx, "   ")

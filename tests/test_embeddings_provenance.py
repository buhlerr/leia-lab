import logging

import pytest
import respx
from httpx import Response

from src.config import Settings
from src.db.connection import init_db
from src.ingest.masking import mask_personal_data as masked
from src.rag import embeddings
from src.rag.embeddings import (
    EMBEDDING_DIM,
    OFFLINE_EMBEDDING_MODEL,
    effective_embedding_model,
    embed_text,
    get_embedding,
)
from src.rag.hybrid_search import _to_pgvector_literal, hybrid_search_rrf

OFFLINE = Settings(OPENROUTER_API_KEY="")
ONLINE = Settings(OPENROUTER_API_KEY="sk-test")


@pytest.fixture(autouse=True)
def _reset_warning():
    embeddings._reset_offline_warning()


def test_offline_model_label_is_distinct_from_configured_model():
    assert OFFLINE_EMBEDDING_MODEL != OFFLINE.EMBEDDING_MODEL
    assert effective_embedding_model(OFFLINE) == OFFLINE_EMBEDDING_MODEL
    assert effective_embedding_model(ONLINE) == ONLINE.EMBEDDING_MODEL


async def test_embed_text_reports_effective_model_offline():
    result = await embed_text(masked("clausula"), OFFLINE)
    assert result.model == OFFLINE_EMBEDDING_MODEL
    assert len(result.vector) == EMBEDDING_DIM
    assert await get_embedding(masked("clausula"), OFFLINE) == result.vector


@respx.mock
async def test_embed_text_reports_configured_model_online():
    respx.post("https://openrouter.ai/api/v1/embeddings").mock(
        return_value=Response(200, json={"data": [{"embedding": [0.1] * EMBEDDING_DIM}]})
    )
    result = await embed_text(masked("clausula"), ONLINE)
    assert result.model == ONLINE.EMBEDDING_MODEL


async def test_offline_fallback_warns_once_per_process(caplog):
    with caplog.at_level(logging.WARNING, logger="src.rag.embeddings"):
        await embed_text(masked("a"), OFFLINE)
        await embed_text(masked("b"), OFFLINE)
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert OFFLINE_EMBEDDING_MODEL in warnings[0].getMessage()


async def test_dense_search_never_compares_offline_and_real_vectors(pool):
    await init_db(pool)
    doc_id = await pool.fetchval("INSERT INTO kb_docs (title) VALUES ('d') RETURNING id")
    text = "prazo da locacao"
    offline_vec = (await embed_text(masked(text), OFFLINE)).vector
    real_vec = [1.0] + [0.0] * (EMBEDDING_DIM - 1)
    for i, (content, vec, model) in enumerate(
        [
            ("chunk offline", offline_vec, OFFLINE_EMBEDDING_MODEL),
            ("chunk real", real_vec, "openai/text-embedding-3-small"),
        ]
    ):
        await pool.execute(
            "INSERT INTO kb_chunks (doc_id, content, sequence_order, embedding, embedding_model) "
            "VALUES ($1, $2, $3, $4::vector, $5)",
            doc_id, content, i, _to_pgvector_literal(vec), model,
        )

    # texto sem match lexical: so o ramo denso contribui.
    off = await hybrid_search_rrf(pool, "zzz", offline_vec, OFFLINE_EMBEDDING_MODEL, top_k=5)
    real = await hybrid_search_rrf(pool, "zzz", real_vec, "openai/text-embedding-3-small", top_k=5)
    assert [r["content"] for r in off] == ["chunk offline"]
    assert [r["content"] for r in real] == ["chunk real"]


async def test_dense_search_excludes_chunks_with_unknown_model(pool):
    await init_db(pool)
    doc_id = await pool.fetchval("INSERT INTO kb_docs (title) VALUES ('d') RETURNING id")
    vec = (await embed_text(masked("prazo"), OFFLINE)).vector
    await pool.execute(
        "INSERT INTO kb_chunks (doc_id, content, sequence_order, embedding, embedding_model) "
        "VALUES ($1, 'legacy', 0, $2::vector, NULL)",
        doc_id, _to_pgvector_literal(vec),
    )
    # dense-only query (no lexical match): NULL-provenance chunk must not be ranked.
    assert await hybrid_search_rrf(pool, "zzz", vec, OFFLINE_EMBEDDING_MODEL, top_k=5) == []

"""O schema do corpus e aplicavel, idempotente e registra a procedencia do vetor."""

from __future__ import annotations

from src.db.connection import init_db


async def _table_names(pool) -> set[str]:
    rows = await pool.fetch(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
    )
    return {row["table_name"] for row in rows}


async def _column_names(pool, table: str) -> set[str]:
    rows = await pool.fetch(
        "SELECT column_name FROM information_schema.columns WHERE table_name = $1", table
    )
    return {row["column_name"] for row in rows}


async def test_init_db_creates_corpus_tables(pool):
    await init_db(pool)
    assert {"kb_docs", "kb_chunks"} <= await _table_names(pool)


async def test_kb_chunks_records_embedding_model(pool):
    await init_db(pool)
    columns = await _column_names(pool, "kb_chunks")
    assert {"embedding", "tsv_content", "embedding_model", "indexed_at"} <= columns


async def test_init_db_is_idempotent(pool):
    await init_db(pool)
    await init_db(pool)
    assert {"kb_docs", "kb_chunks"} <= await _table_names(pool)

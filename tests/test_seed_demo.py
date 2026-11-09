"""Dados ficticios de demonstracao: o seed e idempotente e nao sobrescreve prompts.

Cada teste comeca com o schema `public` vazio (fixture `pool`), aplica o DDL e
roda o seed. O seed usa a fixture `settings` em modo offline, entao o embedding
vem do fallback deterministico e nao depende de rede.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.seed_demo import DEMO_TYPE_NAME, OFFLINE_EMBEDDING_LABEL, seed_demo
from src.db.connection import init_db

FIXTURE_PATH = Path(__file__).with_name("fixtures") / "minuta_demo.txt"


async def _seed(pool, settings) -> None:
    await init_db(pool)
    await seed_demo(pool, settings)


async def _counts(pool) -> tuple[int, int, int, int]:
    return (
        await pool.fetchval("SELECT count(*) FROM minuta_types"),
        await pool.fetchval("SELECT count(*) FROM minuta_reports"),
        await pool.fetchval("SELECT count(*) FROM kb_docs"),
        await pool.fetchval("SELECT count(*) FROM kb_chunks"),
    )


def test_demo_minuta_fixture_exists_and_is_not_empty():
    assert FIXTURE_PATH.is_file()
    assert FIXTURE_PATH.read_text(encoding="utf-8").strip()


async def test_seed_demo_creates_type_reports_and_chunks(pool, settings):
    await _seed(pool, settings)

    type_count = await pool.fetchval("SELECT count(*) FROM minuta_types")
    assert type_count == 1

    rows = await pool.fetch(
        """
        SELECT r.name, r.kind, r.execution_order, r.model, t.name AS type_name
        FROM minuta_reports r
        JOIN minuta_types t ON t.id = r.minuta_type_id
        ORDER BY r.execution_order
        """
    )
    assert [row["execution_order"] for row in rows] == [1, 2, 3]
    assert [row["name"] for row in rows] == [
        "Resumo do objeto",
        "Clausulas essenciais",
        "Parecer de riscos",
    ]
    assert [row["kind"] for row in rows] == ["parecer", "checklist", "parecer"]
    assert all(row["model"] is None for row in rows)
    assert all(row["type_name"] == DEMO_TYPE_NAME for row in rows)

    chunks = await pool.fetch("SELECT embedding_model FROM kb_chunks")
    assert len(chunks) == 4
    assert all(row["embedding_model"] == OFFLINE_EMBEDDING_LABEL for row in chunks)


async def test_seed_demo_keeps_existing_docs_when_embedding_fails(pool, settings, monkeypatch):
    await _seed(pool, settings)

    async def failing_embedding(_text, _settings):
        raise RuntimeError("provedor fora do ar")

    monkeypatch.setattr("scripts.seed_demo.get_embedding", failing_embedding)
    online = settings.model_copy(update={"OPENROUTER_API_KEY": "fake"})
    with pytest.raises(RuntimeError):
        await seed_demo(pool, online)

    assert await pool.fetchval("SELECT count(*) FROM kb_chunks") == 4


async def test_seed_demo_replaces_offline_vectors_when_key_appears(pool, settings, monkeypatch):
    await _seed(pool, settings)

    async def fake_embedding(_text, _settings):
        return [0.1] * 1536

    monkeypatch.setattr("scripts.seed_demo.get_embedding", fake_embedding)
    online = settings.model_copy(update={"OPENROUTER_API_KEY": "fake"})
    await seed_demo(pool, online)

    chunks = await pool.fetch("SELECT embedding_model FROM kb_chunks")
    assert len(chunks) == 4
    assert all(row["embedding_model"] == online.EMBEDDING_MODEL for row in chunks)


async def test_seed_demo_is_idempotent(pool, settings):
    await _seed(pool, settings)
    counts = await _counts(pool)

    await seed_demo(pool, settings)

    assert await _counts(pool) == counts


async def test_seed_demo_does_not_overwrite_changed_prompt(pool, settings):
    await _seed(pool, settings)
    custom_prompt = "Prompt ajustado a mao pela equipe."
    await pool.execute(
        "UPDATE minuta_reports SET prompt = $1 WHERE name = $2",
        custom_prompt,
        "Resumo do objeto",
    )

    await seed_demo(pool, settings)

    prompt = await pool.fetchval(
        "SELECT prompt FROM minuta_reports WHERE name = $1", "Resumo do objeto"
    )
    assert prompt == custom_prompt

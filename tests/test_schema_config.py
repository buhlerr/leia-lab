"""O schema de configuracao da analise e aplicavel, idempotente e guarda as regras."""

from __future__ import annotations

import asyncpg
import pytest

from src.db.connection import init_db


async def _table_names(pool) -> set[str]:
    rows = await pool.fetch(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
    )
    return {row["table_name"] for row in rows}


async def _insert_type(pool, name: str = "compra") -> str:
    return await pool.fetchval(
        "INSERT INTO minuta_types (name) VALUES ($1) RETURNING id", name
    )


async def _insert_report(
    pool,
    minuta_type_id,
    name: str = "parecer-final",
    kind: str = "parecer",
    prompt: str = "Analise as clausulas de risco da minuta.",
    model: str | None = None,
    execution_order: int = 1,
) -> str:
    return await pool.fetchval(
        """
        INSERT INTO minuta_reports
            (minuta_type_id, name, kind, prompt, model, execution_order)
        VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING id
        """,
        minuta_type_id,
        name,
        kind,
        prompt,
        model,
        execution_order,
    )


async def test_init_db_creates_config_tables(pool):
    await init_db(pool)
    assert {"minuta_types", "minuta_reports"} <= await _table_names(pool)


async def test_init_db_config_is_idempotent(pool):
    await init_db(pool)
    await init_db(pool)
    assert {"minuta_types", "minuta_reports"} <= await _table_names(pool)


async def test_valid_report_is_accepted_with_null_model(pool):
    await init_db(pool)
    type_id = await _insert_type(pool)
    report_id = await _insert_report(pool, type_id)
    row = await pool.fetchrow("SELECT model FROM minuta_reports WHERE id = $1", report_id)
    assert row["model"] is None


async def test_kind_outside_allowed_list_is_rejected(pool):
    await init_db(pool)
    type_id = await _insert_type(pool)
    with pytest.raises(asyncpg.exceptions.CheckViolationError):
        await _insert_report(pool, type_id, kind="resumo")


async def test_kind_null_is_rejected(pool):
    await init_db(pool)
    type_id = await _insert_type(pool)
    with pytest.raises(asyncpg.exceptions.NotNullViolationError):
        await _insert_report(pool, type_id, kind=None)


async def test_prompt_with_only_spaces_is_rejected(pool):
    await init_db(pool)
    type_id = await _insert_type(pool)
    with pytest.raises(asyncpg.exceptions.CheckViolationError):
        await _insert_report(pool, type_id, prompt="   ")


async def test_execution_order_zero_is_rejected(pool):
    await init_db(pool)
    type_id = await _insert_type(pool)
    with pytest.raises(asyncpg.exceptions.CheckViolationError):
        await _insert_report(pool, type_id, execution_order=0)


async def test_duplicate_execution_order_for_same_type_is_rejected(pool):
    await init_db(pool)
    type_id = await _insert_type(pool)
    await _insert_report(pool, type_id, name="primeiro", execution_order=1)
    with pytest.raises(asyncpg.exceptions.UniqueViolationError):
        await _insert_report(pool, type_id, name="segundo", execution_order=1)


async def test_duplicate_name_for_same_type_is_rejected(pool):
    await init_db(pool)
    type_id = await _insert_type(pool)
    await _insert_report(pool, type_id, execution_order=1)
    with pytest.raises(asyncpg.exceptions.UniqueViolationError):
        await _insert_report(pool, type_id, execution_order=2)


async def test_different_types_may_repeat_execution_order(pool):
    await init_db(pool)
    first_type_id = await _insert_type(pool, "compra")
    second_type_id = await _insert_type(pool, "venda")
    await _insert_report(pool, first_type_id, execution_order=1)
    await _insert_report(pool, second_type_id, execution_order=1)
    total = await pool.fetchval("SELECT count(*) FROM minuta_reports")
    assert total == 2


async def test_duplicate_type_name_is_rejected(pool):
    await init_db(pool)
    await _insert_type(pool, "compra")
    with pytest.raises(asyncpg.exceptions.UniqueViolationError):
        await _insert_type(pool, "compra")


async def test_deleting_type_with_reports_is_rejected(pool):
    await init_db(pool)
    type_id = await _insert_type(pool)
    await _insert_report(pool, type_id)
    with pytest.raises(asyncpg.exceptions.ForeignKeyViolationError):
        await pool.execute("DELETE FROM minuta_types WHERE id = $1", type_id)

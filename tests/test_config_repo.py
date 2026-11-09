"""O repositorio de leitura devolve a configuracao de minutas vigente no banco."""

from __future__ import annotations

from src.db.config_repo import (
    MinutaReport,
    MinutaType,
    get_minuta_type,
    list_minuta_types,
    list_reports,
)
from src.db.connection import init_db

MISSING_ID = "00000000-0000-0000-0000-000000000000"


async def _insert_type(pool, name: str) -> str:
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


async def test_list_minuta_types_orders_by_name(pool):
    await init_db(pool)
    await _insert_type(pool, "venda")
    await _insert_type(pool, "compra")
    await _insert_type(pool, "locacao")

    types = await list_minuta_types(pool)

    assert [item.name for item in types] == ["compra", "locacao", "venda"]
    assert all(isinstance(item, MinutaType) for item in types)


async def test_list_reports_orders_by_execution_and_filters_by_type(pool):
    await init_db(pool)
    compra_id = await _insert_type(pool, "compra")
    venda_id = await _insert_type(pool, "venda")
    await _insert_report(pool, compra_id, name="terceiro", execution_order=3)
    await _insert_report(pool, compra_id, name="primeiro", execution_order=1)
    await _insert_report(pool, compra_id, name="segundo", execution_order=2)
    await _insert_report(pool, venda_id, name="outro-tipo", execution_order=1)

    reports = await list_reports(pool, compra_id)

    assert [item.name for item in reports] == ["primeiro", "segundo", "terceiro"]
    assert [item.execution_order for item in reports] == [1, 2, 3]
    assert {item.minuta_type_id for item in reports} == {str(compra_id)}
    assert all(isinstance(item, MinutaReport) for item in reports)


async def test_list_reports_keeps_null_model_as_none(pool):
    await init_db(pool)
    type_id = await _insert_type(pool, "compra")
    await _insert_report(pool, type_id, model=None)

    reports = await list_reports(pool, type_id)

    assert reports[0].model is None


async def test_get_minuta_type_returns_none_for_unknown_id(pool):
    await init_db(pool)

    assert await get_minuta_type(pool, MISSING_ID) is None


async def test_list_reports_reflects_updated_prompt(pool):
    await init_db(pool)
    type_id = await _insert_type(pool, "compra")
    report_id = await _insert_report(pool, type_id, prompt="Texto antigo")
    await pool.execute(
        "UPDATE minuta_reports SET prompt = $1 WHERE id = $2",
        "Texto novo",
        report_id,
    )

    reports = await list_reports(pool, type_id)

    assert reports[0].prompt == "Texto novo"

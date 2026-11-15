"""A escrita da configuracao valida campos e respeita as constraints."""

from __future__ import annotations

import pytest

from src.db.config_admin import (
    ConfigAdminError,
    create_minuta_type,
    create_report,
    delete_minuta_type,
    delete_report,
    rename_minuta_type,
    swap_report_order,
    update_report,
    validate_report,
    validate_type_name,
)
from src.db.config_repo import list_reports
from src.db.connection import init_db


def test_validate_type_name_strips_and_rejects_empty():
    assert validate_type_name("  compra ") == "compra"
    with pytest.raises(ConfigAdminError):
        validate_type_name("   ")


def test_validate_report_normalizes_fields():
    assert validate_report("  Risco ", "parecer", "  Analise. ", "  ") == (
        "Risco",
        "parecer",
        "Analise.",
        None,
    )


@pytest.mark.parametrize(
    ("name", "kind", "prompt"),
    [
        ("  ", "parecer", "Analise."),
        ("Risco", "resumo", "Analise."),
        ("Risco", "parecer", "   "),
    ],
)
def test_validate_report_rejects_invalid_fields(name, kind, prompt):
    with pytest.raises(ConfigAdminError):
        validate_report(name, kind, prompt, None)


async def test_create_minuta_type_rejects_duplicate(pool):
    await init_db(pool)

    type_id = await create_minuta_type(pool, " compra ")

    assert type_id
    with pytest.raises(ConfigAdminError):
        await create_minuta_type(pool, "compra")


async def test_rename_minuta_type_reflects_new_name(pool):
    await init_db(pool)
    type_id = await create_minuta_type(pool, "compra")

    await rename_minuta_type(pool, type_id, "venda")

    row = await pool.fetchrow("SELECT name FROM minuta_types WHERE id = $1", type_id)
    assert row["name"] == "venda"
    with pytest.raises(ConfigAdminError):
        await rename_minuta_type(pool, type_id, "   ")


async def test_delete_minuta_type_is_blocked_while_reports_exist(pool):
    await init_db(pool)
    type_id = await create_minuta_type(pool, "compra")
    await create_report(
        pool, type_id, name="Risco", kind="parecer", prompt="Analise.", model=None
    )

    with pytest.raises(ConfigAdminError):
        await delete_minuta_type(pool, type_id)


async def test_delete_minuta_type_without_reports(pool):
    await init_db(pool)
    type_id = await create_minuta_type(pool, "compra")

    await delete_minuta_type(pool, type_id)

    assert await pool.fetchval("SELECT count(*) FROM minuta_types") == 0


async def test_create_report_appends_at_the_end(pool):
    await init_db(pool)
    type_id = await create_minuta_type(pool, "compra")

    await create_report(
        pool, type_id, name="Risco", kind="parecer", prompt="Analise.", model=None
    )
    await create_report(
        pool, type_id, name="Checklist", kind="checklist", prompt="Verifique.", model=None
    )

    reports = await list_reports(pool, type_id)
    assert [(r.name, r.execution_order) for r in reports] == [
        ("Risco", 1),
        ("Checklist", 2),
    ]


async def test_create_report_rejects_duplicate_name(pool):
    await init_db(pool)
    type_id = await create_minuta_type(pool, "compra")
    await create_report(
        pool, type_id, name="Risco", kind="parecer", prompt="Analise.", model=None
    )

    with pytest.raises(ConfigAdminError):
        await create_report(
            pool, type_id, name="Risco", kind="parecer", prompt="Outro.", model=None
        )


async def test_update_report_changes_all_fields(pool):
    await init_db(pool)
    type_id = await create_minuta_type(pool, "compra")
    report_id = await create_report(
        pool, type_id, name="Risco", kind="parecer", prompt="Analise.", model=None
    )

    await update_report(
        pool,
        type_id,
        report_id,
        name="Checklist",
        kind="checklist",
        prompt="Verifique as clausulas.",
        model="deepseek-flash",
    )

    report = (await list_reports(pool, type_id))[0]
    assert report.name == "Checklist"
    assert report.kind == "checklist"
    assert report.prompt == "Verifique as clausulas."
    assert report.model == "deepseek-flash"


async def test_delete_report_removes_only_the_target(pool):
    await init_db(pool)
    type_id = await create_minuta_type(pool, "compra")
    first = await create_report(
        pool, type_id, name="Risco", kind="parecer", prompt="Analise.", model=None
    )
    await create_report(
        pool, type_id, name="Checklist", kind="checklist", prompt="Verifique.", model=None
    )

    await delete_report(pool, type_id, first)

    assert [r.name for r in await list_reports(pool, type_id)] == ["Checklist"]


async def test_swap_report_order_exchanges_positions(pool):
    await init_db(pool)
    type_id = await create_minuta_type(pool, "compra")
    names = ["primeiro", "segundo", "terceiro"]
    ids = [
        await create_report(
            pool, type_id, name=name, kind="parecer", prompt="Analise.", model=None
        )
        for name in names
    ]

    await swap_report_order(pool, type_id, ids[0], ids[1])

    reports = await list_reports(pool, type_id)
    assert [(r.name, r.execution_order) for r in reports] == [
        ("segundo", 1),
        ("primeiro", 2),
        ("terceiro", 3),
    ]

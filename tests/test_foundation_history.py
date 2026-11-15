"""Append-only history by trigger on every domain table (bead leia-lab-1g1.9)."""

from __future__ import annotations

import asyncpg
import pytest

from tests.conftest import TEST_DATABASE_URL

DOMAIN_TABLES = ["minuta_types", "themes", "risk_matrix", "prompts"]


async def _seed_min(pool) -> int:
    tid = await pool.fetchval(
        "INSERT INTO minuta_types (slug, name, classifier_description) VALUES ('t', 'T', 'desc') RETURNING id"
    )
    th = await pool.fetchval("INSERT INTO themes (minuta_type_id, slug) VALUES ($1, 'x') RETURNING id", tid)
    await pool.execute(
        "INSERT INTO risk_matrix (theme_id, risk_id, description, criticality) VALUES ($1, 'R', 'd', 'amarelo')", th
    )
    await pool.execute("INSERT INTO prompts (minuta_type_id, kind, prompt_text) VALUES ($1, 'k', 'p')", tid)
    return tid


async def test_insert_update_delete_on_every_domain_table_is_logged(fpool):
    await _seed_min(fpool)
    await fpool.execute("UPDATE minuta_types SET name='T2'")
    await fpool.execute("UPDATE themes SET description='d'")
    await fpool.execute("UPDATE risk_matrix SET description='d2'")
    await fpool.execute("UPDATE prompts SET prompt_text='p2'")
    await fpool.execute("DELETE FROM prompts")
    await fpool.execute("DELETE FROM risk_matrix")
    rows = await fpool.fetch("SELECT table_name, op FROM domain_history")
    seen = {(r["table_name"], r["op"]) for r in rows}
    for t in DOMAIN_TABLES:
        assert (t, "INSERT") in seen and (t, "UPDATE") in seen, t
    assert ("prompts", "DELETE") in seen and ("risk_matrix", "DELETE") in seen


async def test_update_keeps_old_and_new_row_and_db_user(fpool):
    await _seed_min(fpool)
    await fpool.execute("UPDATE risk_matrix SET criticality='vermelho'")
    h = await fpool.fetchrow(
        "SELECT old_row->>'criticality' AS o, new_row->>'criticality' AS n, db_user, changed_at "
        "FROM domain_history WHERE table_name='risk_matrix' AND op='UPDATE'"
    )
    assert (h["o"], h["n"]) == ("amarelo", "vermelho")
    assert h["db_user"] == "leia" and h["changed_at"] is not None


async def test_write_from_an_independent_connection_is_captured(fpool):
    """Stands in for a direct psql write: a different connection, no app code involved."""
    await _seed_min(fpool)
    conn = await asyncpg.connect(TEST_DATABASE_URL)
    try:
        await conn.execute("UPDATE risk_matrix SET description='edited outside the app'")
    finally:
        await conn.close()
    n = await fpool.fetchval(
        "SELECT count(*) FROM domain_history WHERE table_name='risk_matrix' "
        "AND new_row->>'description'='edited outside the app'"
    )
    assert n == 1


async def test_noop_update_is_not_logged(fpool):
    await _seed_min(fpool)
    before = await fpool.fetchval("SELECT count(*) FROM domain_history")
    await fpool.execute("UPDATE risk_matrix SET description = description")
    assert await fpool.fetchval("SELECT count(*) FROM domain_history") == before


@pytest.mark.parametrize("sql", ["UPDATE domain_history SET op='INSERT'", "DELETE FROM domain_history",
                                 "TRUNCATE domain_history"])
async def test_history_is_append_only_even_for_the_owner(fpool, sql):
    await _seed_min(fpool)
    with pytest.raises(asyncpg.PostgresError):
        await fpool.execute(sql)
    assert await fpool.fetchval("SELECT count(*) FROM domain_history") >= 4


async def test_truncate_of_a_domain_table_is_forbidden(fpool):
    await _seed_min(fpool)
    with pytest.raises(asyncpg.PostgresError):
        await fpool.execute("TRUNCATE prompts")


async def test_app_role_has_no_write_on_history_but_can_edit_domain_and_is_logged(fpool):
    await _seed_min(fpool)
    async with fpool.acquire() as conn:
        await conn.execute("SET ROLE leia_app")
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await conn.execute("DELETE FROM domain_history")
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await conn.execute("INSERT INTO domain_history (table_name,row_id,op) VALUES ('x',1,'INSERT')")
        # app role can edit the domain; the SECURITY DEFINER trigger still logs it.
        await conn.execute("UPDATE risk_matrix SET description='by app role'")
        await conn.execute("RESET ROLE")
    assert await fpool.fetchval(
        "SELECT count(*) FROM domain_history WHERE new_row->>'description'='by app role'"
    ) == 1


async def test_foundation_schema_is_idempotent(fpool):
    from src.foundation.db import init_foundation

    await _seed_min(fpool)
    await init_foundation(fpool)
    assert await fpool.fetchval("SELECT count(*) FROM minuta_types") == 1

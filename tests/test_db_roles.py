"""Papéis mínimos de banco (VIT-22): ``leia_api`` grava só a análise; ``leia_readonly`` não grava nada.

A API roda com um login membro de ``leia_api``; o admin, com um login membro de ``leia_app``, o papel
que edita a matriz. Cada operação fora do papel cai no grant do banco, não num hábito de código.
Inventário de papeis e logins de produção: ``docs/OPERACAO.md``.
"""

from __future__ import annotations

import uuid

import asyncpg
import pytest

from src.db.connection import init_db
from tests.conftest import TEST_DATABASE_URL

API_ROLE = "leia_api"
READONLY_ROLE = "leia_readonly"

DOMAIN_READ_TABLES = [
    "minuta_types",
    "themes",
    "risk_matrix",
    "prompts",
    "domain_history",
    "kb_docs",
    "kb_chunks",
]
READONLY_TABLES = [*DOMAIN_READ_TABLES, "data_versions", "analyses", "analysis_trail"]
ALL_PRIVILEGES = ["SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"]

API_GRANTS = {t: {"SELECT"} for t in DOMAIN_READ_TABLES} | {
    "analyses": {"SELECT", "INSERT", "UPDATE"},
    "analysis_trail": {"SELECT", "INSERT"},
}


@pytest.fixture
async def dpool(pool):
    await init_db(pool)
    return pool


async def _granted_privileges(pool, role: str, tables: list[str]) -> dict[str, set[str]]:
    return {
        t: {p for p in ALL_PRIVILEGES if await pool.fetchval("SELECT has_table_privilege($1, $2, $3)", role, t, p)}
        for t in tables
    }


async def _is_group_role(pool, role: str) -> bool:
    row = await pool.fetchrow(
        "SELECT rolcanlogin, rolinherit FROM pg_roles WHERE rolname = $1", role
    )
    return row is not None and not row["rolcanlogin"] and row["rolinherit"]


async def test_leia_api_has_exactly_the_analysis_grants(dpool):
    assert await _is_group_role(dpool, API_ROLE)
    assert await dpool.fetchval("SELECT has_schema_privilege($1, 'public', 'USAGE')", API_ROLE)
    assert await _granted_privileges(dpool, API_ROLE, list(API_GRANTS)) == API_GRANTS
    assert await dpool.fetchval("SELECT has_sequence_privilege($1, 'analysis_trail_id_seq', 'USAGE')", API_ROLE)
    for seq in ("minuta_types_id_seq", "themes_id_seq", "risk_matrix_id_seq", "prompts_id_seq"):
        assert not await dpool.fetchval("SELECT has_sequence_privilege($1, $2, 'USAGE')", API_ROLE, seq)
    assert not await dpool.fetchval("SELECT has_table_privilege($1, 'data_versions', 'SELECT')", API_ROLE)


async def test_leia_readonly_reads_the_domain_and_nothing_else(dpool):
    assert await _is_group_role(dpool, READONLY_ROLE)
    assert await dpool.fetchval("SELECT has_schema_privilege($1, 'public', 'USAGE')", READONLY_ROLE)
    assert await _granted_privileges(dpool, READONLY_ROLE, READONLY_TABLES) == {
        t: {"SELECT"} for t in READONLY_TABLES
    }
    for seq in ("minuta_types_id_seq", "themes_id_seq", "risk_matrix_id_seq", "prompts_id_seq",
                "analysis_trail_id_seq"):
        assert not await dpool.fetchval("SELECT has_sequence_privilege($1, $2, 'USAGE')", READONLY_ROLE, seq)


async def test_leia_api_runs_the_analysis_lifecycle(dpool):
    """O fluxo inteiro de ``src/db/analyses.py`` passa com o papel mínimo: nada além dele."""
    analysis_id = uuid.uuid4()
    async with dpool.acquire() as conn:
        await conn.execute(f"SET ROLE {API_ROLE}")
        try:
            await conn.execute(
                "INSERT INTO analyses (id, filename_alias, text_sha256, params, rules_snapshot, rules_hash, "
                "matrix_version, prompt_version, domain_history_id, idempotency_key) "
                "VALUES ($1::uuid, 'documento-1.txt', 'h', '{}'::jsonb, '{}'::jsonb, 'rh', 'mv', 'pv', 0, 'k1')",
                analysis_id,
            )
            await conn.execute(
                "INSERT INTO analysis_trail (analysis_id, seq, step, matrix_version, prompt_version) "
                "VALUES ($1::uuid, 1, 'iniciar', 'mv', 'pv')",
                analysis_id,
            )
            await conn.execute(
                "UPDATE analyses SET status = 'done', minuta_type = 'residencial', "
                "report = '{}'::jsonb, finished_at = now() WHERE id = $1::uuid",
                analysis_id,
            )
            await conn.fetch("SELECT id, slug FROM minuta_types WHERE active")
        finally:
            await conn.execute("RESET ROLE")
    assert await dpool.fetchval("SELECT status FROM analyses WHERE id = $1::uuid", analysis_id) == "done"


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE risk_matrix SET active = NOT active",
        "INSERT INTO risk_matrix (theme_id, risk_id, description, criticality) "
        "SELECT id, 'r', 'd', 'verde' FROM themes",
        "DELETE FROM risk_matrix",
        "UPDATE domain_history SET op = 'INSERT'",
        "INSERT INTO domain_history (table_name, row_id, op) VALUES ('x', 1, 'INSERT')",
        "INSERT INTO data_versions (name, sha256) VALUES ('x/v1', 'h')",
        "INSERT INTO kb_docs (title) VALUES ('x')",
        "UPDATE analysis_trail SET step = 'x'",
        "DELETE FROM analysis_trail",
        "TRUNCATE analysis_trail",
        "DELETE FROM analyses",
        "TRUNCATE analyses",
    ],
)
async def test_leia_api_cannot_write_the_matrix_or_erase_the_audit(dpool, sql):
    await _seed_row(dpool)
    counts = [await dpool.fetchval(f"SELECT count(*) FROM {t}") for t in ("risk_matrix", "analysis_trail")]
    async with dpool.acquire() as conn:
        await conn.execute(f"SET ROLE {API_ROLE}")
        try:
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await conn.execute(sql)
        finally:
            await conn.execute("RESET ROLE")
    assert [await dpool.fetchval(f"SELECT count(*) FROM {t}") for t in ("risk_matrix", "analysis_trail")] == counts


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO analyses (filename_alias, text_sha256, rules_snapshot, rules_hash, matrix_version, "
        "prompt_version, domain_history_id) VALUES ('documento-1.txt', 'h', '{}'::jsonb, 'rh', 'mv', 'pv', 0)",
        "INSERT INTO analysis_trail (analysis_id, seq, step, matrix_version, prompt_version) "
        "SELECT id, 1, 'x', 'mv', 'pv' FROM analyses",
        "UPDATE risk_matrix SET active = NOT active",
        "DELETE FROM analyses",
        "DELETE FROM analysis_trail",
        "TRUNCATE analyses",
    ],
)
async def test_leia_readonly_cannot_write_anything(dpool, sql):
    await _seed_row(dpool)
    async with dpool.acquire() as conn:
        await conn.execute(f"SET ROLE {READONLY_ROLE}")
        try:
            for table in READONLY_TABLES:
                await conn.fetch(f"SELECT count(*) FROM {table}")
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await conn.execute(sql)
        finally:
            await conn.execute("RESET ROLE")


async def _seed_row(pool) -> None:
    """Uma linha na matriz e uma análise, para os UPDATE/DELETE terem o que mirar."""
    if await pool.fetchval("SELECT count(*) FROM risk_matrix") == 0:
        tid = await pool.fetchval(
            "INSERT INTO minuta_types (slug, name, classifier_description) VALUES ('t', 'T', 'd') RETURNING id"
        )
        theme_id = await pool.fetchval(
            "INSERT INTO themes (minuta_type_id, slug) VALUES ($1, 'x') RETURNING id", tid
        )
        await pool.execute(
            "INSERT INTO risk_matrix (theme_id, risk_id, description, criticality) "
            "VALUES ($1, 'r', 'd', 'verde')",
            theme_id,
        )
    if await pool.fetchval("SELECT count(*) FROM analyses") == 0:
        await pool.execute(
            "INSERT INTO analyses (filename_alias, text_sha256, rules_snapshot, rules_hash, matrix_version, "
            "prompt_version, domain_history_id) VALUES ('documento-1.txt', 'h', '{}'::jsonb, 'rh', 'mv', 'pv', 0)"
        )

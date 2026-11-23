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

API_ROLE = "leia_api"
READONLY_ROLE = "leia_readonly"
APP_ROLE = "leia_app"

# Guardioes do schema: so o dono os instala em gatilhos; EXECUTE publico abriria a forja de
# auditoria via TEMP TABLE + gatilho proprio (domain_history_log e SECURITY DEFINER).
GUARD_FUNCTIONS = ("domain_history_log()", "forbid_change()", "analyses_guard()")
# As colunas que finish_analysis/fail_analysis tocam (src/db/analyses.py); fora delas, sem grant.
FINISH_COLUMNS = ("status", "minuta_type", "report", "finished_at")
IMMUTABLE_COLUMNS = ("filename_alias", "text_sha256", "rules_snapshot", "idempotency_key")

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


# ---------------------------------------------------------------- funcoes guardias (revisao PR 55)


async def test_guard_functions_stay_with_the_owner_and_the_matrix_trigger_still_logs(dpool):
    """MED 1: nem PUBLIC nem os papeis minimos executam os guardioes; o caminho legitimo segue."""
    for fn in GUARD_FUNCTIONS:
        for role in ("public", API_ROLE, READONLY_ROLE):
            assert not await dpool.fetchval(
                "SELECT has_function_privilege($1, $2, 'EXECUTE')", role, fn
            ), f"{fn} executavel por {role}"
    await _seed_row(dpool)
    before = await dpool.fetchval("SELECT count(*) FROM domain_history")
    async with dpool.acquire() as conn:
        await conn.execute(f"SET ROLE {APP_ROLE}")
        try:
            await conn.execute("UPDATE risk_matrix SET active = NOT active")
        finally:
            await conn.execute("RESET ROLE")
    assert await dpool.fetchval("SELECT count(*) FROM domain_history") == before + 1


@pytest.mark.parametrize("role", [API_ROLE, READONLY_ROLE])
async def test_minimal_roles_cannot_forge_domain_history_with_a_temp_table(dpool, role):
    """MED 1: TEMP TABLE + gatilho chamando domain_history_log() e negado na criacao do gatilho."""
    async with dpool.acquire() as conn:
        await conn.execute(f"SET ROLE {role}")
        try:
            await conn.execute("CREATE TEMP TABLE fake_matrix (id bigint)")
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await conn.execute(
                    "CREATE TRIGGER fake AFTER INSERT ON fake_matrix FOR EACH ROW "
                    "EXECUTE FUNCTION domain_history_log()"
                )
        finally:
            await conn.execute("RESET ROLE")
            await conn.execute("DROP TABLE IF EXISTS pg_temp.fake_matrix")


async def test_init_db_converges_by_revoking_excess_grants(dpool):
    """MED 2: init converge, nao acumula: grant excedente de versao anterior nao sobrevive."""
    await dpool.execute(f"GRANT DELETE ON risk_matrix TO {API_ROLE}")
    await dpool.execute(f"GRANT USAGE ON SEQUENCE minuta_types_id_seq TO {READONLY_ROLE}")
    await init_db(dpool)
    assert not await dpool.fetchval("SELECT has_table_privilege($1, 'risk_matrix', 'DELETE')", API_ROLE)
    assert not await dpool.fetchval(
        "SELECT has_sequence_privilege($1, 'minuta_types_id_seq', 'USAGE')", READONLY_ROLE
    )
    assert await dpool.fetchval("SELECT has_table_privilege($1, 'analyses', 'INSERT')", API_ROLE)


async def test_leia_api_updates_only_the_columns_of_the_finish(dpool):
    """LOW 1: UPDATE de analyses e por coluna; fora do termino, negado pelo grant, antes do gatilho."""
    await _seed_row(dpool)
    analysis_id = await dpool.fetchval("SELECT id FROM analyses LIMIT 1")
    for col in FINISH_COLUMNS:
        assert await dpool.fetchval(
            "SELECT has_column_privilege($1, 'analyses', $2, 'UPDATE')", API_ROLE, col
        ), col
    for col in IMMUTABLE_COLUMNS:
        assert not await dpool.fetchval(
            "SELECT has_column_privilege($1, 'analyses', $2, 'UPDATE')", API_ROLE, col
        ), col
    async with dpool.acquire() as conn:
        await conn.execute(f"SET ROLE {API_ROLE}")
        try:
            # A mensagem distingue a negacao do grant ("permission denied") da do gatilho.
            with pytest.raises(asyncpg.InsufficientPrivilegeError, match="permission denied"):
                await conn.execute(
                    "UPDATE analyses SET idempotency_key = 'outra' WHERE id = $1", analysis_id
                )
        finally:
            await conn.execute("RESET ROLE")


@pytest.mark.parametrize("role", [API_ROLE, READONLY_ROLE])
async def test_minimal_roles_cannot_create_or_drop_tables_in_public(dpool, role):
    """LOW 4: o papel nao cria nem derruba tabela no espaco da Leia."""
    async with dpool.acquire() as conn:
        await conn.execute(f"SET ROLE {role}")
        try:
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await conn.execute("CREATE TABLE fora_do_papel (id INT)")
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await conn.execute("DROP TABLE analyses")
        finally:
            await conn.execute("RESET ROLE")


async def test_reinit_keeps_third_party_tables_and_stays_idempotent(pool):
    """LOW 4: init duas vezes com os papeis minimos; tabelas de terceiros (directus_*) intocadas."""
    await pool.execute("CREATE TABLE directus_users (id INT PRIMARY KEY, email TEXT)")
    await pool.execute("INSERT INTO directus_users VALUES (1, 'alguem@exemplo.invalid')")
    await init_db(pool)
    await init_db(pool)
    assert await pool.fetchval("SELECT email FROM directus_users WHERE id = 1") == "alguem@exemplo.invalid"
    for role in (API_ROLE, READONLY_ROLE):
        assert not await pool.fetchval("SELECT has_table_privilege($1, 'directus_users', 'SELECT')", role)
    assert await pool.fetchval("SELECT has_table_privilege($1, 'analyses', 'INSERT')", API_ROLE)

"""Esquema de dominio (M1): idempotencia, historico append-only, snapshot congelado e papeis."""

from __future__ import annotations

import json
from urllib.parse import urlsplit, urlunsplit

import asyncpg
import pytest

from src.db.connection import init_db
from tests.conftest import TEST_DATABASE_URL

DOMAIN_TABLES = ["minuta_types", "themes", "risk_matrix", "prompts"]
ALL_TABLES = {*DOMAIN_TABLES, "domain_history", "analyses", "analysis_trail", "kb_docs", "kb_chunks"}

# Corpus como estava antes da M1 (schema.sql do master em dd54227, sem as colunas de procedencia).
LEGACY_CORPUS_DDL = """
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE kb_docs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(), title TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'kb', metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE kb_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(), doc_id UUID REFERENCES kb_docs(id) ON DELETE CASCADE,
    content TEXT NOT NULL, sequence_order INT NOT NULL,
    tsv_content TSVECTOR GENERATED ALWAYS AS (to_tsvector('portuguese', content)) STORED,
    embedding VECTOR(1536), created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE directus_users (id INT PRIMARY KEY, email TEXT);
INSERT INTO directus_users VALUES (1, 'alguem@exemplo.invalid');
"""


@pytest.fixture
async def dpool(pool):
    await init_db(pool)
    return pool


async def _tables(pool) -> set[str]:
    rows = await pool.fetch("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
    return {r["table_name"] for r in rows}


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


async def _insert_analysis(pool) -> str:
    aid = await pool.fetchval(
        "INSERT INTO analyses (filename_alias, text_sha256, rules_snapshot, rules_hash, matrix_version, "
        "prompt_version, domain_history_id) VALUES ('documento-1.txt', 'h', '{}'::jsonb, 'rh', 'mv', 'pv', 0) "
        "RETURNING id"
    )
    await pool.execute(
        "INSERT INTO analysis_trail (analysis_id, seq, step, matrix_version, prompt_version) "
        "VALUES ($1, 1, 'classify', 'mv', 'pv')",
        aid,
    )
    return str(aid)


# ---------------------------------------------------------------- idempotencia / banco existente


async def test_init_on_empty_database_creates_everything_and_is_idempotent(pool):
    await init_db(pool)
    await init_db(pool)
    assert ALL_TABLES <= await _tables(pool)
    assert await pool.fetchval("SELECT 1 FROM pg_roles WHERE rolname = 'leia_app' AND NOT rolcanlogin")


async def test_init_on_a_legacy_corpus_database_keeps_its_data_and_foreign_tables(pool):
    await pool.execute(LEGACY_CORPUS_DDL)
    doc = await pool.fetchval("INSERT INTO kb_docs (title) VALUES ('Lei 8.245') RETURNING id")
    await pool.execute("INSERT INTO kb_chunks (doc_id, content, sequence_order) VALUES ($1, 'Art. 4', 1)", doc)

    await init_db(pool)
    await init_db(pool)

    assert ALL_TABLES <= await _tables(pool)
    assert await pool.fetchval("SELECT count(*) FROM kb_chunks WHERE doc_id = $1", doc) == 1
    assert await pool.fetchval("SELECT email FROM directus_users WHERE id = 1") == "alguem@exemplo.invalid"
    # leia_app nao ganha nada sobre tabelas de terceiros.
    assert not await pool.fetchval("SELECT has_table_privilege('leia_app', 'directus_users', 'SELECT')")


async def test_reinit_keeps_domain_rows_and_their_history(dpool):
    await _seed_min(dpool)
    before = await dpool.fetchval("SELECT count(*) FROM domain_history")
    await init_db(dpool)
    assert await dpool.fetchval("SELECT count(*) FROM minuta_types") == 1
    assert await dpool.fetchval("SELECT count(*) FROM domain_history") == before


# ---------------------------------------------------------------- historico


async def test_insert_update_delete_on_every_domain_table_is_logged(dpool):
    await _seed_min(dpool)
    for t, col in [("minuta_types", "name"), ("themes", "description"), ("risk_matrix", "description"),
                   ("prompts", "prompt_text")]:
        await dpool.execute(f"UPDATE {t} SET {col} = 'novo'")
    await dpool.execute("DELETE FROM prompts")
    await dpool.execute("DELETE FROM risk_matrix")
    seen = {(r["table_name"], r["op"]) for r in await dpool.fetch("SELECT table_name, op FROM domain_history")}
    for t in DOMAIN_TABLES:
        assert {(t, "INSERT"), (t, "UPDATE")} <= seen, t
    assert {("prompts", "DELETE"), ("risk_matrix", "DELETE")} <= seen


async def test_update_keeps_old_and_new_row(dpool):
    await _seed_min(dpool)
    await dpool.execute("UPDATE risk_matrix SET criticality = 'vermelho'")
    h = await dpool.fetchrow(
        "SELECT old_row->>'criticality' AS o, new_row->>'criticality' AS n, db_user "
        "FROM domain_history WHERE table_name = 'risk_matrix' AND op = 'UPDATE'"
    )
    assert (h["o"], h["n"]) == ("amarelo", "vermelho")
    assert h["db_user"] == urlsplit(TEST_DATABASE_URL).username


async def test_noop_update_is_not_logged(dpool):
    await _seed_min(dpool)
    before = await dpool.fetchval("SELECT count(*) FROM domain_history")
    await dpool.execute("UPDATE risk_matrix SET description = description")
    assert await dpool.fetchval("SELECT count(*) FROM domain_history") == before


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE domain_history SET op = 'INSERT'",
        "DELETE FROM domain_history",
        "TRUNCATE domain_history",
        "UPDATE analysis_trail SET step = 'x'",
        "DELETE FROM analysis_trail",
        "TRUNCATE analysis_trail",
        "DELETE FROM analyses",
        "TRUNCATE analyses CASCADE",
        "UPDATE analyses SET rules_hash = 'outro'",
        "TRUNCATE prompts",
    ],
)
async def test_audit_tables_reject_changes_even_for_the_owner(dpool, sql):
    await _seed_min(dpool)
    await _insert_analysis(dpool)
    counts = [await dpool.fetchval(f"SELECT count(*) FROM {t}") for t in ("domain_history", "analysis_trail")]
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await dpool.execute(sql)
    assert [await dpool.fetchval(f"SELECT count(*) FROM {t}") for t in ("domain_history", "analysis_trail")] == counts
    assert await dpool.fetchval("SELECT rules_hash FROM analyses") == "rh"


async def test_analysis_result_columns_stay_writable(dpool):
    aid = await _insert_analysis(dpool)
    await dpool.execute(
        "UPDATE analyses SET status = 'done', report = $2::jsonb, finished_at = now() WHERE id = $1::uuid",
        aid,
        json.dumps({"content": {"alerts": []}}),
    )
    assert await dpool.fetchval("SELECT status FROM analyses") == "done"


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE analyses SET status = 'running', finished_at = NULL",
        "UPDATE analyses SET status = 'failed'",
        "UPDATE analyses SET report = '{}'::jsonb",
    ],
)
async def test_a_finished_analysis_is_frozen(dpool, sql):
    aid = await _insert_analysis(dpool)
    await dpool.execute("UPDATE analyses SET status = 'done', finished_at = now() WHERE id = $1::uuid", aid)
    with pytest.raises(asyncpg.InsufficientPrivilegeError, match="finished"):
        await dpool.execute(sql)
    assert await dpool.fetchval("SELECT status FROM analyses") == "done"


async def test_analysis_status_outside_the_lifecycle_is_rejected(dpool):
    await _insert_analysis(dpool)
    with pytest.raises(asyncpg.CheckViolationError):
        await dpool.execute("UPDATE analyses SET status = 'finished'")


async def test_init_adds_the_status_check_to_an_existing_database(dpool):
    await dpool.execute("ALTER TABLE analyses DROP CONSTRAINT analyses_status_check")  # banco anterior ao CHECK
    await _insert_analysis(dpool)
    await init_db(dpool)
    with pytest.raises(asyncpg.CheckViolationError):
        await dpool.execute("UPDATE analyses SET status = 'finished'")


async def test_init_normalizes_a_legacy_status_outside_the_lifecycle(dpool):
    """Banco anterior ao CHECK com status fora do ciclo: init normaliza e recria o CHECK, sem abortar."""
    await dpool.execute("ALTER TABLE analyses DROP CONSTRAINT analyses_status_check")  # banco anterior ao CHECK
    aid = await _insert_analysis(dpool)
    await dpool.execute("UPDATE analyses SET status = 'finished' WHERE id = $1::uuid", aid)  # so sem o CHECK
    await init_db(dpool)
    row = await dpool.fetchrow("SELECT status, report FROM analyses WHERE id = $1::uuid", aid)
    assert row["status"] == "failed"
    assert json.loads(row["report"])["status_original"] == "finished"
    fresh = await _insert_analysis(dpool)  # linha running: o gatilho deixa passar, o CHECK nao
    with pytest.raises(asyncpg.CheckViolationError):  # e o CHECK voltou a valer
        await dpool.execute("UPDATE analyses SET status = 'finished' WHERE id = $1::uuid", fresh)


# ---------------------------------------------------------------- papeis


async def test_app_role_edits_domain_but_cannot_touch_history_or_delete_analyses(dpool):
    await _seed_min(dpool)
    await _insert_analysis(dpool)
    async with dpool.acquire() as conn:
        await conn.execute("SET ROLE leia_app")
        try:
            for sql in [
                "DELETE FROM domain_history",
                "INSERT INTO domain_history (table_name, row_id, op) VALUES ('x', 1, 'INSERT')",
                "DELETE FROM analyses",
                "DELETE FROM analysis_trail",
            ]:
                with pytest.raises(asyncpg.InsufficientPrivilegeError):
                    await conn.execute(sql)
            # escreve no dominio e cria linhas novas (precisa das sequencias); o gatilho registra.
            await conn.execute("UPDATE risk_matrix SET description = 'pelo papel da aplicacao'")
            await conn.execute("INSERT INTO prompts (minuta_type_id, kind, prompt_text) SELECT id, 'k2', 'p' FROM minuta_types")
        finally:
            await conn.execute("RESET ROLE")
    assert await dpool.fetchval(
        "SELECT count(*) FROM domain_history WHERE new_row->>'description' = 'pelo papel da aplicacao'"
    ) == 1


@pytest.fixture
async def editor_dsn(dpool):
    """Um login pessoal (como os do admin na M3) que so tem o papel leia_app."""
    name, password = "leia_m1_editor_test", "editor-test-only"
    await dpool.execute(f"DROP ROLE IF EXISTS {name}")
    await dpool.execute(f"CREATE ROLE {name} LOGIN PASSWORD '{password}' IN ROLE leia_app")
    parts = urlsplit(TEST_DATABASE_URL)
    host = parts.netloc.rsplit("@", 1)[-1]
    try:
        yield urlunsplit((parts.scheme, f"{name}:{password}@{host}", parts.path, "", ""))
    finally:
        await dpool.execute(f"DROP ROLE IF EXISTS {name}")


async def test_third_write_of_the_same_row_is_in_history_with_the_writers_login(dpool, editor_dsn):
    await _seed_min(dpool)
    row_id = await dpool.fetchval("SELECT id FROM risk_matrix WHERE risk_id = 'R'")
    conn = await asyncpg.connect(editor_dsn)
    try:
        for desc in ("v1", "v2", "v3"):
            await conn.execute("UPDATE risk_matrix SET description = $1 WHERE id = $2", desc, row_id)
    finally:
        await conn.close()
    rows = await dpool.fetch(
        "SELECT old_row->>'description' AS o, new_row->>'description' AS n, db_user FROM domain_history "
        "WHERE table_name = 'risk_matrix' AND row_id = $1 AND op = 'UPDATE' ORDER BY id",
        row_id,
    )
    assert [(r["o"], r["n"]) for r in rows] == [("d", "v1"), ("v1", "v2"), ("v2", "v3")]
    assert {r["db_user"] for r in rows} == {"leia_m1_editor_test"}

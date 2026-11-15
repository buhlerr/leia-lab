"""Fixtures compartilhadas: um Postgres de teste limpo por teste.

O banco de teste e separado do banco de desenvolvimento para que rodar a suite
nunca apague o corpus que voce indexou a mao. Cada teste comeca com o schema
`public` recriado do zero, o que torna a ordem dos testes irrelevante.
"""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

import asyncpg
import pytest

from src.config import Settings
from tests._capture import capture  # noqa: F401  (fixture de captura de telemetria)
from tests._db_guard import SuiteSettings, UnsafeTestDatabaseError, assert_safe_test_database

_SUITE_SETTINGS = SuiteSettings()
TEST_DATABASE_URL = _SUITE_SETTINGS.TEST_DATABASE_URL


def _server_url(dsn: str, database: str) -> str:
    parts = urlsplit(dsn)
    return urlunsplit((parts.scheme, parts.netloc, f"/{database}", "", ""))


def require_safe_test_database(test_dsn: str | None = None, dev_dsn: str | None = None) -> None:
    """Aborta a sessao do pytest se o banco de teste nao for descartavel.

    Usa ``pytest.exit`` (e nao ``skip``/``fail``) para que nenhum teste seguinte
    chegue ao ``DROP SCHEMA public CASCADE`` do fixture ``pool``.
    """
    test_dsn = test_dsn if test_dsn is not None else TEST_DATABASE_URL
    dev_dsn = dev_dsn if dev_dsn is not None else _SUITE_SETTINGS.DATABASE_URL
    try:
        assert_safe_test_database(test_dsn, dev_dsn)
    except UnsafeTestDatabaseError as exc:
        pytest.exit(str(exc), returncode=pytest.ExitCode.USAGE_ERROR)


async def _ensure_test_database() -> None:
    """Cria o database de teste se ele ainda nao existir."""
    name = urlsplit(TEST_DATABASE_URL).path.lstrip("/")
    admin = await asyncpg.connect(_server_url(TEST_DATABASE_URL, "postgres"))
    try:
        exists = await admin.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", name)
        if not exists:
            await admin.execute(f'CREATE DATABASE "{name}"')
    finally:
        await admin.close()


@pytest.fixture
async def pool():
    """Pool para um banco de teste com o schema `public` vazio."""
    require_safe_test_database()
    await _ensure_test_database()
    created = await asyncpg.create_pool(dsn=TEST_DATABASE_URL, min_size=1, max_size=4)
    assert created is not None
    async with created as db_pool:
        await db_pool.execute("DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;")
        yield db_pool


@pytest.fixture
def settings() -> Settings:
    """Settings apontando para o banco de teste, sem chave de API (modo offline)."""
    return Settings(DATABASE_URL=TEST_DATABASE_URL, OPENROUTER_API_KEY="")


@pytest.fixture
async def fpool(pool):
    """``pool`` with the foundation schema applied (no seed)."""
    from src.foundation.db import init_foundation

    await init_foundation(pool)
    return pool

"""Fixtures compartilhadas: um Postgres de teste limpo por teste.

O banco de teste e separado do banco de desenvolvimento para que rodar a suite
nunca apague o corpus que voce indexou a mao. Cada teste comeca com o schema
`public` recriado do zero, o que torna a ordem dos testes irrelevante.
"""

from __future__ import annotations

import os
from urllib.parse import urlsplit, urlunsplit

import asyncpg
import pytest

from src.config import Settings

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://leia:leia_lab_2026@localhost:5433/leia_lab_test",
)


def _server_url(dsn: str, database: str) -> str:
    parts = urlsplit(dsn)
    return urlunsplit((parts.scheme, parts.netloc, f"/{database}", "", ""))


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

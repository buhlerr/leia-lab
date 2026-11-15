"""Apply the foundation DDL (after the corpus schema) and optionally seed defaults."""

from __future__ import annotations

from pathlib import Path

import asyncpg

from src.db.connection import init_db

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


async def init_foundation(pool: asyncpg.Pool) -> None:
    """Corpus schema + foundation schema. Idempotent."""
    await init_db(pool)
    await pool.execute(SCHEMA_PATH.read_text(encoding="utf-8"))

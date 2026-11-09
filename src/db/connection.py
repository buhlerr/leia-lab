"""asyncpg connection pool lifecycle management.

The pool is created lazily and cached at module level so that the FastAPI
lifespan handlers can share a single pool across requests.
"""

from __future__ import annotations

import logging
from pathlib import Path

import asyncpg

from src.config import Settings

logger = logging.getLogger(__name__)

POOL_MIN_SIZE = 2
POOL_MAX_SIZE = 10

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
CONFIG_SCHEMA_PATH = Path(__file__).with_name("schema_config.sql")

_pool: asyncpg.Pool | None = None


async def get_db_pool(settings: Settings | None = None) -> asyncpg.Pool:
    """Return the cached pool, creating it on first use."""
    global _pool
    if _pool is None:
        settings = settings or Settings()
        logger.info("Creating asyncpg pool (min_size=%s, max_size=%s)", POOL_MIN_SIZE, POOL_MAX_SIZE)
        _pool = await asyncpg.create_pool(
            dsn=settings.DATABASE_URL,
            min_size=POOL_MIN_SIZE,
            max_size=POOL_MAX_SIZE,
        )
    return _pool


async def close_db_pool() -> None:
    """Close and forget the cached pool. Safe to call when no pool exists."""
    global _pool
    if _pool is not None:
        logger.info("Closing asyncpg pool")
        await _pool.close()
        _pool = None


def is_pool_initialized() -> bool:
    """Whether a pool has already been created in this process."""
    return _pool is not None


def read_schema_sql() -> str:
    """Read the DDL script bundled with this package."""
    return SCHEMA_PATH.read_text(encoding="utf-8")


def read_config_schema_sql() -> str:
    """Read the config DDL script bundled with this package."""
    return CONFIG_SCHEMA_PATH.read_text(encoding="utf-8")


async def init_db(pool: asyncpg.Pool) -> None:
    """Apply ``schema.sql`` then ``schema_config.sql`` (idempotent DDL) to the database behind ``pool``."""
    await pool.execute(read_schema_sql())
    await pool.execute(read_config_schema_sql())
    logger.info("Database schema applied from %s and %s", SCHEMA_PATH, CONFIG_SCHEMA_PATH)

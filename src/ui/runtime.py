"""Helpers de conexao compartilhados pelas telas Streamlit."""

from __future__ import annotations

import asyncio

import asyncpg
import streamlit as st

from src.config import Settings
from src.db.connection import init_db


async def apply_schema(settings: Settings) -> None:
    """Aplica o schema em um pool proprio, fechado em seguida."""
    async with asyncpg.create_pool(
        dsn=settings.DATABASE_URL, min_size=1, max_size=2
    ) as pool:
        await init_db(pool)


@st.cache_resource(show_spinner=False)
def ensure_schema(dsn: str) -> bool:
    """Aplica o schema uma vez por processo; falhas nao ficam no cache."""
    asyncio.run(apply_schema(Settings(DATABASE_URL=dsn)))
    return True


async def with_pool(settings: Settings, work):
    """Executa ``work`` com um pool curto, como o resto da UI."""
    async with asyncpg.create_pool(
        dsn=settings.DATABASE_URL, min_size=1, max_size=4
    ) as pool:
        return await work(pool)

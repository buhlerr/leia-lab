"""Entrypoint de debug para GraphLoupe e depuradores visuais de LangGraph.

Este módulo expõe funções sem argumentos obrigatórios que retornam instâncias
compiladas com ``InMemorySaver`` (checkpointer necessário para step debugging,
inspeção de checkpoints e time-travel no GraphLoupe).

O pool Postgres é criado de forma lazy durante a execução dos nós, para que o
AST scanner e a importação do módulo ocorram instantaneamente sem conexões de rede
ou dependência de event loop ativo.

Entrypoint no GraphLoupe:
``src.graphs.debug:build_graph`` ou ``src.graphs.debug:graph``

O input precisa de ``text`` ja mascarado e de um ``analysis_id`` (uuid novo). Rodando o grafo
direto, ninguem termina a linha de ``analyses`` se a execucao parar no meio: so ``analyze()`` faz isso.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import asyncpg
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from src.config import Settings
from src.graphs.analyze_minuta_graph import (
    AnalyzeMinutaState,
    build_analyze_minuta_graph,
    route_after_classificar,
)

_saver = InMemorySaver()
_cached_pool: asyncpg.Pool | None = None
_pool_lock = asyncio.Lock() if hasattr(asyncio, "Lock") else None


class LazyAsyncpgPoolProxy:
    """Proxy lazy para asyncpg.Pool que inicializa a conexão na primeira chamada assíncrona."""

    def __init__(self, dsn: str | None = None) -> None:
        self.dsn = dsn

    async def _get_real_pool(self) -> asyncpg.Pool:
        global _cached_pool
        if _cached_pool is not None and not _cached_pool._closed:
            return _cached_pool
        settings = Settings()
        dsn = self.dsn or os.environ.get("DATABASE_URL") or os.environ.get("TEST_DATABASE_URL")
        if not dsn or "localhost:5433" in dsn:
            pw = os.environ.get("LEIA_HOMELAB_PG_PASSWORD")
            if pw:
                dsn = f"postgresql://leia:{pw}@192.168.0.120:5432/leia_lab"
            else:
                dsn = settings.DATABASE_URL
        _cached_pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
        return _cached_pool

    async def execute(self, *args: Any, **kwargs: Any) -> Any:
        pool = await self._get_real_pool()
        return await pool.execute(*args, **kwargs)

    async def fetch(self, *args: Any, **kwargs: Any) -> Any:
        pool = await self._get_real_pool()
        return await pool.fetch(*args, **kwargs)

    async def fetchrow(self, *args: Any, **kwargs: Any) -> Any:
        pool = await self._get_real_pool()
        return await pool.fetchrow(*args, **kwargs)

    async def fetchval(self, *args: Any, **kwargs: Any) -> Any:
        pool = await self._get_real_pool()
        return await pool.fetchval(*args, **kwargs)

    def acquire(self, *args: Any, **kwargs: Any) -> Any:
        outer = self

        class _AcquireContext:
            async def __aenter__(self) -> Any:
                pool = await outer._get_real_pool()
                self._conn_ctx = pool.acquire(*args, **kwargs)
                return await self._conn_ctx.__aenter__()

            async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> Any:
                return await self._conn_ctx.__aexit__(exc_type, exc_val, exc_tb)

        return _AcquireContext()


def build_graph(checkpointer: Any = None) -> Any:
    """Factory sem argumentos obrigatórios compatível com o AST scanner do GraphLoupe."""
    pool_proxy = LazyAsyncpgPoolProxy()
    settings = Settings()
    saver = checkpointer or _saver
    return build_analyze_minuta_graph(pool_proxy, settings, checkpointer=saver).compiled  # type: ignore[arg-type]


def build_app(checkpointer: Any = None) -> Any:
    """Alias comum detectado automaticamente pelo GraphLoupe."""
    return build_graph(checkpointer=checkpointer)


graph = build_graph()

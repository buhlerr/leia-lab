"""Repositorio de leitura da configuracao de minutas: tipos e seus relatorios.

Sem cache de proposito: a configuracao e lida do banco a cada chamada, para que
um UPDATE no prompt valha imediatamente na execucao seguinte.
"""

from __future__ import annotations

from dataclasses import dataclass

import asyncpg

LIST_MINUTA_TYPES_SQL = """
SELECT id::text AS id, name
FROM minuta_types
ORDER BY name
"""

GET_MINUTA_TYPE_SQL = """
SELECT id::text AS id, name
FROM minuta_types
WHERE id = $1::uuid
"""

LIST_REPORTS_SQL = """
SELECT
    id::text AS id,
    minuta_type_id::text AS minuta_type_id,
    name,
    kind,
    prompt,
    model,
    execution_order
FROM minuta_reports
WHERE minuta_type_id = $1::uuid
ORDER BY execution_order
"""


@dataclass(frozen=True)
class MinutaType:
    id: str
    name: str


@dataclass(frozen=True)
class MinutaReport:
    id: str
    minuta_type_id: str
    name: str
    kind: str
    prompt: str
    model: str | None
    execution_order: int


async def list_minuta_types(pool: asyncpg.Pool) -> list[MinutaType]:
    """Todos os tipos de minuta, em ordem de nome."""
    rows = await pool.fetch(LIST_MINUTA_TYPES_SQL)
    return [MinutaType(id=row["id"], name=row["name"]) for row in rows]


async def get_minuta_type(pool: asyncpg.Pool, minuta_type_id: str) -> MinutaType | None:
    """Tipo de minuta pelo id, ou ``None`` quando ele nao existe."""
    row = await pool.fetchrow(GET_MINUTA_TYPE_SQL, str(minuta_type_id))
    if row is None:
        return None
    return MinutaType(id=row["id"], name=row["name"])


async def list_reports(pool: asyncpg.Pool, minuta_type_id: str) -> list[MinutaReport]:
    """Relatorios do tipo de minuta pedido, em ordem de execucao."""
    rows = await pool.fetch(LIST_REPORTS_SQL, str(minuta_type_id))
    return [
        MinutaReport(
            id=row["id"],
            minuta_type_id=row["minuta_type_id"],
            name=row["name"],
            kind=row["kind"],
            prompt=row["prompt"],
            model=row["model"],
            execution_order=row["execution_order"],
        )
        for row in rows
    ]

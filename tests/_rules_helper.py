"""Helper de teste: troca temas e riscos do tipo padrao (as regras agora vivem no banco)."""

from __future__ import annotations

import json
from typing import Any

from src.db.connection import init_db
from src.db.defaults import LOCACAO_RESIDENCIAL
from src.db.seed import seed_defaults


async def use_rules(
    pool,
    riscos: dict[str, list[dict[str, Any]]],
    temas: list[str],
    tema_map: dict[str, list[str]] | None = None,
) -> None:
    """``init_db`` + seed, depois substitui temas/riscos de ``locacao_residencial`` pelos dados."""
    await init_db(pool)
    await seed_defaults(pool)
    async with pool.acquire() as conn, conn.transaction():
        tid = await conn.fetchval("SELECT id FROM minuta_types WHERE slug = $1", LOCACAO_RESIDENCIAL)
        await conn.execute("DELETE FROM risk_matrix")
        await conn.execute("DELETE FROM themes")
        ids = {}
        for pos, t in enumerate(temas):
            ids[t] = await conn.fetchval(
                "INSERT INTO themes (minuta_type_id, slug, norm_ids, position) VALUES ($1, $2, $3, $4) RETURNING id",
                tid,
                t,
                (tema_map or {}).get(t, []),
                pos,
            )
        for t, lista in riscos.items():
            for x in lista:
                await conn.execute(
                    "INSERT INTO risk_matrix (theme_id, risk_id, description, criticality, party, norms) "
                    "VALUES ($1, $2, $3, $4, $5, $6::jsonb)",
                    ids[t],
                    x["id"],
                    x["risco"],
                    x["cor"],
                    x["parte"],
                    json.dumps(x.get("normas", [])),
                )

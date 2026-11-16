"""Migracao de dados idempotente: o tipo ``locacao_residencial`` a partir dos ``DEFAULT_*`` do master.

Roda depois de ``init_db``. Se o tipo ja existe, nao faz nada: o que alguem editou no banco
(pelo admin ou por SQL) nunca e sobrescrito pelo seed.
"""

from __future__ import annotations

import json

import asyncpg

from src.db.defaults import (
    DEFAULT_PROMPTS,
    LOCACAO_CLASSIFIER,
    LOCACAO_NAME,
    LOCACAO_RESIDENCIAL,
)
from src.graphs.minuta_rules import DEFAULT_RISCOS, DEFAULT_TEMA_MAP, DEFAULT_TEMAS


async def seed_defaults(pool: asyncpg.Pool) -> bool:
    """Cria tipo, temas, riscos e prompts padrao numa transacao. ``False`` se o tipo ja existia."""
    async with pool.acquire() as conn, conn.transaction():
        if await conn.fetchval("SELECT 1 FROM minuta_types WHERE slug = $1", LOCACAO_RESIDENCIAL):
            return False
        type_id = await conn.fetchval(
            "INSERT INTO minuta_types (slug, name, classifier_description) VALUES ($1, $2, $3) RETURNING id",
            LOCACAO_RESIDENCIAL,
            LOCACAO_NAME,
            LOCACAO_CLASSIFIER,
        )
        theme_ids: dict[str, int] = {}
        for position, tema in enumerate(DEFAULT_TEMAS):
            theme_ids[tema] = await conn.fetchval(
                "INSERT INTO themes (minuta_type_id, slug, norm_ids, position) VALUES ($1, $2, $3, $4) RETURNING id",
                type_id,
                tema,
                DEFAULT_TEMA_MAP.get(tema, []),
                position,
            )
        for tema, riscos in DEFAULT_RISCOS.items():
            for r in riscos:
                await conn.execute(
                    "INSERT INTO risk_matrix (theme_id, risk_id, description, criticality, party, norms) "
                    "VALUES ($1, $2, $3, $4, $5, $6::jsonb)",
                    theme_ids[tema],
                    r["id"],
                    r["risco"],
                    r["cor"],
                    r["parte"],
                    json.dumps(r.get("normas", [])),
                )
        for kind, text in DEFAULT_PROMPTS.items():
            await conn.execute(
                "INSERT INTO prompts (minuta_type_id, kind, prompt_text) VALUES ($1, $2, $3)", type_id, kind, text
            )
    return True

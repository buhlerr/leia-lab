"""Test helper: replace the seeded locacao rules with custom ones (rules now live in the DB)."""

from __future__ import annotations

from typing import Any

from src.foundation.seed import LOCACAO, add_risks, normalize_norm, seed_defaults


async def use_rules(pool, riscos: dict[str, list[dict[str, Any]]], temas: list[str], tema_map: dict[str, list[str]]) -> None:
    await seed_defaults(pool)
    await pool.execute("DELETE FROM risk_matrix")
    await pool.execute("DELETE FROM themes")
    async with pool.acquire() as conn:
        tid = await conn.fetchval("SELECT id FROM minuta_types WHERE slug = $1", LOCACAO)
        for pos, t in enumerate(temas):
            await conn.execute(
                "INSERT INTO themes (minuta_type_id, slug, norm_ids, position) VALUES ($1,$2,$3,$4)",
                tid, t, tema_map.get(t, []), pos,
            )
        rows = [
            {
                "theme": t, "risk_id": x["id"], "description": x["risco"], "criticality": x["cor"], "party": x["parte"],
                "norms": [normalize_norm(n, risk_id=x["id"]) for n in x.get("normas", [])],
            }
            for t, lista in riscos.items() for x in lista
        ]
        await add_risks(conn, tid, rows, tema_map)

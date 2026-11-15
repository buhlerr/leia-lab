"""Seed and load the domain tables.

Two sources:
* ``seed_defaults`` - master's ``DEFAULT_TEMAS`` / ``DEFAULT_RISCOS`` / ``DEFAULT_TEMA_MAP`` and the
  graph prompt constants (``defaults.py``), for the ``locacao_residencial`` type.
* ``load_matrix_jsonl`` - the real matrix (``levantamento/matriz-riscos.jsonl``).

Bead leia-lab-vz3: the real matrix stores norms as ``{norma, artigo, status, por_que}`` while master's
``load_risk_matrix`` only understands ``{citacao, id}`` and silently drops the rest (so every red risk
is downgraded to yellow). ``normalize_norm`` maps ``norma``/``artigo`` to ``citacao`` explicitly, keeps
the extra fields, and RAISES on a norm it cannot map instead of dropping it.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any

import asyncpg

from src.foundation.defaults import DEFAULT_PROMPTS, LOCACAO_CLASSIFIER
from src.graphs.minuta_rules import DEFAULT_RISCOS, DEFAULT_TEMA_MAP, DEFAULT_TEMAS

LOCACAO = "locacao_residencial"


def _slug(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def normalize_norm(n: dict[str, Any], *, risk_id: str = "?") -> dict[str, Any]:
    """One norm in the matrix -> ``{"id", "citacao", ...extra}``. Raises if it cannot be mapped."""
    if not isinstance(n, dict):
        raise ValueError(f"risk {risk_id}: norm is not an object")
    if n.get("citacao"):
        citacao = n["citacao"]
    elif n.get("norma"):
        artigo = str(n.get("artigo") or "").strip()
        citacao = f"{n['norma']}, art. {artigo}" if artigo else str(n["norma"])
    else:
        raise ValueError(f"risk {risk_id}: norm has neither 'citacao' nor 'norma' (keys={sorted(n)})")
    out = {k: v for k, v in n.items() if k not in {"id", "citacao"}}
    out["id"] = n.get("id") or _slug(citacao)
    out["citacao"] = citacao
    return out


def rows_from_matrix_jsonl(path: Path) -> list[dict[str, Any]]:
    """Parse the real matrix into ``risk_matrix``-shaped dicts (normalising norms)."""
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        rows.append(
            {
                "theme": r["tema"],
                "risk_id": r["id"],
                "description": r["risco"],
                "criticality": r["criticidade_sugerida"],
                "party": r["parte_prejudicada"],
                "norms": [normalize_norm(n, risk_id=r["id"]) for n in r.get("normas", [])],
            }
        )
    return rows


async def ensure_type(conn: asyncpg.Connection, slug: str, name: str, classifier: str) -> int:
    row = await conn.fetchrow("SELECT id FROM minuta_types WHERE slug = $1", slug)
    if row:
        return row["id"]
    return await conn.fetchval(
        "INSERT INTO minuta_types (slug, name, classifier_description) VALUES ($1, $2, $3) RETURNING id",
        slug,
        name,
        classifier,
    )


async def add_risks(
    conn: asyncpg.Connection,
    type_id: int,
    rows: list[dict[str, Any]],
    tema_map: dict[str, list[str]] | None = None,
) -> None:
    """Insert risks (creating missing themes). ``tema_map`` gives each theme's always-fetched norm ids."""
    themes: dict[str, int] = {}
    for pos, r in enumerate(rows):
        slug = r["theme"]
        if slug not in themes:
            themes[slug] = await conn.fetchval(
                "INSERT INTO themes (minuta_type_id, slug, norm_ids, position) VALUES ($1, $2, $3, $4) "
                "ON CONFLICT (minuta_type_id, slug) DO UPDATE SET slug = EXCLUDED.slug RETURNING id",
                type_id,
                slug,
                (tema_map or {}).get(slug, []),
                pos,
            )
        await conn.execute(
            "INSERT INTO risk_matrix (theme_id, risk_id, description, criticality, party, norms) "
            "VALUES ($1, $2, $3, $4, $5, $6::jsonb)",
            themes[slug],
            r["risk_id"],
            r["description"],
            r["criticality"],
            r["party"],
            json.dumps(r["norms"]),
        )


async def seed_defaults(pool: asyncpg.Pool) -> bool:
    """Seed ``locacao_residencial`` from master's constants. No-op (False) if the type exists."""
    async with pool.acquire() as conn, conn.transaction():
        if await conn.fetchval("SELECT 1 FROM minuta_types WHERE slug = $1", LOCACAO):
            return False
        tid = await ensure_type(conn, LOCACAO, "Locacao residencial", LOCACAO_CLASSIFIER)
        for pos, tema in enumerate(DEFAULT_TEMAS):  # themes without risks must exist too
            await conn.execute(
                "INSERT INTO themes (minuta_type_id, slug, norm_ids, position) VALUES ($1, $2, $3, $4)",
                tid,
                tema,
                DEFAULT_TEMA_MAP.get(tema, []),
                pos,
            )
        rows = [
            {
                "theme": tema,
                "risk_id": x["id"],
                "description": x["risco"],
                "criticality": x["cor"],
                "party": x["parte"],
                "norms": [normalize_norm(n, risk_id=x["id"]) for n in x.get("normas", [])],
            }
            for tema, lista in DEFAULT_RISCOS.items()
            for x in lista
        ]
        await add_risks(conn, tid, rows, DEFAULT_TEMA_MAP)
        for kind, text in DEFAULT_PROMPTS.items():
            await conn.execute(
                "INSERT INTO prompts (minuta_type_id, kind, prompt_text) VALUES ($1, $2, $3)", tid, kind, text
            )
    return True


async def load_matrix_jsonl(pool: asyncpg.Pool, slug: str, path: Path, *, name: str | None = None) -> int:
    """Load the real matrix as a (new) minuta type, with default prompts. Returns the risk count."""
    rows = rows_from_matrix_jsonl(path)
    async with pool.acquire() as conn, conn.transaction():
        tid = await ensure_type(conn, slug, name or slug, LOCACAO_CLASSIFIER)
        await add_risks(conn, tid, rows)
        for kind, text in DEFAULT_PROMPTS.items():
            await conn.execute(
                "INSERT INTO prompts (minuta_type_id, kind, prompt_text) VALUES ($1, $2, $3)", tid, kind, text
            )
    return len(rows)

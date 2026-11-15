"""Read the domain tables into one immutable, hashed rules snapshot.

The snapshot is read in a single REPEATABLE READ transaction, so it is internally consistent. It is
what the graph runs on (``state["rules"]``) AND what is stored with the analysis: the analysis is
self-contained even after the matrix changes.

Versions are content hashes (``matrix_version`` = themes + risks, ``prompt_version`` = prompts +
classifier descriptions), so they change on ANY write, including a direct psql one. ``history_id`` is
the ``domain_history`` watermark at read time: rows after it are changes made after the analysis.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

import asyncpg

SCHEMA_VERSION = 1


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _sha(obj: Any) -> str:
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RulesSnapshot:
    content: dict[str, Any]
    hash: str
    matrix_version: str
    prompt_version: str
    history_id: int


def verify_snapshot(content: dict[str, Any], expected_hash: str) -> bool:
    return _sha(content) == expected_hash


def _decode(v: Any) -> Any:
    return json.loads(v) if isinstance(v, str) else v


async def load_rules_snapshot(pool: asyncpg.Pool) -> RulesSnapshot:
    async with pool.acquire() as conn, conn.transaction(isolation="repeatable_read", readonly=True):
        history_id = await conn.fetchval("SELECT coalesce(max(id), 0) FROM domain_history")
        types = await conn.fetch("SELECT id, slug, name, classifier_description FROM minuta_types WHERE active ORDER BY id")
        themes = await conn.fetch("SELECT id, minuta_type_id, slug, description, norm_ids FROM themes ORDER BY position, id")
        risks = await conn.fetch(
            "SELECT theme_id, risk_id, description, criticality, party, norms FROM risk_matrix WHERE active ORDER BY id"
        )
        prompts = await conn.fetch(
            "SELECT minuta_type_id, kind, prompt_text, model FROM prompts WHERE active ORDER BY position, id"
        )
    out: dict[str, Any] = {}
    theme_slug = {t["id"]: t["slug"] for t in themes}
    for ty in types:
        mine = [t for t in themes if t["minuta_type_id"] == ty["id"]]
        riscos: dict[str, list[dict[str, Any]]] = {}
        for r in risks:
            if r["theme_id"] in {t["id"] for t in mine}:
                riscos.setdefault(theme_slug[r["theme_id"]], []).append(
                    {
                        "id": r["risk_id"],
                        "risco": r["description"],
                        "cor": r["criticality"],
                        "parte": r["party"],
                        "normas": _decode(r["norms"]),
                    }
                )
        pr: dict[str, dict[str, Any]] = {}
        for p in prompts:
            if p["minuta_type_id"] == ty["id"]:
                pr.setdefault(p["kind"], {"text": p["prompt_text"], "model": p["model"]})  # lowest position wins
        out[ty["slug"]] = {
            "name": ty["name"],
            "classifier": ty["classifier_description"],
            "temas": [t["slug"] for t in mine],
            "tema_desc": {t["slug"]: t["description"] for t in mine if t["description"]},
            "tema_map": {t["slug"]: list(t["norm_ids"]) for t in mine},
            "riscos": riscos,
            "prompts": pr,
        }
    content = {"schema": SCHEMA_VERSION, "history_id": history_id, "types": out}
    matrix_version = _sha({s: {k: t[k] for k in ("temas", "tema_desc", "tema_map", "riscos")} for s, t in out.items()})[:12]
    prompt_version = _sha({s: {k: t[k] for k in ("classifier", "prompts")} for s, t in out.items()})[:12]
    return RulesSnapshot(content, _sha(content), matrix_version, prompt_version, history_id)

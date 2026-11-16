"""Registro de uma analise com a foto congelada das regras (a trilha por passo entra na M2b)."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

import asyncpg

from src.db.rules import RulesSnapshot, canonical_json


async def start_analysis(
    pool: asyncpg.Pool,
    snap: RulesSnapshot,
    *,
    filename_alias: str,
    masked_text: str,
    params: dict[str, Any],
) -> uuid.UUID:
    """Insere a analise com o snapshot. So o texto MASCARADO e hasheado; nada cru chega aqui."""
    return await pool.fetchval(
        "INSERT INTO analyses (filename_alias, text_sha256, params, rules_snapshot, rules_hash, "
        "matrix_version, prompt_version, domain_history_id) "
        "VALUES ($1, $2, $3::jsonb, $4::jsonb, $5, $6, $7, $8) RETURNING id",
        filename_alias,
        hashlib.sha256(masked_text.encode("utf-8")).hexdigest(),
        json.dumps(params),
        canonical_json(snap.content),
        snap.hash,
        snap.matrix_version,
        snap.prompt_version,
        snap.history_id,
    )


async def finish_analysis(
    pool: asyncpg.Pool,
    analysis_id: uuid.UUID,
    *,
    status: str,
    minuta_type: str | None,
    report: dict[str, Any] | None,
) -> None:
    await pool.execute(
        "UPDATE analyses SET status = $2, minuta_type = $3, report = $4::jsonb, finished_at = now() WHERE id = $1",
        analysis_id,
        status,
        minuta_type,
        json.dumps(report, ensure_ascii=False, default=str) if report is not None else None,
    )

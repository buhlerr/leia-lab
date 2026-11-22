"""Registro de uma analise: a foto congelada das regras e a trilha append-only de cada passo."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

import asyncpg

from src.db.rules import RulesSnapshot, canonical_json
from src.ingest.masking import MaskedText, requires_masked


@requires_masked("filename_alias", "masked_text")
async def start_analysis(
    pool: asyncpg.Pool,
    snap: RulesSnapshot,
    *,
    filename_alias: MaskedText,
    masked_text: MaskedText,
    params: dict[str, Any],
) -> uuid.UUID:
    """Insere a analise com o snapshot. So o texto MASCARADO e hasheado; str comum e recusada."""
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


async def append_trail(
    pool: asyncpg.Pool, analysis_id: uuid.UUID | str, snap_meta: dict[str, Any], steps: list[dict[str, Any]]
) -> None:
    """Acrescenta passos em ordem (``seq`` continuo por analise).

    Cada passo: ``step`` e, opcionais, ``clause_n``, ``input_summary`` (so dado MASCARADO),
    ``decision``, ``score``, ``cutoff`` e ``cited_norms``. ``snap_meta`` traz as versoes da foto.
    """
    if not steps:
        return
    async with pool.acquire() as conn, conn.transaction():
        seq = await conn.fetchval(
            "SELECT coalesce(max(seq), 0) FROM analysis_trail WHERE analysis_id = $1", analysis_id
        )
        for i, s in enumerate(steps, start=seq + 1):
            await conn.execute(
                "INSERT INTO analysis_trail (analysis_id, seq, step, clause_n, input_summary, decision, score, "
                "cutoff, matrix_version, prompt_version, cited_norms) "
                "VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb, $7, $8, $9, $10, $11)",
                analysis_id,
                i,
                s["step"],
                s.get("clause_n"),
                json.dumps(s.get("input_summary", {}), ensure_ascii=False),
                json.dumps(s.get("decision", {}), ensure_ascii=False, default=str),
                s.get("score"),
                s.get("cutoff"),
                snap_meta["matrix_version"],
                snap_meta["prompt_version"],
                list(s.get("cited_norms", [])),
            )

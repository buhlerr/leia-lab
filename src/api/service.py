"""Nucleo puro da API: extrai o texto, roda a analise e devolve o contrato.

Sem nenhum import do FastAPI: o mesmo nucleo serve ao shell HTTP
(``src.api.app``) e aos testes. O fluxo e sempre ``extracao -> analyze``,
e o mascaramento acontece DENTRO de ``analyze`` (``prepare_input``), antes de
o grafo ou qualquer chamada externa ver o texto. O nome real do arquivo nunca
sai daqui: vira o apelido ``documento-<sha8>.<ext>`` no ``prepare_input``.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from typing import Any

import asyncpg

from src.graphs.analyze_minuta_graph import analyze
from src.ingest.extract import (
    MAX_UPLOAD_BYTES,
    DocumentTooLargeError,
    EmptyDocumentError,
    InvalidDocumentError,
    UnsupportedFileError,
)
from src.ingest.isolated import extract_text_isolated

# Extensoes que podem ser patologicas: extracao em processo separado.
_ISOLATED_EXTENSIONS = frozenset({".pdf", ".docx"})


def _decode(value: Any) -> Any:
    """asyncpg devolve JSONB como ``str``; o contrato quer objetos."""
    return json.loads(value) if isinstance(value, str) else value


async def _extract_text(filename: str, data: bytes) -> str:
    """Texto do upload conforme a extensao; erros sao sempre ``DocumentError``.

    O teto de bytes vale antes de qualquer biblioteca abrir o arquivo.
    """
    if len(data) > MAX_UPLOAD_BYTES:
        raise DocumentTooLargeError("The file is larger than the upload limit")
    extension = os.path.splitext(filename)[1].lower()
    if extension in _ISOLATED_EXTENSIONS:
        return await asyncio.to_thread(extract_text_isolated, filename, data)
    if extension == ".txt":
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise InvalidDocumentError("The file is not valid UTF-8") from exc
    raise UnsupportedFileError("Unsupported file extension")


async def evaluate_upload(
    pool: asyncpg.Pool, graph: Any, *, filename: str, data: bytes
) -> dict[str, Any]:
    """Avalia um contrato enviado como bytes e devolve o resultado com a trilha.

    POST e GET devolvem o mesmo contrato: aqui a analise roda e o resultado e
    re-lido do banco (``load_analysis``), exatamente como o GET fara depois.
    """
    text = await _extract_text(filename, data)
    if not text.strip():
        raise EmptyDocumentError("The document has no text")
    state = await analyze(graph, raw_text=text, filename=filename)
    result = await load_analysis(pool, state["analysis_id"])
    if result is None:  # o proprio grafo acabou de gravar a analise
        raise RuntimeError("analysis row not found after a completed run")  # pragma: no cover
    return result


async def load_analysis(pool: asyncpg.Pool, analysis_id: uuid.UUID | str) -> dict[str, Any] | None:
    """Linha de ``analyses`` + trilha ordenada de ``analysis_trail``, ou ``None``."""
    row = await pool.fetchrow(
        "SELECT id, status, filename_alias, minuta_type, matrix_version, prompt_version, "
        "rules_hash, report FROM analyses WHERE id = $1::uuid",
        analysis_id,
    )
    if row is None:
        return None
    trail = await pool.fetch(
        "SELECT seq, step, clause_n, input_summary, decision, score, cutoff, cited_norms, recorded_at "
        "FROM analysis_trail WHERE analysis_id = $1::uuid ORDER BY seq",
        analysis_id,
    )
    steps = [
        {
            "seq": t["seq"],
            "step": t["step"],
            "clause_n": t["clause_n"],
            "input_summary": _decode(t["input_summary"]),
            "decision": _decode(t["decision"]),
            "score": t["score"],
            "cutoff": t["cutoff"],
            "cited_norms": list(t["cited_norms"]),
            "recorded_at": t["recorded_at"],
        }
        for t in trail
    ]
    return {
        "analysis_id": row["id"],
        "status": row["status"],
        "filename_alias": row["filename_alias"],
        "minuta_type": row["minuta_type"],
        "matrix_version": row["matrix_version"],
        "prompt_version": row["prompt_version"],
        "rules_hash": row["rules_hash"],
        "report": _decode(row["report"]),
        "trail": steps,
    }

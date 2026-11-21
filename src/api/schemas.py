"""Contrato de resposta da API: o OpenAPI (/docs) e gerado destes modelos.

Tudo que aparece aqui ja passou pelo mascaramento: ``filename_alias`` e o
apelido publico do documento e a trilha so traz resumos de texto MASCARADO.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class TrailStep(BaseModel):
    """Um passo da trilha de auditoria, na ordem em que rodou (``seq``)."""

    seq: int
    step: str
    clause_n: int | None = None
    input_summary: dict[str, Any] = {}
    decision: dict[str, Any] = {}
    score: float | None = None
    cutoff: float | None = None
    cited_norms: list[str] = []
    recorded_at: datetime


class AnalysisResult(BaseModel):
    """Resultado de uma analise: envelope do report e trilha completa.

    ``report`` fica ``None`` so numa analise ainda em execucao; o POST, que
    espera a execucao terminar, devolve sempre o envelope pronto.
    """

    analysis_id: uuid.UUID
    status: str
    filename_alias: str
    minuta_type: str | None = None
    matrix_version: str
    prompt_version: str
    rules_hash: str
    report: dict[str, Any] | None = None
    trail: list[TrailStep]

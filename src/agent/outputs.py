"""Saidas estruturadas do agente de analise de minutas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class ChecklistItem(BaseModel):
    item: str
    status: Literal["presente", "ausente", "divergente"]
    evidence: str


class ChecklistOutput(BaseModel):
    items: list[ChecklistItem]


class ReportResult(BaseModel):
    name: str
    kind: str
    execution_order: int
    status: Literal["ok", "failed"]
    text: str | None = None
    checklist: ChecklistOutput | None = None
    model: str
    error: str | None = None
    input_tokens: int = 0
    cache_read_tokens: int = 0


class AnalysisResult(BaseModel):
    minuta_type_id: str
    minuta_type_name: str
    reports: list[ReportResult]

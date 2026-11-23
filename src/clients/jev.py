"""Cliente assincrono do TypeSafe Jev (``/v1/systemone``) com fallback offline."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

from src.config import Settings
from src.ingest.masking import requires_masked
from src.tracing import client_span, tag_span

_RETRY_STATUS = {429, 529}
_MAX_ATTEMPTS = 4


def _offline_answer(q: dict[str, Any], state_text: str) -> dict[str, Any]:
    criteria = q.get("criteria") or {}
    if q.get("type") == "noul":
        return {"noul": 0.75}
    if "locacao_residencial" in criteria and any(
        t in state_text for t in ("locacao", "locação", "aluguel")
    ):
        return {
            "choice": "locacao_residencial",
            "confidence": 0.95,
            "probabilities": {"locacao_residencial": 0.95},
        }
    if "nao_suportado" in criteria:
        choice = "nao_suportado"
    elif "c0" in criteria:
        choice = "c0"
    else:
        choice = next(iter(criteria), "")
    return {"choice": choice, "confidence": 0.95, "probabilities": {choice: 0.95}}


@requires_masked("state", "questions")
@client_span("call_jev", allowed=("state", "questions"))
async def call_jev(
    state: dict[str, Any],
    questions: dict[str, Any],
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Faz as ``questions`` ao Jev sobre ``state``; offline sem ``TYPESAFE_API_KEY``."""
    settings = settings or Settings()
    tag_span(model=settings.JEV_MODEL, offline=not settings.TYPESAFE_API_KEY)

    if not settings.TYPESAFE_API_KEY:
        state_text = json.dumps(state, ensure_ascii=False).lower()
        return {
            "answers": {name: _offline_answer(q, state_text) for name, q in questions.items()},
            "usage": {"input_tokens": 0},
        }

    payload = {"model": settings.JEV_MODEL, "state": state, "questions": questions}
    headers = {"Authorization": f"Bearer {settings.TYPESAFE_API_KEY}"}
    async with httpx.AsyncClient(timeout=40.0) as client:
        for attempt in range(_MAX_ATTEMPTS):
            resp = await client.post(settings.TYPESAFE_BASE_URL, json=payload, headers=headers)
            if resp.status_code in _RETRY_STATUS and attempt < _MAX_ATTEMPTS - 1:
                await asyncio.sleep(0.05 * (attempt + 1))
                continue
            # raise_for_status so cita status e URL, nunca o corpo/estado (texto da minuta).
            resp.raise_for_status()
            data = resp.json()
            data.setdefault("usage", {"input_tokens": 0})
            return data
    raise RuntimeError("unreachable")  # pragma: no cover

"""Cliente assincrono do TypeSafe Jev (``/v1/systemone``) com fallback offline."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
from opentelemetry import trace

from src.config import Settings

tracer = trace.get_tracer("src.clients")
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


async def call_jev(
    state: dict[str, Any],
    questions: dict[str, Any],
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Faz as ``questions`` ao Jev sobre ``state``; offline sem ``TYPESAFE_API_KEY``."""
    settings = settings or Settings()
    offline = not settings.TYPESAFE_API_KEY

    # Span manual: os clientes sao httpx cru, sem instrumentacao automatica.
    # Conteudo do estado = texto JA MASCARADO (o grafo nunca ve texto cru).
    with tracer.start_as_current_span("call_jev") as span:
        span.set_attribute("openinference.span.kind", "LLM")
        span.set_attribute("llm.model_name", "offline-stub" if offline else settings.JEV_MODEL)
        span.set_attribute("leia.offline", offline)
        span.set_attribute(
            "input.value", json.dumps({"state": state, "questions": questions}, ensure_ascii=False)
        )
        result = await _call_jev_raw(state, questions, settings)
        span.set_attribute("output.value", json.dumps(result, ensure_ascii=False))
        return result


async def _call_jev_raw(
    state: dict[str, Any],
    questions: dict[str, Any],
    settings: Settings,
) -> dict[str, Any]:
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

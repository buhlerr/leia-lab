"""Cliente assincrono de chat completion (OpenRouter/OpenAI) com fallback offline."""

from __future__ import annotations

import json
import re

import httpx
from opentelemetry import trace

from src.config import Settings

tracer = trace.get_tracer("src.clients")

_RISK_LINE = re.compile(r"^\s*-\s*([^\s:]+)\s*:\s*(.+?)\s*$", re.MULTILINE)
_CLAUSE = re.compile(r"<clausula>(.*?)</clausula>", re.DOTALL)
_OFFLINE_ANSWER = "Resposta offline baseada nos trechos fornecidos."


def _offline(system_prompt: str, user_prompt: str) -> str:
    if "alertas" not in system_prompt:
        return _OFFLINE_ANSWER
    m = _CLAUSE.search(user_prompt)
    clausula = m.group(1).strip() if m else ""
    alertas = [
        {
            "id": rid,
            "trecho": clausula[:120],
            "resumo": risco,
            "detalhe": "Análise offline determinística.",
            "discorda": False,
        }
        for rid, risco in _RISK_LINE.findall(user_prompt)
    ]
    return json.dumps({"alertas": alertas}, ensure_ascii=False)


async def chat_completion(
    system_prompt: str,
    user_prompt: str,
    settings: Settings | None = None,
    *,
    temperature: float = 0.1,
    max_tokens: int = 900,
) -> tuple[str, int]:
    """Retorna ``(texto, tokens_usados)``; offline (0 tokens) sem ``OPENROUTER_API_KEY``."""
    settings = settings or Settings()
    offline = not settings.OPENROUTER_API_KEY

    # Span manual (conteudo mascarado — o grafo nunca ve texto cru).
    with tracer.start_as_current_span("chat_completion") as span:
        span.set_attribute("openinference.span.kind", "LLM")
        span.set_attribute(
            "llm.model_name", "offline-stub" if offline else settings.CHAT_MODEL
        )
        span.set_attribute("leia.offline", offline)
        span.set_attribute(
            "input.value",
            json.dumps({"system": system_prompt, "user": user_prompt}, ensure_ascii=False),
        )
        content, tokens = await _chat_completion_raw(
            system_prompt, user_prompt, settings, temperature=temperature, max_tokens=max_tokens
        )
        span.set_attribute("output.value", content)
        if tokens:
            span.set_attribute("llm.token_count.total", tokens)
        return content, tokens


async def _chat_completion_raw(
    system_prompt: str,
    user_prompt: str,
    settings: Settings,
    *,
    temperature: float,
    max_tokens: int,
) -> tuple[str, int]:
    if not settings.OPENROUTER_API_KEY:
        return _offline(system_prompt, user_prompt), 0

    url = f"{settings.OPENROUTER_BASE_URL.rstrip('/')}/chat/completions"
    payload = {
        "model": settings.CHAT_MODEL,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    headers = {"Authorization": f"Bearer {settings.OPENROUTER_API_KEY}"}
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(url, json=payload, headers=headers)
    resp.raise_for_status()
    data = resp.json()
    content = data["choices"][0]["message"]["content"] or ""
    return content, int(data.get("usage", {}).get("total_tokens", 0))

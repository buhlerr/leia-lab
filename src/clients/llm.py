"""Cliente assincrono de chat completion (OpenRouter/OpenAI) com fallback offline."""

from __future__ import annotations

import json
import re

import httpx

from src.config import Settings
from src.tracing import client_span, tag_span

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


@client_span("chat_completion", allowed=("system_prompt", "user_prompt", "temperature", "max_tokens"))
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
    tag_span(model=settings.CHAT_MODEL, offline=not settings.OPENROUTER_API_KEY)

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

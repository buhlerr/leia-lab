"""Cliente assincrono de chat completion (OpenRouter/OpenAI) com fallback offline."""

from __future__ import annotations

import json
import re
from typing import NamedTuple

import httpx

from src.config import Settings
from src.tracing import client_span, tag_span

_RISK_LINE = re.compile(r"^\s*-\s*([^\s:]+)\s*:\s*(.+?)\s*$", re.MULTILINE)
_CLAUSE = re.compile(r"<clausula>(.*?)</clausula>", re.DOTALL)
_OFFLINE_ANSWER = "Resposta offline baseada nos trechos fornecidos."


class ChatResult(NamedTuple):
    """Texto da resposta junto com os tokens usados e o custo em dolares."""

    text: str
    tokens: int
    cost_usd: float


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


@client_span(
    "chat_completion", allowed=("system_prompt", "user_prompt", "temperature", "max_tokens", "json_output")
)
async def chat_completion(
    system_prompt: str,
    user_prompt: str,
    settings: Settings | None = None,
    *,
    temperature: float = 0.1,
    max_tokens: int | None = None,
    json_output: bool = False,
) -> ChatResult:
    """Retorna ``ChatResult``; offline (0 tokens, custo 0) sem ``OPENROUTER_API_KEY``."""
    settings = settings or Settings()
    tag_span(model=settings.CHAT_MODEL, offline=not settings.OPENROUTER_API_KEY)

    if not settings.OPENROUTER_API_KEY:
        return ChatResult(_offline(system_prompt, user_prompt), 0, 0.0)

    url = f"{settings.OPENROUTER_BASE_URL.rstrip('/')}/chat/completions"
    payload = {
        "model": settings.CHAT_MODEL,
        "temperature": temperature,
        "max_tokens": settings.CHAT_MAX_TOKENS if max_tokens is None else max_tokens,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "provider": {"data_collection": settings.OPENROUTER_DATA_COLLECTION},
        "usage": {"include": True},
    }
    if json_output:
        payload["response_format"] = {"type": "json_object"}
        payload["provider"]["require_parameters"] = True
    headers = {"Authorization": f"Bearer {settings.OPENROUTER_API_KEY}"}
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(url, json=payload, headers=headers)
    resp.raise_for_status()
    data = resp.json()
    content = data["choices"][0]["message"]["content"] or ""
    usage = data.get("usage") or {}
    return ChatResult(content, int(usage.get("total_tokens", 0)), float(usage.get("cost") or 0.0))

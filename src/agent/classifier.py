"""Classificacao do tipo de uma minuta a partir dos tipos cadastrados."""

from __future__ import annotations

import logging
from typing import Literal

import httpx
from pydantic_ai import Agent

from src.agent.llm import build_model, minuta_history
from src.config import Settings
from src.db.config_repo import MinutaType

logger = logging.getLogger(__name__)

NONE_LABEL = "__nenhum__"
CLASSIFIER_EXCERPT_CHARS = 8_000

CLASSIFIER_INSTRUCTIONS = (
    "Identifique o tipo do documento entre os nomes permitidos. "
    f"Responda {NONE_LABEL} se nenhum servir."
)


async def classify_minuta(
    text: str,
    types: list[MinutaType],
    settings: Settings,
    *,
    http_client: httpx.AsyncClient | None = None,
) -> MinutaType | None:
    """Tipo da minuta, ou ``None`` quando nenhum tipo serve ou a chamada falha."""
    if not types:
        return None

    output = Literal[tuple(t.name for t in types) + (NONE_LABEL,)]  # type: ignore
    # So o inicio do documento: identificar o tipo nao paga a minuta inteira, e o
    # primeiro relatorio e quem grava o prefixo completo no cache.
    agent = Agent(
        build_model(settings, http_client=http_client),
        output_type=output,
    )

    try:
        result = await agent.run(
            CLASSIFIER_INSTRUCTIONS,
            message_history=minuta_history(text[:CLASSIFIER_EXCERPT_CHARS]),
        )
    except Exception as exc:
        # Nunca registre o texto da minuta: ele e confidencial.
        logger.warning("Falha ao classificar minuta: %s", type(exc).__name__)
        return None

    name = result.output
    if name == NONE_LABEL:
        return None

    for minuta_type in types:
        if minuta_type.name == name:
            return minuta_type
    return None

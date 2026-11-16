"""Rastreio na LangSmith (ADR-0002): a vista de depuracao, nao a fonte da auditoria.

A auditoria continua na trilha do Postgres (``analysis_trail``). O rastreio mostra o grafo e cada
chamada externa; so conteudo MASCARADO chega aqui, porque o grafo nunca ve texto cru (M2b).

Ligar: ``with langsmith_tracing(): ...`` (CLI: ``--trace``). Le ``LANGSMITH_API_KEY`` e
``LANGSMITH_PROJECT`` das variaveis de ambiente (de usuario no Windows), nunca de arquivo do repo.
Atencao: o SDK tambem obedece a ``LANGSMITH_TRACING=true`` no ambiente e, com ela, rastrearia toda
execucao. Deixe essa variavel desligada e ligue o rastreio so por este bloco.

Os clientes Jev e LLM sao httpx cru, sem instrumentacao automatica: ``client_span`` cria um span
por chamada. Ele recebe uma lista de argumentos PERMITIDOS: ``settings`` (chaves de API, senha do
banco no DATABASE_URL) nunca entra no traco.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from langsmith import Client, traceable
from langsmith.run_helpers import get_current_run_tree, tracing_context


def client_span(name: str, allowed: tuple[str, ...]) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Span ``llm`` da LangSmith que so registra os argumentos em ``allowed``."""

    def keep(inputs: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in inputs.items() if k in allowed}

    return traceable(run_type="llm", name=name, process_inputs=keep)


def tag_span(**metadata: Any) -> None:
    """Acrescenta metadados (modelo, offline) ao span atual; nada se o rastreio estiver desligado."""
    run = get_current_run_tree()
    if run is not None:
        run.metadata.update(metadata)


@contextmanager
def langsmith_tracing(client: Client | None = None, project_name: str | None = None) -> Iterator[Client]:
    """Liga o rastreio dentro do bloco e espera o envio ao sair."""
    if client is None:
        if not os.environ.get("LANGSMITH_API_KEY"):
            raise RuntimeError("LANGSMITH_API_KEY ausente (variavel de usuario do Windows)")
        client = Client()
    project = project_name or os.environ.get("LANGSMITH_PROJECT") or "leia-lab"
    with tracing_context(enabled=True, client=client, project_name=project):
        try:
            yield client
        finally:
            client.flush()

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


def month_start(now: Any = None) -> Any:
    import datetime as dt

    now = now or dt.datetime.now(dt.UTC)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def trace_usage(client: Any, project_name: str, *, limit: int, warn_at: float = 0.8, now: Any = None) -> dict[str, Any]:
    """Tracos (runs raiz) do projeto no mes corrente contra o limite do plano.

    A LangSmith cobra por traco (a arvore inteira, 1 por analise). O limite do plano vale para a
    ORGANIZACAO: se houver outros projetos, a contagem deste e um piso, nao o total.
    """
    since = month_start(now)
    n = sum(1 for _ in client.list_runs(project_name=project_name, is_root=True, start_time=since, select=["id"]))
    status = "estourado" if n >= limit else "alerta" if n >= warn_at * limit else "ok"
    return {"project": project_name, "since": since.date().isoformat(), "traces": n, "limit": limit, "status": status}

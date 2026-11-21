"""Rastreio na LangSmith e/ou MLflow (ADR-0002): vista de depuracao, nao fonte da auditoria.

A auditoria continua na trilha do Postgres (``analysis_trail``). O rastreio mostra o grafo e cada
chamada externa; so conteudo MASCARADO chega aqui, porque o grafo nunca ve texto cru (M2b).

Ligar em modo dual: ``with tracing_session(): ...`` (CLI: ``--trace``). Le ``LANGSMITH_API_KEY`` /
``LANGSMITH_PROJECT`` e ``MLFLOW_TRACKING_URI`` / ``MLFLOW_EXPERIMENT_NAME`` das variaveis de
ambiente, nunca de arquivo do repo.
Atencao: o SDK da LangSmith tambem obedece a ``LANGSMITH_TRACING=true`` no ambiente; deixe essa
variavel desligada e ligue o rastreio so por este bloco.

Os clientes Jev e LLM sao httpx cru, sem instrumentacao automatica: ``client_span`` cria um span
por chamada nos backends ativos. Ele recebe uma lista de argumentos PERMITIDOS: ``settings``
(chaves de API, senha do banco no DATABASE_URL) nunca entra no traco.
"""

from __future__ import annotations

import inspect
import os
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
from functools import wraps
from typing import Any

import mlflow
import mlflow.langchain
from langsmith import Client, traceable
from langsmith.run_helpers import get_current_run_tree, tracing_context
from mlflow.entities import SpanType

_MLFLOW_ACTIVE: ContextVar[bool] = ContextVar("_mlflow_active", default=False)


def client_span(name: str, allowed: tuple[str, ...]) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Span ``llm`` nos backends ativos (LangSmith / MLflow) registrando so ``allowed``."""

    def keep(inputs: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in inputs.items() if k in allowed}

    def decorate(fn: Callable[..., Any]) -> Callable[..., Any]:
        ls_fn = traceable(run_type="llm", name=name, process_inputs=keep)(fn)
        sig = inspect.signature(fn)

        def _filtered_inputs(args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
            bound = sig.bind_partial(*args, **kwargs)
            bound.apply_defaults()
            return keep(dict(bound.arguments))

        if inspect.iscoroutinefunction(fn):

            @wraps(fn)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                if not _MLFLOW_ACTIVE.get():
                    return await ls_fn(*args, **kwargs)
                with mlflow.start_span(name=name, span_type=SpanType.LLM) as span:
                    span.set_inputs(_filtered_inputs(args, kwargs))
                    out = await ls_fn(*args, **kwargs)
                    span.set_outputs(out)
                    return out

            return async_wrapper

        @wraps(fn)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            if not _MLFLOW_ACTIVE.get():
                return ls_fn(*args, **kwargs)
            with mlflow.start_span(name=name, span_type=SpanType.LLM) as span:
                span.set_inputs(_filtered_inputs(args, kwargs))
                out = ls_fn(*args, **kwargs)
                span.set_outputs(out)
                return out

        return sync_wrapper

    return decorate


def tag_span(**metadata: Any) -> None:
    """Acrescenta metadados (modelo, offline) ao span atual; nada se o rastreio estiver desligado."""
    run = get_current_run_tree()
    if run is not None:
        run.metadata.update(metadata)
    if _MLFLOW_ACTIVE.get():
        span = mlflow.get_current_active_span()
        if span is not None:
            span.set_attributes({k: v for k, v in metadata.items() if v is not None})


@contextmanager
def langsmith_tracing(client: Client | None = None, project_name: str | None = None) -> Iterator[Client]:
    """Liga o rastreio na LangSmith dentro do bloco e espera o envio ao sair."""
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


@contextmanager
def mlflow_tracing(tracking_uri: str | None = None, experiment_name: str | None = None) -> Iterator[str]:
    """Liga o rastreio na MLflow dentro do bloco e faz flush ao sair."""
    uri = tracking_uri or os.environ.get("MLFLOW_TRACKING_URI")
    if not uri:
        raise RuntimeError("MLFLOW_TRACKING_URI ausente (variavel de ambiente)")
    exp = experiment_name or os.environ.get("MLFLOW_EXPERIMENT_NAME") or "leia-lab"
    prev_uri = mlflow.get_tracking_uri()
    token = _MLFLOW_ACTIVE.set(True)
    try:
        mlflow.set_tracking_uri(uri)
        mlflow.tracing.enable()
        mlflow.set_experiment(exp)
        mlflow.langchain.autolog(run_tracer_inline=True, silent=True)
        yield uri
    finally:
        _MLFLOW_ACTIVE.reset(token)
        try:
            mlflow.langchain.autolog(disable=True, silent=True)
        finally:
            try:
                mlflow.flush_trace_async_logging()
            finally:
                mlflow.set_tracking_uri(prev_uri)


@contextmanager
def tracing_session(
    *,
    langsmith_client: Client | None = None,
    langsmith_project: str | None = None,
    mlflow_uri: str | None = None,
    mlflow_experiment: str | None = None,
) -> Iterator[dict[str, Any]]:
    """Liga LangSmith, MLflow ou ambos em paralelo conforme as variaveis configuradas."""
    use_ls = langsmith_client is not None or bool(os.environ.get("LANGSMITH_API_KEY"))
    use_ml = mlflow_uri is not None or bool(os.environ.get("MLFLOW_TRACKING_URI"))
    if not use_ls and not use_ml:
        raise RuntimeError(
            "Nenhum backend de rastreio configurado: defina LANGSMITH_API_KEY e/ou MLFLOW_TRACKING_URI"
        )
    active: dict[str, Any] = {"langsmith": None, "mlflow": None}
    with ExitStack() as stack:
        if use_ls:
            active["langsmith"] = stack.enter_context(
                langsmith_tracing(client=langsmith_client, project_name=langsmith_project)
            )
        if use_ml:
            active["mlflow"] = stack.enter_context(
                mlflow_tracing(tracking_uri=mlflow_uri, experiment_name=mlflow_experiment)
            )
        yield active


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

"""Rastreio na LangSmith e/ou MLflow (ADR-0002): vista de depuracao, nao fonte da auditoria.

A auditoria continua na trilha do Postgres (``analysis_trail``). O rastreio mostra o grafo e cada
chamada externa; so conteudo MASCARADO chega aqui, porque o grafo nunca ve texto cru (M2b).

Ligar em modo dual: ``with tracing_session(): ...`` (CLI: ``--trace``). Le ``LANGSMITH_API_KEY`` /
``LANGSMITH_PROJECT`` e ``MLFLOW_TRACKING_URI`` / ``MLFLOW_EXPERIMENT_NAME`` das variaveis de
ambiente, nunca de arquivo do repo.
Atencao: o SDK da LangSmith tambem obedece a ``LANGSMITH_TRACING=true`` no ambiente; deixe essa
variavel desligada e ligue o rastreio so por este bloco.

Servidor de vida longa (API, ``src/api``): ``configure_mlflow`` uma vez na subida e
``with mlflow_request():`` por requisicao, com flush antes de devolver a resposta. A API nunca
liga a LangSmith. ``tag_analysis`` amarra o traco a analise e ``find_trace`` recupera o traco
pelo id para linkar do admin (MLflow pode estar fora do ar: fronteira que devolve ``None``).

Os clientes Jev e LLM sao httpx cru, sem instrumentacao automatica: ``client_span`` cria um span
por chamada nos backends ativos. Ele recebe uma lista de argumentos PERMITIDOS: ``settings``
(chaves de API, senha do banco no DATABASE_URL) nunca entra no traco.
"""

from __future__ import annotations

import inspect
import os
import uuid
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from functools import lru_cache, wraps
from typing import Any

import mlflow
import mlflow.langchain
from langsmith import Client, traceable
from langsmith.run_helpers import get_current_run_tree, tracing_context
from mlflow.entities import SpanType
from mlflow.tracing.client import TracingClient

_MLFLOW_ACTIVE: ContextVar[bool] = ContextVar("_mlflow_active", default=False)

# Tag que amarra um traco (LangSmith ou MLflow) a uma analise: e o analysis_id da linha em
# ``analyses``. Chave com ponto exige crases no filtro de busca do MLflow.
ANALYSIS_TAG = "leia.analysis_id"

# Tracking uri que o processo tinha antes de ``configure_mlflow`` (None = nao tinha).
_MLFLOW_PREV_URI: str | None = None


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


def tag_analysis(analysis_id: str) -> None:
    """Amarra o traco atual a analise: metadata no run da LangSmith, tag ``ANALYSIS_TAG`` no MLflow.

    No-op com o rastreio desligado. Chamado no no ``iniciar`` logo depois do id existir, entao
    vale para o CLI (``--trace``) e para a API.
    """
    run = get_current_run_tree()
    if run is not None:
        run.metadata.update({"analysis_id": analysis_id})
    if _MLFLOW_ACTIVE.get():
        mlflow.update_current_trace(tags={ANALYSIS_TAG: analysis_id})


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


def configure_mlflow(tracking_uri: str, experiment_name: str) -> None:
    """Configura o MLflow do PROCESSO: uri, tracing, experimento e autolog do LangChain.

    Uma vez na subida de um servidor de vida longa (lifespan da API). Para o bloco curto do CLI
    use ``mlflow_tracing``, que desfaz tudo ao sair. ``shutdown_mlflow`` desfaz o que esta
    funcao fez: sem ela, o ``set_tracking_uri`` abaixo grava a variavel de ambiente
    ``MLFLOW_TRACKING_URI`` (heranca para subprocessos) e ela vaza para o resto do processo.
    """
    global _MLFLOW_PREV_URI
    _MLFLOW_PREV_URI = os.environ.get("MLFLOW_TRACKING_URI")
    mlflow.set_tracking_uri(tracking_uri)
    mlflow.tracing.enable()
    mlflow.set_experiment(experiment_name)
    mlflow.langchain.autolog(run_tracer_inline=True, silent=True)


def shutdown_mlflow() -> None:
    """Desfaz o ``configure_mlflow`` na descida do servidor.

    Desliga o autolog, descarrega o que falta na fila e devolve o tracking uri que o processo
    tinha antes (``None`` desconfigura e apaga a variavel de ambiente).
    """
    mlflow.langchain.autolog(disable=True, silent=True)
    mlflow.flush_trace_async_logging()
    mlflow.set_tracking_uri(_MLFLOW_PREV_URI)


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
        configure_mlflow(uri, exp)
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
def mlflow_request() -> Iterator[None]:
    """Uma requisicao num servidor ja configurado por ``configure_mlflow``.

    Ativa o rastreio so dentro do bloco (os spans dos clientes olham ``_MLFLOW_ACTIVE``) e, ao
    sair, descarrega a fila do MLflow: o traco chega ao servidor antes da resposta HTTP voltar.
    """
    token = _MLFLOW_ACTIVE.set(True)
    try:
        yield
    finally:
        _MLFLOW_ACTIVE.reset(token)
        mlflow.flush_trace_async_logging()


@dataclass(frozen=True)
class TraceRef:
    """Referencia minima a um traco no MLflow: o que o admin precisa para linkar e mostrar."""

    experiment_id: str
    trace_id: str
    duration_ms: int | None


# Chamadas de consulta ao MLflow curtas: timeout de 5 s e sem reflexo de retentativa longa.
# So entram se o operador nao as definiu; sao restauradas no fim da busca.
_SHORT_MLFLOW_HTTP_ENV = {
    "MLFLOW_HTTP_REQUEST_TIMEOUT": "5",
    "MLFLOW_HTTP_REQUEST_MAX_RETRIES": "1",
    "MLFLOW_HTTP_REQUEST_BACKOFF_FACTOR": "1",
}


@contextmanager
def _short_mlflow_http() -> Iterator[None]:
    saved = {k: os.environ.get(k) for k in _SHORT_MLFLOW_HTTP_ENV}
    os.environ.update({k: v for k, v in _SHORT_MLFLOW_HTTP_ENV.items() if saved[k] is None})
    try:
        yield
    finally:
        for key, prev in saved.items():
            if prev is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = prev


@lru_cache(maxsize=4)
def _trace_client(tracking_uri: str) -> TracingClient:
    return TracingClient(tracking_uri=tracking_uri)


def find_trace(tracking_uri: str, experiment_name: str, analysis_id: uuid.UUID) -> TraceRef | None:
    """Acha o traco de uma analise pelo tag ``ANALYSIS_TAG``, ou ``None``.

    Fronteira: ``analysis_id`` e um ``uuid.UUID`` (o valor interpolado no filtro e seguro) e
    qualquer falha (MLflow fora do ar, experimento inexistente, resposta estranha) vira ``None``,
    nunca excecao. O cliente usa o ``tracking_uri`` dado, nunca o global do processo.
    """
    if not tracking_uri:
        return None
    with _short_mlflow_http():
        try:
            client = _trace_client(tracking_uri)
            experiment = client.store.get_experiment_by_name(experiment_name)
            if experiment is None:
                return None
            found = client.search_traces(
                experiment_ids=[experiment.experiment_id],
                filter_string=f"tags.`{ANALYSIS_TAG}` = '{analysis_id}'",
                max_results=1,
                include_spans=False,
            )
        except Exception:
            return None
    if not found:
        return None
    info = found[0].info
    return TraceRef(
        experiment_id=experiment.experiment_id,
        trace_id=info.trace_id,
        duration_ms=info.execution_duration,
    )


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

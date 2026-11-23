"""Rastreio na LangSmith e/ou MLflow (ADR-0002): vista de depuracao, nao fonte da auditoria.

A auditoria continua na trilha do Postgres (``analysis_trail``). O rastreio mostra o grafo e cada
chamada externa; so conteudo MASCARADO chega aqui, porque o grafo nunca ve texto cru (M2b).

Ligar em modo dual: ``with tracing_session(): ...`` (CLI: ``--trace``). Le ``LANGSMITH_API_KEY`` /
``LANGSMITH_PROJECT`` e ``MLFLOW_TRACKING_URI`` / ``MLFLOW_EXPERIMENT_NAME`` das variaveis de
ambiente, nunca de arquivo do repo.
Atencao: o SDK da LangSmith tambem obedece a ``LANGSMITH_TRACING=true`` no ambiente; deixe essa
variavel desligada e ligue o rastreio so por este bloco.

Servidor de vida longa (API, ``src/api``): ``with mlflow_configured(...)`` em volta da vida do
processo e ``with mlflow_request():`` por requisicao; o envio fica com o exportador em segundo
plano. A API nunca liga a LangSmith. ``tag_analysis`` amarra o traco a analise e ``find_trace``
recupera o traco pelo id para linkar do admin (MLflow pode estar fora do ar: devolve ``None``).

Os clientes Jev e LLM sao httpx cru, sem instrumentacao automatica: ``client_span`` cria um span
por chamada nos backends ativos. Ele recebe uma lista de argumentos PERMITIDOS: ``settings``
(chaves de API, senha do banco no DATABASE_URL) nunca entra no traco.

Rastreio opcional nunca derruba a analise: toda chamada que esta fachada faz ao SDK do MLflow ou
da LangSmith passa por ``_guarded``, que registra a falha e devolve um valor neutro. Falha do MLflow
desliga o MLflow do bloco corrente; falha da LangSmith perde so aquele span, e se o cliente nem
sobe o bloco roda sem LangSmith. Erro da chamada embrulhada (inclusive cancelamento) sai intacto.
"""

from __future__ import annotations

import inspect
import logging
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
from langsmith import Client, trace
from langsmith.run_helpers import get_current_run_tree, tracing_context
from langsmith.utils import tracing_is_enabled
from mlflow.entities import SpanType
from mlflow.tracing.client import TracingClient
from mlflow.tracing.provider import is_tracing_enabled

_log = logging.getLogger(__name__)

# Chave com ponto exige crases no filtro de busca do MLflow.
ANALYSIS_TAG = "leia.analysis_id"


@dataclass
class _MlflowRun:
    """Rastreio MLflow de um bloco (CLI ou requisicao): ligado ate a primeira falha do backend.

    Mutavel de proposito: as tarefas do grafo copiam o contexto, mas compartilham este objeto, entao
    uma falha em qualquer no desliga o rastreio do bloco inteiro.
    """

    on: bool = True


_MLFLOW_RUN: ContextVar[_MlflowRun | None] = ContextVar("_mlflow_run", default=None)


def _guarded(call: Callable[[], Any], run: _MlflowRun | None = None, default: Any = None) -> Any:
    """Unica porta para o SDK de rastreio: falha vira aviso, ``default`` e ``run`` desligado."""
    try:
        return call()
    except Exception as exc:
        _log.warning("rastreio falhou (%s); segue sem ele", type(exc).__name__)
        if run is not None:
            run.on = False
        return default


def _active_run() -> _MlflowRun | None:
    run = _MLFLOW_RUN.get()
    return run if run is not None and run.on else None


@contextmanager
def _mlflow_run() -> Iterator[None]:
    token = _MLFLOW_RUN.set(_MlflowRun())
    try:
        yield
    finally:
        _MLFLOW_RUN.reset(token)


def _close(stack: ExitStack, exc: BaseException | None, run: _MlflowRun | None) -> None:
    if exc is None:
        _guarded(stack.close, run)
    else:
        _guarded(lambda: stack.__exit__(type(exc), exc, exc.__traceback__), run)


def _as_outputs(out: Any) -> dict[str, Any]:
    return out if isinstance(out, dict) else {"output": out}


@contextmanager
def _llm_span(name: str, inputs: Callable[[], dict[str, Any]]) -> Iterator[Callable[[Any], None]]:
    """Span ``llm`` em volta de uma chamada nos backends ativos; devolve quem grava a saida.

    Entrada e saida de cada backend ficam separadas da chamada: erro do SDK nunca sai, erro da
    chamada sai intacto.
    """
    ls_stack, ml_stack = ExitStack(), ExitStack()
    ls_run = _guarded(
        lambda: ls_stack.enter_context(trace(name, run_type="llm", inputs=inputs())) if tracing_is_enabled() else None
    )
    run = _active_run()
    span = None
    if run is not None:
        span = _guarded(lambda: ml_stack.enter_context(mlflow.start_span(name=name, span_type=SpanType.LLM)), run)
    if span is not None:
        _guarded(lambda: span.set_inputs(inputs()), run)

    def record(out: Any) -> None:
        if ls_run is not None:
            _guarded(lambda: ls_run.end(outputs=_as_outputs(out)))
        if span is not None and run.on:
            _guarded(lambda: span.set_outputs(out), run)

    try:
        yield record
    except BaseException as exc:
        _close(ml_stack, exc, run)
        _close(ls_stack, exc, None)
        raise
    _close(ml_stack, None, run)
    _close(ls_stack, None, None)


def _langsmith_metadata(metadata: dict[str, Any]) -> None:
    def update() -> None:
        current = get_current_run_tree()
        if current is not None:
            current.metadata.update(metadata)

    _guarded(update)


def client_span(name: str, allowed: tuple[str, ...]) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Span ``llm`` nos backends ativos (LangSmith / MLflow) registrando so ``allowed``."""

    def keep(inputs: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in inputs.items() if k in allowed}

    def decorate(fn: Callable[..., Any]) -> Callable[..., Any]:
        sig = inspect.signature(fn)

        def _filtered_inputs(args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
            bound = sig.bind_partial(*args, **kwargs)
            bound.apply_defaults()
            return keep(dict(bound.arguments))

        if inspect.iscoroutinefunction(fn):

            @wraps(fn)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                with _llm_span(name, lambda: _filtered_inputs(args, kwargs)) as record:
                    out = await fn(*args, **kwargs)
                    record(out)
                    return out

            return async_wrapper

        @wraps(fn)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            with _llm_span(name, lambda: _filtered_inputs(args, kwargs)) as record:
                out = fn(*args, **kwargs)
                record(out)
                return out

        return sync_wrapper

    return decorate


def tag_span(**metadata: Any) -> None:
    """Acrescenta metadados (modelo, offline) ao span atual; nada se o rastreio estiver desligado."""
    _langsmith_metadata(metadata)
    run = _active_run()
    if run is None:
        return

    def set_attributes() -> None:
        span = mlflow.get_current_active_span()
        if span is not None:
            span.set_attributes({k: v for k, v in metadata.items() if v is not None})

    _guarded(set_attributes, run)


def tag_analysis(analysis_id: str) -> None:
    """Amarra o traco atual a analise: metadata no run da LangSmith, tag ``ANALYSIS_TAG`` no MLflow.

    No-op com o rastreio desligado. Chamado no no ``iniciar`` logo depois do id existir, entao
    vale para o CLI (``--trace``) e para a API.
    """
    _langsmith_metadata({"analysis_id": analysis_id})
    run = _active_run()
    if run is not None:
        _guarded(lambda: mlflow.update_current_trace(tags={ANALYSIS_TAG: analysis_id}), run)


@contextmanager
def langsmith_tracing(client: Client | None = None, project_name: str | None = None) -> Iterator[Client | None]:
    """Liga o rastreio na LangSmith dentro do bloco e espera o envio ao sair.

    Devolve ``None`` se a LangSmith falhou ao subir (cliente ou contexto): o bloco roda sem ela.
    """
    if client is None:
        if not os.environ.get("LANGSMITH_API_KEY"):
            raise RuntimeError("LANGSMITH_API_KEY ausente (variavel de usuario do Windows)")
        client = _guarded(Client)
    project = project_name or os.environ.get("LANGSMITH_PROJECT") or "leia-lab"
    stack = ExitStack()

    def start() -> bool:
        stack.enter_context(tracing_context(enabled=True, client=client, project_name=project))
        return True

    if client is None or not _guarded(start, default=False):
        yield None
        return
    try:
        yield client
    finally:
        _guarded(client.flush)
        _guarded(stack.close)


def _restore_tracking_uri(env_value: str | None) -> None:
    try:
        mlflow.set_tracking_uri(env_value or None)
    finally:
        if env_value is None:
            os.environ.pop("MLFLOW_TRACKING_URI", None)
        else:
            os.environ["MLFLOW_TRACKING_URI"] = env_value


@contextmanager
def mlflow_configured(tracking_uri: str, experiment_name: str) -> Iterator[bool]:
    """Configura o MLflow do PROCESSO dentro do bloco e sempre desfaz ao sair.

    Liga uri, tracing, experimento e autolog do LangChain; devolve ``False`` se o MLflow falhou
    (o que chegou a ser ligado ja foi desfeito). Ao sair desliga o autolog, descarrega a fila, volta
    o tracking uri ao de antes e o tracing ao estado anterior: ``set_tracking_uri`` grava a variavel
    de ambiente ``MLFLOW_TRACKING_URI``, e sem desfazer ela vazaria para o resto do processo.
    """
    prev_uri = os.environ.get("MLFLOW_TRACKING_URI")
    was_enabled = _guarded(is_tracing_enabled, default=True)

    def configure() -> bool:
        mlflow.set_tracking_uri(tracking_uri)
        mlflow.tracing.enable()
        mlflow.set_experiment(experiment_name)
        mlflow.langchain.autolog(run_tracer_inline=True, silent=True)
        return True

    def undo() -> None:
        _guarded(lambda: mlflow.langchain.autolog(disable=True, silent=True))
        _guarded(mlflow.flush_trace_async_logging)
        _guarded(lambda: _restore_tracking_uri(prev_uri))  # troca de uri reinicia o tracing do MLflow
        _guarded(mlflow.tracing.reset if was_enabled else mlflow.tracing.disable)

    if not _guarded(configure, default=False):
        undo()
        yield False
        return
    try:
        yield True
    finally:
        undo()


@contextmanager
def mlflow_tracing(tracking_uri: str | None = None, experiment_name: str | None = None) -> Iterator[str]:
    """Liga o rastreio na MLflow dentro do bloco; se o MLflow falhar, o bloco roda sem ele."""
    uri = tracking_uri or os.environ.get("MLFLOW_TRACKING_URI")
    if not uri:
        raise RuntimeError("MLFLOW_TRACKING_URI ausente (variavel de ambiente)")
    exp = experiment_name or os.environ.get("MLFLOW_EXPERIMENT_NAME") or "leia-lab"
    with mlflow_configured(uri, exp) as configured:
        if not configured:
            yield uri
            return
        with _mlflow_run():
            yield uri


@contextmanager
def mlflow_request() -> Iterator[None]:
    """Uma requisicao num servidor dentro de ``mlflow_configured``.

    Ativa o rastreio so dentro do bloco. O envio fica com o exportador em segundo plano do MLflow:
    descarregar a fila aqui travaria o event loop da API inteira enquanto o MLflow estivesse lento
    ou fora do ar.
    """
    with _mlflow_run():
        yield


@dataclass(frozen=True)
class TraceRef:
    """Referencia minima a um traco no MLflow: o que o admin precisa para linkar e mostrar."""

    experiment_id: str
    trace_id: str
    duration_ms: int | None


# O padrao do MLflow e 120 s por chamada com 7 retentativas: minutos de espera se o servidor
# cair. Servidores de vida longa (API, admin) usam chamadas curtas; o operador ainda manda.
_SHORT_MLFLOW_HTTP_ENV = {
    "MLFLOW_HTTP_REQUEST_TIMEOUT": "5",
    "MLFLOW_HTTP_REQUEST_MAX_RETRIES": "1",
    "MLFLOW_HTTP_REQUEST_BACKOFF_FACTOR": "1",
}


def use_short_mlflow_http() -> None:
    """Chamadas curtas ao MLflow no processo inteiro, sem sobrescrever o que o operador definiu."""
    for key, value in _SHORT_MLFLOW_HTTP_ENV.items():
        os.environ.setdefault(key, value)


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
    use_short_mlflow_http()

    def find() -> TraceRef | None:
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
        if not found:
            return None
        info = found[0].info
        return TraceRef(
            experiment_id=experiment.experiment_id,
            trace_id=info.trace_id,
            duration_ms=info.execution_duration,
        )

    return _guarded(find)


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

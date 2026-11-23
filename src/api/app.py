"""Shell HTTP fino sobre o nucleo puro (``src.api.service``).

Autenticacao servico-a-servico por bearer ``LEIA_API_TOKEN``, separada dos
logins do Django Admin; sem token configurado o app recusa subir (fail
closed). Rotas:

* ``POST /v1/analyses``: multipart campo ``file`` (.pdf/.docx/.txt) e header obrigatorio
  ``Idempotency-Key``, sincrono; devolve 201 com o resultado completo (report + trilha). A mesma
  chave com a mesma entrada nunca roda de novo: 200 com a analise terminada, ou 409 com o
  ``analysis_id`` se ela ainda roda (``analysis_in_progress``) ou falhou (``analysis_failed``);
  com outra entrada, 409 ``idempotency_key_reused``.
* ``GET  /v1/analyses/{analysis_id}``: o mesmo contrato de um POST anterior.
* ``GET  /healthz``: sem autenticacao.

O nome real do arquivo enviado nunca aparece em resposta, log ou erro: so o
apelido ``documento-<sha8>.<ext>`` e respostas de erro de codigo fixo.
"""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import logging
import os
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

import asyncpg
from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, Response, UploadFile
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.api.schemas import AnalysisResult
from src.api.service import AnalysisNotReplayable, evaluate_upload, load_analysis
from src.config import Settings
from src.db.analyses import AnalysisKeyTaken
from src.graphs.analyze_minuta_graph import build_analyze_minuta_graph
from src.ingest.extract import MAX_UPLOAD_BYTES, DocumentError
from src.tracing import configure_mlflow, mlflow_request, shutdown_mlflow, use_short_mlflow_http

_log = logging.getLogger(__name__)

_401_BODY = {"code": "unauthorized", "message": "Token de servico ausente ou invalido."}
_409_KEY_REUSED = {
    "code": "idempotency_key_reused",
    "message": "Esta Idempotency-Key ja foi usada para outro documento.",
}
_409_NOT_REPLAYABLE = {
    "running": (
        "analysis_in_progress",
        "A analise desta Idempotency-Key ainda esta em curso; consulte GET /v1/analyses/{analysis_id}.",
    ),
    "failed": (
        "analysis_failed",
        "A analise desta Idempotency-Key falhou; envie de novo com uma Idempotency-Key nova.",
    ),
}
_DISCONNECT_POLL = 0.5  # s entre sondas de desconexao


class ClientDisconnected(Exception):
    """O cliente foi embora antes da analise terminar."""


async def _watch_disconnect(request: Request) -> bool:
    """True quando o canal do pedido reporta ``http.disconnect``; sonda ate la."""
    while not await request.is_disconnected():
        await asyncio.sleep(_DISCONNECT_POLL)
    return True


async def run_disconnect_guarded(work: Any, request: Request) -> Any:
    """Roda ``work`` e devolve o resultado; desconexao do cliente cancela o trabalho.

    O cancelamento atravessa ``analyze()``: a linha de ``analyses`` termina 'failed' pelo
    dono do ciclo de vida, em vez de seguir gastando chamadas pagas para um cliente que ja foi.
    """
    task = asyncio.ensure_future(work)
    watcher = asyncio.ensure_future(_watch_disconnect(request))
    try:
        await asyncio.wait({task, watcher}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        watcher.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await watcher
    if task.done():
        return task.result()  # levanta a excecao se work falhou
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    raise ClientDisconnected()


def _require_token_factory(expected: str) -> Any:
    """Dependencia de auth: comparacao em tempo constante, 401 caso contrario."""

    async def require_token(authorization: Annotated[str | None, Header()] = None) -> None:
        scheme, _, supplied = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not hmac.compare_digest(supplied.encode(), expected.encode()):
            raise HTTPException(status_code=401, detail=_401_BODY)

    return require_token


async def _start_mlflow(cfg: Settings) -> bool:
    """Liga o MLflow do processo; se ele nao responder, a API sobe sem rastreio.

    O rastreio e vista de depuracao, nao a auditoria (que fica no Postgres): o MLflow fora do ar
    nunca impede a API de subir.
    """
    use_short_mlflow_http()
    # O trace so fica buscavel quando o span raiz sai do lote; o padrao espera ate 5 s e o admin,
    # que abre o detalhe logo depois do POST, mostraria "sem trace".
    os.environ.setdefault("MLFLOW_ASYNC_TRACE_LOGGING_MAX_INTERVAL_MILLIS", "500")
    try:
        await asyncio.to_thread(configure_mlflow, cfg.MLFLOW_TRACKING_URI, cfg.MLFLOW_EXPERIMENT_NAME)
    except Exception:
        _log.warning("MLflow indisponivel na subida; a API segue sem rastreio ate reiniciar")
        return False
    return True


def create_app(settings: Settings | None = None) -> FastAPI:
    """Monta a API. Recusa subir sem ``LEIA_API_TOKEN`` (fail closed)."""
    cfg = settings or Settings()
    if not cfg.LEIA_API_TOKEN:
        raise RuntimeError("LEIA_API_TOKEN is empty; refusing to start the API")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        pool = await asyncpg.create_pool(dsn=cfg.DATABASE_URL, min_size=1, max_size=4)
        app.state.pool = pool
        # O grafo fecha sobre o pool: regras e trilha passam por ele.
        app.state.graph = build_analyze_minuta_graph(pool, cfg)
        app.state.mlflow_on = False
        try:
            if cfg.MLFLOW_TRACKING_URI:  # LangSmith fica fora da API: so o MLflow self-hosted
                app.state.mlflow_on = await _start_mlflow(cfg)
            yield
        finally:
            if app.state.mlflow_on:
                shutdown_mlflow()
            await pool.close()

    app = FastAPI(title="leia-lab API", version="1", lifespan=lifespan)
    require_token = Depends(_require_token_factory(cfg.LEIA_API_TOKEN))

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        # Envelope unico de erro: {"code", "message"}, o mesmo dos DocumentError.
        detail = exc.detail if isinstance(exc.detail, dict) else {"message": str(exc.detail)}
        return JSONResponse(status_code=exc.status_code, content=detail)

    @app.exception_handler(DocumentError)
    async def _document_error(request: Request, exc: DocumentError) -> JSONResponse:
        # O corpo nunca ecoa o documento nem o nome real do arquivo: so o contrato da classe.
        return JSONResponse(status_code=exc.http_status, content={"code": exc.code, "message": exc.public_message})

    @app.exception_handler(AnalysisKeyTaken)
    async def _key_reused(request: Request, exc: AnalysisKeyTaken) -> JSONResponse:
        return JSONResponse(status_code=409, content=_409_KEY_REUSED)

    @app.exception_handler(AnalysisNotReplayable)
    async def _not_replayable(request: Request, exc: AnalysisNotReplayable) -> JSONResponse:
        code, message = _409_NOT_REPLAYABLE[exc.status]
        return JSONResponse(
            status_code=409, content={"code": code, "message": message, "analysis_id": str(exc.analysis_id)}
        )

    @app.post(
        "/v1/analyses",
        status_code=201,
        response_model=AnalysisResult,
        summary="Avalia um contrato enviado como arquivo",
        dependencies=[require_token],
        responses={
            200: {"description": "Retry: a analise terminada desta chave"},
            409: {
                "description": "Chave ja usada para outro documento (idempotency_key_reused), ou a analise "
                "dela ainda roda (analysis_in_progress) ou falhou (analysis_failed); as duas ultimas "
                "trazem analysis_id"
            },
        },
    )
    async def create_analysis(
        file: Annotated[UploadFile, File(description="Contrato (.pdf, .docx ou .txt)")],
        idempotency_key: Annotated[
            str,
            Header(
                alias="Idempotency-Key",
                min_length=1,
                max_length=255,
                description="Uma por documento enviado; repeti-la no retry devolve a mesma analise",
            ),
        ],
        request: Request,
        response: Response,
    ) -> AnalysisResult:
        # Le no maximo um byte alem do teto: o nucleo recusa sem carregar o resto.
        data = await file.read(MAX_UPLOAD_BYTES + 1)
        # Traco MLflow so quando ele subiu junto; o nucleo (service.py) segue sem rastreio.
        with mlflow_request() if app.state.mlflow_on else contextlib.nullcontext():
            try:
                result, created = await run_disconnect_guarded(
                    evaluate_upload(
                        app.state.pool,
                        app.state.graph,
                        filename=file.filename or "",
                        data=data,
                        idempotency_key=idempotency_key,
                    ),
                    request,
                )
            except ClientDisconnected:
                raise HTTPException(
                    status_code=499,
                    detail={"code": "client_disconnected", "message": "Cliente desconectou durante a analise."},
                ) from None
        if not created:
            response.status_code = 200
        return result

    @app.get(
        "/v1/analyses/{analysis_id}",
        response_model=AnalysisResult,
        summary="Recupera uma analise pelo id (report + trilha)",
        dependencies=[require_token],
    )
    async def get_analysis(analysis_id: uuid.UUID) -> AnalysisResult:
        result = await load_analysis(app.state.pool, analysis_id)
        if result is None:
            raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Analise inexistente."})
        return result

    @app.get("/healthz", summary="Sonda de vida (sem autenticacao)")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app

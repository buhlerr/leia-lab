"""Shell HTTP fino sobre o nucleo puro (``src.api.service``).

Autenticacao servico-a-servico por bearer ``LEIA_API_TOKEN``, separada dos
logins do Django Admin; sem token configurado o app recusa subir (fail
closed). Rotas:

* ``POST /v1/analyses``: multipart campo ``file`` (.pdf/.docx/.txt), sincrono;
  devolve 201 com o resultado completo (report + trilha).
* ``GET  /v1/analyses/{analysis_id}``: o mesmo contrato de um POST anterior.
* ``GET  /healthz``: sem autenticacao.

O nome real do arquivo enviado nunca aparece em resposta, log ou erro: so o
apelido ``documento-<sha8>.<ext>`` e respostas de erro de codigo fixo.
"""

from __future__ import annotations

import hmac
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

import asyncpg
from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.api.schemas import AnalysisResult
from src.api.service import evaluate_upload, load_analysis
from src.config import Settings
from src.graphs.analyze_minuta_graph import build_analyze_minuta_graph
from src.ingest.extract import (
    MAX_UPLOAD_BYTES,
    DocumentError,
    DocumentTooLargeError,
    EmptyDocumentError,
    InvalidDocumentError,
    UnsupportedFileError,
)

# Erros do nucleo -> (HTTP, codigo fixo, mensagem generica), numa tabela so.
# O corpo de erro nunca ecoa conteudo do documento nem o nome real do arquivo.
_ERROR_MAP: dict[type[DocumentError], tuple[int, str, str]] = {
    UnsupportedFileError: (415, "unsupported_file", "Formato de arquivo nao suportado; envie .pdf, .docx ou .txt."),
    DocumentTooLargeError: (413, "document_too_large", "O arquivo excede o limite de tamanho permitido."),
    InvalidDocumentError: (422, "invalid_document", "O documento enviado nao pode ser lido."),
    EmptyDocumentError: (422, "empty_document", "O documento enviado nao contem texto extraivel."),
}

_401_BODY = {"code": "unauthorized", "message": "Token de servico ausente ou invalido."}


def _require_token_factory(expected: str) -> Any:
    """Dependencia de auth: comparacao em tempo constante, 401 caso contrario."""

    async def require_token(authorization: Annotated[str | None, Header()] = None) -> None:
        scheme, _, supplied = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not hmac.compare_digest(supplied.encode(), expected.encode()):
            raise HTTPException(status_code=401, detail=_401_BODY)

    return require_token


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
        try:
            yield
        finally:
            await pool.close()

    app = FastAPI(title="leia-lab API", version="1", lifespan=lifespan)
    require_token = Depends(_require_token_factory(cfg.LEIA_API_TOKEN))

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        # Envelope unico de erro: {"code", "message"}, igual ao mapa de _ERROR_MAP.
        detail = exc.detail if isinstance(exc.detail, dict) else {"message": str(exc.detail)}
        return JSONResponse(status_code=exc.status_code, content=detail)

    @app.exception_handler(DocumentError)
    async def _document_error(request: Request, exc: DocumentError) -> JSONResponse:
        status, code, message = _ERROR_MAP.get(type(exc), _ERROR_MAP[InvalidDocumentError])
        return JSONResponse(status_code=status, content={"code": code, "message": message})

    @app.post(
        "/v1/analyses",
        status_code=201,
        response_model=AnalysisResult,
        summary="Avalia um contrato enviado como arquivo",
        dependencies=[require_token],
    )
    async def create_analysis(
        file: Annotated[UploadFile, File(description="Contrato (.pdf, .docx ou .txt)")],
    ) -> AnalysisResult:
        # Le no maximo um byte alem do teto: o nucleo recusa sem carregar o resto.
        data = await file.read(MAX_UPLOAD_BYTES + 1)
        return await evaluate_upload(
            app.state.pool, app.state.graph, filename=file.filename or "", data=data
        )

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

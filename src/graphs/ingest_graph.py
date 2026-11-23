"""Grafo LangGraph equivalente a ``Contratos - Ingestao.json``.

``START -> iniciar -> split_text -> index_chunks -> END``.
Nenhum texto de minuta entra em logs ou mensagens de excecao.

Privacidade (mesma regra do grafo de analise, M2b/M6): o grafo NUNCA ve texto cru.
``prepare_ingest_input`` (usado por ``ingest()``) le e mascara FORA do grafo; o estado nao tem
``raw_text`` nem ``file_path``, e ``iniciar`` recusa texto e apelido que nao sejam ``MaskedText``.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, TypedDict

import asyncpg
from langgraph.graph import END, START, StateGraph

from src.config import Settings
from src.ingest.extract import BoundedText, extract, require_bounded
from src.ingest.masking import MaskedText, mask_personal_data, require_masked, resolve_doc_alias, split_contract_text
from src.rag.embeddings import embed_text
from src.rag.hybrid_search import _to_pgvector_literal

_EMPTY_TEXT_MSG = "text must be a non-empty string"
_INGEST_TEXT_EXTENSIONS = frozenset({".txt", ".md"})


class IngestState(TypedDict, total=False):
    source: str
    chunk_size: int
    chunk_overlap: int
    masked_text: MaskedText
    resolved_filename: MaskedText
    chunks: list[MaskedText]
    doc_id: str
    chunks_indexed: int


def _read_path(path: Path) -> BoundedText:
    return extract(path, isolated=True, text_extensions=_INGEST_TEXT_EXTENSIONS)


async def prepare_ingest_input(
    *,
    raw_text: str | None = None,
    file_path: str | Path | None = None,
    filename: str = "",
    doc_name: str = "",
    **extra: Any,
) -> dict[str, Any]:
    """Le e mascara localmente. O dict devolvido e a UNICA coisa que entra no grafo.

    ``extra`` passa adiante so campos de configuracao (``source``, ``chunk_size``, ``chunk_overlap``).
    """
    unknown = set(extra) - {"source", "chunk_size", "chunk_overlap"}
    if unknown:
        raise TypeError(f"campos desconhecidos: {sorted(unknown)}")
    text = raw_text
    if text is None and file_path is not None:
        path = Path(file_path)
        text = require_bounded(await asyncio.to_thread(_read_path, path), what="prepare_ingest_input")
        filename = filename or path.name
    if not isinstance(text, str) or not text.strip():
        raise ValueError(_EMPTY_TEXT_MSG)
    return {"masked_text": mask_personal_data(text), "resolved_filename": resolve_doc_alias(filename, doc_name), **extra}


async def ingest(graph: Any, *, config: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
    """``prepare_ingest_input`` + execucao do grafo; devolve o estado final."""
    return await graph.ainvoke(await prepare_ingest_input(**kwargs), config)


def build_ingest_graph(pool: asyncpg.Pool, settings: Settings | None = None, *, checkpointer: Any = None) -> Any:
    """Compila o grafo de ingestao (segmenta e indexa no pgvector texto JA mascarado)."""
    cfg = settings or Settings()

    async def iniciar(state: IngestState) -> dict[str, Any]:
        require_masked([state.get("masked_text", ""), state.get("resolved_filename", "")], what="ingest graph input")
        return {}

    async def split_node(state: IngestState) -> dict[str, Any]:
        chunks = split_contract_text(
            state["masked_text"],
            chunk_size=state.get("chunk_size", 1200),
            chunk_overlap=state.get("chunk_overlap", 200),
            separator="\n",
        )
        return {"chunks": chunks}

    async def index_node(state: IngestState) -> dict[str, Any]:
        chunks = state["chunks"]
        require_masked([state["resolved_filename"], *chunks], what="kb_docs/kb_chunks insert")
        embedded = [await embed_text(chunk, cfg) for chunk in chunks]
        async with pool.acquire() as conn, conn.transaction():
            doc_id = await conn.fetchval(
                "INSERT INTO kb_docs (title, source, metadata) "
                "VALUES ($1, $2, $3::jsonb) RETURNING id",
                state["resolved_filename"],
                state.get("source", "kb"),
                json.dumps({"chunks": len(chunks)}),
            )
            await conn.executemany(
                "INSERT INTO kb_chunks (doc_id, content, sequence_order, embedding, embedding_model) "
                "VALUES ($1, $2, $3, $4::vector, $5)",
                [
                    (doc_id, chunk, i, _to_pgvector_literal(emb.vector), emb.model)
                    for i, (chunk, emb) in enumerate(zip(chunks, embedded, strict=True))
                ],
            )
        return {"doc_id": str(doc_id), "chunks_indexed": len(chunks)}

    builder = StateGraph(IngestState)
    builder.add_node("iniciar", iniciar)
    builder.add_node("split_text", split_node)
    builder.add_node("index_chunks", index_node)
    builder.add_edge(START, "iniciar")
    builder.add_edge("iniciar", "split_text")
    builder.add_edge("split_text", "index_chunks")
    builder.add_edge("index_chunks", END)
    return builder.compile(checkpointer=checkpointer)

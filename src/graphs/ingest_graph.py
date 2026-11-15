"""Grafo LangGraph equivalente a ``Contratos - Ingestao.json``.

``START -> read_file -> mask_personal_data -> split_text -> index_chunks -> END``.
Nenhum texto de minuta entra em logs ou mensagens de excecao.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, TypedDict

import asyncpg
from langgraph.graph import END, START, StateGraph

from src.config import Settings
from src.ingest.masking import mask_personal_data, resolve_doc_alias, split_contract_text
from src.rag.embeddings import get_embedding
from src.rag.hybrid_search import _to_pgvector_literal

_EMPTY_TEXT_MSG = "text must be a non-empty string"


class IngestState(TypedDict, total=False):
    file_path: str
    raw_text: str
    filename: str
    doc_name: str
    source: str
    chunk_size: int
    chunk_overlap: int
    masked_text: str
    resolved_filename: str
    chunks: list[str]
    doc_id: str
    chunks_indexed: int


def _read_path(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        from pypdf import PdfReader

        return "\n".join((page.extract_text() or "") for page in PdfReader(str(path)).pages)
    if suffix == ".docx":
        import docx

        return "\n".join(p.text for p in docx.Document(str(path)).paragraphs)
    return path.read_text(encoding="utf-8")


def build_ingest_graph(pool: asyncpg.Pool, settings: Settings | None = None) -> Any:
    """Compila o grafo de ingestao (mascara PII, segmenta e indexa no pgvector)."""
    cfg = settings or Settings()

    async def read_file(state: IngestState) -> dict[str, Any]:
        text = state.get("raw_text")
        update: dict[str, Any] = {}
        if text is None and state.get("file_path"):
            path = Path(state["file_path"])
            text = await asyncio.to_thread(_read_path, path)
            update["filename"] = state.get("filename") or path.name
        if not isinstance(text, str) or not text.strip():
            raise ValueError(_EMPTY_TEXT_MSG)
        update["raw_text"] = text
        return update

    async def mask_node(state: IngestState) -> dict[str, Any]:
        return {
            "masked_text": mask_personal_data(state["raw_text"]),
            "resolved_filename": resolve_doc_alias(
                state.get("filename", ""), state.get("doc_name", "")
            ),
        }

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
        vectors = [await get_embedding(chunk, cfg) for chunk in chunks]
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
                    (doc_id, chunk, i, _to_pgvector_literal(vec), cfg.EMBEDDING_MODEL)
                    for i, (chunk, vec) in enumerate(zip(chunks, vectors, strict=True))
                ],
            )
        return {"doc_id": str(doc_id), "chunks_indexed": len(chunks)}

    builder = StateGraph(IngestState)
    builder.add_node("read_file", read_file)
    builder.add_node("mask_personal_data", mask_node)
    builder.add_node("split_text", split_node)
    builder.add_node("index_chunks", index_node)
    builder.add_edge(START, "read_file")
    builder.add_edge("read_file", "mask_personal_data")
    builder.add_edge("mask_personal_data", "split_text")
    builder.add_edge("split_text", "index_chunks")
    builder.add_edge("index_chunks", END)
    return builder.compile()

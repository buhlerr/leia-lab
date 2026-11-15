"""Hybrid retrieval: dense cosine (pgvector/HNSW) + sparse full-text, fused by RRF.

Reciprocal Rank Fusion (RRF) combines two independently ranked candidate lists
without requiring score normalization:

    score(doc) = sum_over_lists( 1 / (rrf_k + rank(doc)) )

``rrf_k`` (default 60) damps the influence of the very top ranks, which makes
fusion robust across heterogeneous retrievers.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import asyncpg

from src.rag.embeddings import EMBEDDING_DIM

DEFAULT_RRF_K = 60
# Number of candidates each branch contributes before fusion.
CANDIDATE_MULTIPLIER = 4
MIN_CANDIDATES = 20

# ``$2::text::vector`` keeps the parameter typed as text on the wire so that we
# do not need to register a pgvector codec on the asyncpg pool; PostgreSQL does
# the text -> vector conversion server-side.
HYBRID_SEARCH_SQL = """
WITH dense AS (
    SELECT
        c.id AS chunk_id,
        ROW_NUMBER() OVER (ORDER BY c.embedding <=> $2::text::vector) AS rank_pos
    FROM kb_chunks c
    WHERE c.embedding IS NOT NULL AND c.embedding_model = $6
    ORDER BY c.embedding <=> $2::text::vector
    LIMIT $3
),
sparse AS (
    SELECT
        c.id AS chunk_id,
        ROW_NUMBER() OVER (
            ORDER BY ts_rank_cd(c.tsv_content, websearch_to_tsquery('portuguese', $1)) DESC
        ) AS rank_pos
    FROM kb_chunks c
    WHERE c.tsv_content @@ websearch_to_tsquery('portuguese', $1)
    ORDER BY ts_rank_cd(c.tsv_content, websearch_to_tsquery('portuguese', $1)) DESC
    LIMIT $3
),
fused AS (
    SELECT chunk_id, SUM(1.0::float8 / ($4::float8 + rank_pos)) AS score
    FROM (
        SELECT chunk_id, rank_pos FROM dense
        UNION ALL
        SELECT chunk_id, rank_pos FROM sparse
    ) AS candidates
    GROUP BY chunk_id
)
SELECT
    c.id::text AS id,
    c.doc_id::text AS doc_id,
    d.title AS title,
    c.content AS content,
    f.score AS score
FROM fused f
JOIN kb_chunks c ON c.id = f.chunk_id
LEFT JOIN kb_docs d ON d.id = c.doc_id
ORDER BY f.score DESC, c.id
LIMIT $5
"""


def compute_rrf_scores(
    dense_ranks: Mapping[str, int],
    sparse_ranks: Mapping[str, int],
    rrf_k: int = DEFAULT_RRF_K,
) -> list[tuple[str, float]]:
    """Fuse two ``{doc_id: rank}`` mappings into a descending ``(doc_id, score)`` list.

    Ranks are 1-based. Documents present in only one list are still scored.
    Ties are broken by ``doc_id`` so the ordering is deterministic.
    """
    if rrf_k < 0:
        raise ValueError("rrf_k must be non-negative")

    scores: dict[str, float] = {}
    for ranks in (dense_ranks, sparse_ranks):
        for doc_id, rank in ranks.items():
            if rank < 1:
                raise ValueError(f"rank for {doc_id!r} must be >= 1, got {rank}")
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (rrf_k + rank)

    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))


def _to_pgvector_literal(vector: list[float]) -> str:
    """Serialize a float list into pgvector's text format, e.g. ``[0.1,0.2]``."""
    return "[" + ",".join(repr(float(value)) for value in vector) + "]"


async def hybrid_search_rrf(
    pool: asyncpg.Pool,
    query_text: str,
    query_vector: list[float],
    embedding_model: str,
    top_k: int = 5,
    rrf_k: int = DEFAULT_RRF_K,
) -> list[dict[str, Any]]:
    """Run dense + sparse retrieval in Postgres and return RRF-fused chunks.

    ``embedding_model`` must be the model that produced ``query_vector``
    (``EmbeddingResult.model``); the dense branch only ranks chunks stored with
    that same model, so real and offline vectors are never compared.

    Each returned dict has ``id``, ``doc_id``, ``title``, ``content`` and
    ``score`` keys, ordered by descending ``score``.
    """
    if len(query_vector) != EMBEDDING_DIM:
        raise ValueError(
            f"query_vector must have {EMBEDDING_DIM} dimensions, got {len(query_vector)}"
        )
    if top_k < 1:
        raise ValueError("top_k must be >= 1")
    if rrf_k < 0:
        raise ValueError("rrf_k must be non-negative")

    candidate_limit = max(top_k * CANDIDATE_MULTIPLIER, MIN_CANDIDATES)

    rows = await pool.fetch(
        HYBRID_SEARCH_SQL,
        query_text,
        _to_pgvector_literal(query_vector),
        candidate_limit,
        float(rrf_k),
        top_k,
        embedding_model,
    )

    results = [
        {
            "id": row["id"],
            "doc_id": row["doc_id"],
            "title": row["title"],
            "content": row["content"],
            "score": float(row["score"]),
        }
        for row in rows
    ]
    results.sort(key=lambda item: (-item["score"], item["id"]))
    return results

"""RAG layer: embeddings and hybrid (dense + sparse) retrieval."""

from src.rag.embeddings import EMBEDDING_DIM, OFFLINE_EMBEDDING_MODEL, embed_text, get_embedding
from src.rag.hybrid_search import compute_rrf_scores, hybrid_search_rrf

__all__ = [
    "EMBEDDING_DIM",
    "OFFLINE_EMBEDDING_MODEL",
    "compute_rrf_scores",
    "embed_text",
    "get_embedding",
    "hybrid_search_rrf",
]

"""RAG layer: embeddings and hybrid (dense + sparse) retrieval."""

from src.rag.embeddings import EMBEDDING_DIM, get_embedding
from src.rag.hybrid_search import compute_rrf_scores, hybrid_search_rrf

__all__ = ["EMBEDDING_DIM", "compute_rrf_scores", "get_embedding", "hybrid_search_rrf"]

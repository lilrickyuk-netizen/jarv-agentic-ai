"""
JARV Backend - Memory System

The memory store itself is ``app.core.jarv_memory.memory_service``. This package
holds the parts it is built from: embeddings, the 23-category taxonomy, and the
task-scoped recall context used to put memory into agent prompts.
"""
from app.core.memory.embeddings import EmbeddingService, cosine_similarity, get_embedding, local_hash_embedding
from app.core.memory.taxonomy import MEMORY_CATEGORIES, categorise

__all__ = [
    "EmbeddingService",
    "MEMORY_CATEGORIES",
    "categorise",
    "cosine_similarity",
    "get_embedding",
    "local_hash_embedding",
]

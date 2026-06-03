"""
JARV Backend - Embedding Service

Generates vector embeddings for semantic memory search using pgvector.
"""
from typing import List, Optional, Dict, Any
import logging
import os
import httpx
from functools import lru_cache

logger = logging.getLogger(__name__)


class EmbeddingService:
    """
    Service for generating text embeddings for semantic search.

    Supports multiple embedding providers:
    - OpenAI (text-embedding-3-small, text-embedding-3-large)
    - Local models (via Ollama or sentence-transformers)
    - Custom embedding endpoints
    """

    def __init__(
        self,
        provider: str = "openai",
        model: str = "text-embedding-3-small",
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
        dimensions: int = 1536,
    ):
        """
        Initialize embedding service.

        Args:
            provider: Embedding provider (openai, ollama, local, custom)
            model: Model name
            api_key: API key for provider
            api_base: Base URL for API
            dimensions: Embedding dimensions
        """
        self.provider = provider
        self.model = model
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.api_base = api_base or "https://api.openai.com/v1"
        self.dimensions = dimensions
        self.logger = logging.getLogger("memory.embeddings")

        # Initialize HTTP client
        self.client = httpx.AsyncClient(timeout=30.0)

    async def generate_embedding(
        self,
        text: str,
        user_id: Optional[str] = None,
    ) -> List[float]:
        """
        Generate embedding vector for text.

        Args:
            text: Text to embed
            user_id: Optional user ID for tracking

        Returns:
            Embedding vector as list of floats

        Raises:
            Exception: If embedding generation fails
        """
        if not text or not text.strip():
            raise ValueError("Text cannot be empty")

        try:
            if self.provider == "openai":
                return await self._generate_openai_embedding(text, user_id)
            elif self.provider == "ollama":
                return await self._generate_ollama_embedding(text)
            elif self.provider == "local":
                return await self._generate_local_embedding(text)
            elif self.provider == "custom":
                return await self._generate_custom_embedding(text)
            else:
                raise ValueError(f"Unknown embedding provider: {self.provider}")

        except Exception as e:
            self.logger.error(
                f"Failed to generate embedding: {e}",
                extra={"text_length": len(text), "provider": self.provider},
                exc_info=True
            )
            raise

    async def _generate_openai_embedding(
        self,
        text: str,
        user_id: Optional[str] = None,
    ) -> List[float]:
        """Generate embedding using OpenAI API"""
        if not self.api_key:
            raise ValueError("OpenAI API key not configured")

        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }

            payload = {
                "input": text,
                "model": self.model,
            }

            # Add dimensions parameter for text-embedding-3 models
            if "text-embedding-3" in self.model:
                payload["dimensions"] = self.dimensions

            if user_id:
                payload["user"] = user_id

            response = await self.client.post(
                f"{self.api_base}/embeddings",
                headers=headers,
                json=payload,
            )

            response.raise_for_status()
            data = response.json()

            embedding = data["data"][0]["embedding"]

            self.logger.debug(
                f"Generated OpenAI embedding",
                extra={
                    "model": self.model,
                    "dimensions": len(embedding),
                    "usage": data.get("usage", {}),
                }
            )

            return embedding

        except httpx.HTTPError as e:
            self.logger.error(
                f"OpenAI API error: {e}",
                extra={"status_code": getattr(e.response, 'status_code', None)},
                exc_info=True
            )
            raise Exception(f"Failed to generate OpenAI embedding: {str(e)}")

    async def _generate_ollama_embedding(self, text: str) -> List[float]:
        """Generate embedding using Ollama local API"""
        try:
            ollama_base = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

            response = await self.client.post(
                f"{ollama_base}/api/embeddings",
                json={
                    "model": self.model,
                    "prompt": text,
                },
            )

            response.raise_for_status()
            data = response.json()

            embedding = data["embedding"]

            self.logger.debug(
                f"Generated Ollama embedding",
                extra={"model": self.model, "dimensions": len(embedding)}
            )

            return embedding

        except Exception as e:
            self.logger.error(f"Ollama API error: {e}", exc_info=True)
            raise Exception(f"Failed to generate Ollama embedding: {str(e)}")

    async def _generate_local_embedding(self, text: str) -> List[float]:
        """Generate embedding using local sentence-transformers"""
        try:
            # In production: Use sentence-transformers library
            # from sentence_transformers import SentenceTransformer
            # model = SentenceTransformer(self.model)
            # embedding = model.encode(text).tolist()
            # return embedding

            self.logger.warning("Local embeddings not implemented, using placeholder")
            # Return placeholder vector
            return [0.0] * self.dimensions

        except Exception as e:
            self.logger.error(f"Local embedding error: {e}", exc_info=True)
            raise Exception(f"Failed to generate local embedding: {str(e)}")

    async def _generate_custom_embedding(self, text: str) -> List[float]:
        """Generate embedding using custom endpoint"""
        try:
            custom_endpoint = os.getenv("CUSTOM_EMBEDDING_ENDPOINT")
            if not custom_endpoint:
                raise ValueError("CUSTOM_EMBEDDING_ENDPOINT not configured")

            response = await self.client.post(
                custom_endpoint,
                json={"text": text, "model": self.model},
            )

            response.raise_for_status()
            data = response.json()

            return data["embedding"]

        except Exception as e:
            self.logger.error(f"Custom embedding error: {e}", exc_info=True)
            raise Exception(f"Failed to generate custom embedding: {str(e)}")

    async def batch_generate_embeddings(
        self,
        texts: List[str],
        user_id: Optional[str] = None,
    ) -> List[List[float]]:
        """
        Generate embeddings for multiple texts in batch.

        Args:
            texts: List of texts to embed
            user_id: Optional user ID

        Returns:
            List of embedding vectors
        """
        if not texts:
            return []

        try:
            if self.provider == "openai":
                return await self._batch_generate_openai_embeddings(texts, user_id)
            else:
                # Fallback to individual generation for other providers
                embeddings = []
                for text in texts:
                    embedding = await self.generate_embedding(text, user_id)
                    embeddings.append(embedding)
                return embeddings

        except Exception as e:
            self.logger.error(
                f"Failed to generate batch embeddings: {e}",
                extra={"count": len(texts)},
                exc_info=True
            )
            raise

    async def _batch_generate_openai_embeddings(
        self,
        texts: List[str],
        user_id: Optional[str] = None,
    ) -> List[List[float]]:
        """Generate embeddings in batch using OpenAI API"""
        if not self.api_key:
            raise ValueError("OpenAI API key not configured")

        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }

            payload = {
                "input": texts,
                "model": self.model,
            }

            if "text-embedding-3" in self.model:
                payload["dimensions"] = self.dimensions

            if user_id:
                payload["user"] = user_id

            response = await self.client.post(
                f"{self.api_base}/embeddings",
                headers=headers,
                json=payload,
            )

            response.raise_for_status()
            data = response.json()

            embeddings = [item["embedding"] for item in data["data"]]

            self.logger.debug(
                f"Generated {len(embeddings)} OpenAI embeddings",
                extra={
                    "model": self.model,
                    "count": len(embeddings),
                    "usage": data.get("usage", {}),
                }
            )

            return embeddings

        except Exception as e:
            self.logger.error(f"Batch OpenAI embedding error: {e}", exc_info=True)
            raise Exception(f"Failed to generate batch embeddings: {str(e)}")

    async def close(self):
        """Close HTTP client"""
        await self.client.aclose()

    def __del__(self):
        """Cleanup on deletion"""
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(self.close())
        except:
            pass


# Global embedding service instance
_embedding_service: Optional[EmbeddingService] = None


def get_embedding_service() -> EmbeddingService:
    """
    Get global embedding service instance.

    Returns:
        EmbeddingService instance
    """
    global _embedding_service

    if _embedding_service is None:
        provider = os.getenv("EMBEDDING_PROVIDER", "openai")
        model = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
        dimensions = int(os.getenv("EMBEDDING_DIMENSIONS", "1536"))

        _embedding_service = EmbeddingService(
            provider=provider,
            model=model,
            dimensions=dimensions,
        )

    return _embedding_service


async def get_embedding(text: str, user_id: Optional[str] = None) -> List[float]:
    """
    Global function to generate embedding.

    Args:
        text: Text to embed
        user_id: Optional user ID

    Returns:
        Embedding vector
    """
    service = get_embedding_service()
    return await service.generate_embedding(text, user_id)

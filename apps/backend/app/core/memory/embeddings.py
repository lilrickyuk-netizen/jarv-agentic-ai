"""
JARV Backend - Embedding Service

Generates vector embeddings for semantic memory search.

Providers:
- ``local``  : JARV's built-in feature-hashing embedder (``jarv-hash-v1``). It
               runs offline with no model download or API key, is deterministic
               across processes, and captures word, phrase, and sub-word overlap.
               It is a lexical-semantic embedding, not a neural one: it ranks
               "exponential back-off for retries" close to "retry with backoff",
               but it does not know that "car" and "automobile" are synonyms.
- ``openai`` : OpenAI embeddings API (requires OPENAI_API_KEY).
- ``ollama`` : a local Ollama embedding model (OLLAMA_BASE_URL).
- ``custom`` : any HTTP endpoint returning {"embedding": [...]}
               (CUSTOM_EMBEDDING_ENDPOINT).
- ``auto``   : (default) ``openai`` when OPENAI_API_KEY is set, else ``local``.

Every vector is returned together with a model identifier. Vectors from
different models live in different spaces and must never be compared with each
other, so the memory store records the identifier per row and only ranks rows
whose identifier matches the query's.
"""
from __future__ import annotations

import hashlib
import logging
import math
import os
import re
import unicodedata
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import httpx

logger = logging.getLogger(__name__)

DEFAULT_DIMENSIONS = 1536
LOCAL_MODEL_NAME = "jarv-hash-v1"

_STOPWORDS = frozenset(
    "a an and are as at be been but by can could did do does for from had has have "
    "he her his how i if in into is it its just me my no not of on or our out she so "
    "than that the their them then there these they this to too up us was we were "
    "what when where which who why will with would you your".split()
)
_SUFFIXES = ("ations", "ation", "ingly", "ings", "ing", "edly", "ed", "ies", "es", "ly", "s")
_WORD_RE = re.compile(r"[a-z0-9]+")


def _normalise(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text.lower()


def _stem(word: str) -> str:
    if len(word) <= 4 or word.isdigit():
        return word
    for suffix in _SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            stem = word[: -len(suffix)]
            if suffix == "ies":
                stem += "y"
            return stem
    return word


def _features(text: str) -> Dict[str, float]:
    """Weighted lexical features: stems, adjacent-stem phrases, sub-word trigrams."""
    words = [w for w in _WORD_RE.findall(_normalise(text)) if len(w) > 1]
    stems = [_stem(w) for w in words if w not in _STOPWORDS]
    counts: Dict[str, float] = {}

    def bump(key: str, weight: float) -> None:
        counts[key] = counts.get(key, 0.0) + weight

    for stem in stems:
        bump(f"w:{stem}", 1.0)
        padded = f"^{stem}$"
        if len(padded) >= 5:
            for i in range(len(padded) - 2):
                bump(f"c:{padded[i:i + 3]}", 0.25)
    for left, right in zip(stems, stems[1:]):
        bump(f"b:{left}_{right}", 0.6)
    # Sub-linear term frequency so one repeated word cannot dominate the vector.
    return {key: 1.0 + math.log(value) if value > 1.0 else value for key, value in counts.items()}


def local_hash_embedding(text: str, dimensions: int = DEFAULT_DIMENSIONS) -> List[float]:
    """Deterministic signed feature-hashing embedding, L2-normalised.

    Empty or stopword-only text yields the zero vector, which compares as
    "no similarity" with everything rather than matching at random.
    """
    if dimensions <= 0:
        raise ValueError("dimensions must be positive")
    vector = [0.0] * dimensions
    for feature, weight in _features(text or "").items():
        digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
        value = int.from_bytes(digest, "big")
        index = value % dimensions
        sign = 1.0 if (value >> 63) & 1 else -1.0
        vector[index] += sign * weight
    norm = math.sqrt(sum(v * v for v in vector))
    if norm == 0.0:
        return vector
    return [v / norm for v in vector]


def cosine_similarity(left: Optional[Sequence[float]], right: Optional[Sequence[float]]) -> float:
    """Cosine similarity of two vectors (lists, tuples, or numpy arrays).

    Returns 0.0 when either vector is missing, empty, zero, or the dimensions
    differ, so callers can treat the result as "no semantic evidence".
    """
    if left is None or right is None:
        return 0.0
    a = [float(x) for x in left]
    b = [float(x) for x in right]
    if not a or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


class EmbeddingService:
    """Generates embeddings and reports which model produced them."""

    def __init__(
        self,
        provider: str = "auto",
        model: str = "text-embedding-3-small",
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
        dimensions: int = DEFAULT_DIMENSIONS,
    ):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY") or None
        requested = (provider or "auto").lower()
        if requested == "auto":
            requested = "openai" if self.api_key else "local"
        self.provider = requested
        self.model = LOCAL_MODEL_NAME if requested == "local" else model
        self.api_base = (api_base or os.getenv("OPENAI_API_BASE") or "https://api.openai.com/v1").rstrip("/")
        self.dimensions = dimensions
        self.logger = logging.getLogger("memory.embeddings")

    @property
    def model_id(self) -> str:
        """Identifier stored beside every vector; vectors only compare within one id."""
        return self._model_id(self.provider, self.model)

    def _model_id(self, provider: str, model: str) -> str:
        return f"{provider}:{model}:{self.dimensions}"

    @property
    def local_model_id(self) -> str:
        return self._model_id("local", LOCAL_MODEL_NAME)

    async def embed(self, text: str, user_id: Optional[str] = None) -> Tuple[List[float], str]:
        """Return ``(vector, model_id)``.

        A remote provider failure falls back to the local embedder and reports
        the local model id, so the stored row is still searchable and is never
        compared against vectors from the remote model.
        """
        if not text or not text.strip():
            raise ValueError("Text cannot be empty")
        if self.provider == "local":
            return local_hash_embedding(text, self.dimensions), self.local_model_id
        try:
            if self.provider == "openai":
                vector = await self._generate_openai_embedding(text, user_id)
            elif self.provider == "ollama":
                vector = await self._generate_ollama_embedding(text)
            elif self.provider == "custom":
                vector = await self._generate_custom_embedding(text)
            else:
                raise ValueError(f"Unknown embedding provider: {self.provider}")
            if len(vector) != self.dimensions:
                raise ValueError(
                    f"{self.provider} returned {len(vector)} dimensions; "
                    f"the memory column stores {self.dimensions}"
                )
            return [float(x) for x in vector], self.model_id
        except Exception as exc:  # noqa: BLE001 - logged, then honest local fallback
            self.logger.warning(
                "Remote embedding failed; using local embedder for this record",
                extra={"provider": self.provider, "error": str(exc)[:300]},
            )
            return local_hash_embedding(text, self.dimensions), self.local_model_id

    async def generate_embedding(self, text: str, user_id: Optional[str] = None) -> List[float]:
        """Vector only (kept for existing callers)."""
        vector, _ = await self.embed(text, user_id)
        return vector

    async def batch_generate_embeddings(
        self, texts: Iterable[str], user_id: Optional[str] = None,
    ) -> List[List[float]]:
        return [await self.generate_embedding(text, user_id) for text in texts]

    async def _post(self, url: str, **kwargs: Any) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, **kwargs)
            response.raise_for_status()
            return response.json()

    async def _generate_openai_embedding(self, text: str, user_id: Optional[str]) -> List[float]:
        if not self.api_key:
            raise ValueError("OpenAI API key not configured")
        payload: Dict[str, Any] = {"input": text, "model": self.model}
        if "text-embedding-3" in self.model:
            payload["dimensions"] = self.dimensions
        if user_id:
            payload["user"] = user_id
        data = await self._post(
            f"{self.api_base}/embeddings",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json=payload,
        )
        return data["data"][0]["embedding"]

    async def _generate_ollama_embedding(self, text: str) -> List[float]:
        base = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
        data = await self._post(f"{base}/api/embeddings", json={"model": self.model, "prompt": text})
        return data["embedding"]

    async def _generate_custom_embedding(self, text: str) -> List[float]:
        endpoint = os.getenv("CUSTOM_EMBEDDING_ENDPOINT")
        if not endpoint:
            raise ValueError("CUSTOM_EMBEDDING_ENDPOINT not configured")
        data = await self._post(endpoint, json={"text": text, "model": self.model})
        return data["embedding"]


_embedding_service: Optional[EmbeddingService] = None


def get_embedding_service() -> EmbeddingService:
    """Process-wide embedding service configured from the environment."""
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService(
            provider=os.getenv("EMBEDDING_PROVIDER", "auto"),
            model=os.getenv("EMBEDDING_MODEL", "text-embedding-3-small"),
            dimensions=int(os.getenv("EMBEDDING_DIMENSIONS", str(DEFAULT_DIMENSIONS))),
        )
    return _embedding_service


def reset_embedding_service() -> None:
    """Drop the cached service so changed environment settings take effect."""
    global _embedding_service
    _embedding_service = None


async def get_embedding(text: str, user_id: Optional[str] = None) -> List[float]:
    return await get_embedding_service().generate_embedding(text, user_id)

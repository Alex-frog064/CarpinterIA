"""Embedding generation for a RAG system using Ollama's embedding endpoint.

Provides a fallback to hash-based random projection embeddings when Ollama
is not available.
"""

import hashlib
import logging
from typing import Optional

import httpx
import numpy as np

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Generates text embeddings via Ollama, with a numpy fallback."""

    def __init__(
        self,
        ollama_base_url: str = "http://localhost:11434",
        embedding_model: str = "nomic-embed-text",
        timeout: float = 30.0,
        dimension: int = 768,
    ):
        self.ollama_base_url = ollama_base_url.rstrip("/")
        self.embedding_model = embedding_model
        self.timeout = timeout
        self._dimension = dimension
        self._fallback: Optional[_FallbackEmbedder] = None

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def get_embedding_dimension(self) -> int:
        """Return the embedding dimension.

        If Ollama is reachable a test call is made to discover the real
        dimension; otherwise the pre-configured value (or fallback) is used.
        """
        try:
            resp = httpx.get(
                f"{self.ollama_base_url}/api/embed",
                json={"model": self.embedding_model, "input": "test"},
                timeout=self.timeout,
            )
            resp.raise_for_status()
            embeddings = resp.json().get("embeddings", [])
            if embeddings:
                self._dimension = len(embeddings[0])
                return self._dimension
        except Exception:
            logger.debug("Could not probe Ollama for dimension, using fallback")
        return self._fallback_dimension()

    # ------------------------------------------------------------------
    # Core embedding methods
    # ------------------------------------------------------------------

    async def embed_text(self, text: str) -> list[float]:
        """Embed a single text string."""
        results = await self.embed_texts([text])
        if results:
            return results[0]
        return []

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of text strings."""
        if not texts:
            return []

        try:
            return await self._ollama_embed(texts)
        except Exception as exc:
            logger.warning(
                "Ollama embedding failed (%s), falling back to local embedder",
                exc,
            )
            return self._fallback_embed(texts)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _ollama_embed(self, texts: list[str]) -> list[list[float]]:
        """Call the Ollama /api/embed endpoint."""
        url = f"{self.ollama_base_url}/api/embed"
        payload = {"model": self.embedding_model, "input": texts}

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()

        data = resp.json()
        embeddings: list[list[float]] = data.get("embeddings", [])
        if not embeddings:
            raise ValueError("Ollama returned empty embeddings")
        return embeddings

    def _fallback_dimension(self) -> int:
        if self._fallback is None:
            self._fallback = _FallbackEmbedder(self._dimension)
        return self._fallback.dimension

    def _fallback_embed(self, texts: list[str]) -> list[list[float]]:
        """Use a deterministic hash-based random projection as fallback."""
        if self._fallback is None:
            self._fallback = _FallbackEmbedder(self._dimension)
        return [self._fallback.embed(t) for t in texts]


class _FallbackEmbedder:
    """Deterministic TF-IDF-like embeddings via random projection."""

    VOCAB_SIZE = 20_000

    def __init__(self, dimension: int = 768):
        self.dimension = dimension
        rng = np.random.RandomState(42)
        self._projection = rng.randn(self.VOCAB_SIZE, dimension).astype(np.float32)
        # L2-normalise columns so dot-product is cosine-like
        norms = np.linalg.norm(self._projection, axis=1, keepdims=True)
        self._projection /= norms + 1e-9

    def embed(self, text: str) -> list[float]:
        vec = np.zeros(self.dimension, dtype=np.float32)
        tokens = text.lower().split()
        if not tokens:
            return vec.tolist()
        counts: dict[int, int] = {}
        for tok in tokens:
            idx = self._token_index(tok)
            counts[idx] = counts.get(idx, 0) + 1
        for idx, count in counts.items():
            vec += self._projection[idx] * float(count)
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec /= norm
        return vec.tolist()

    @staticmethod
    def _token_index(token: str) -> int:
        h = int(hashlib.md5(token.encode()).hexdigest(), 16)
        return h % _FallbackEmbedder.VOCAB_SIZE

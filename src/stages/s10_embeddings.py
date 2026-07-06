"""Stage 10 — Embeddings.

Jina v3/v4 as primary (genuinely permanent free tier), Gemini embeddings
as overflow when Jina's RPM is exhausted.

Sparse vector support: when using Jina, we request both dense AND sparse
embeddings in a single API call (return_sparse=true). This powers true
hybrid dense+sparse retrieval in Stage 11, replacing the BM25-lite heuristic.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import httpx

from src.core.config import settings
from src.core.rate_limiter import RateLimiter
from src.models.schemas import Chunk

logger = logging.getLogger(__name__)

_JINA_EMBED_URL = "https://api.jina.ai/v1/embeddings"
_GEMINI_EMBED_URL = "https://generativelanguage.googleapis.com/v1beta/models"


@dataclass
class SparseVector:
    """A sparse embedding represented as parallel index/value arrays.

    Qdrant accepts sparse vectors in this format for its named sparse
    vector collections.
    """
    indices: list[int] = field(default_factory=list)
    values: list[float] = field(default_factory=list)

    def is_empty(self) -> bool:
        return len(self.indices) == 0


def _empty_sparse_vectors(n: int) -> list[SparseVector]:
    """Return a list of n empty SparseVector objects (fallback when sparse is unavailable)."""
    return [SparseVector() for _ in range(n)]


class EmbeddingService:
    """Embeds chunks using Jina (primary) with Gemini overflow.

    Returns both dense and sparse vectors. Sparse vectors are populated
    by Jina (return_sparse=true). Gemini fallback returns empty sparse vectors
    and the retrieval layer gracefully degrades to dense-only search.
    """

    def __init__(self, rate_limiter: RateLimiter | None = None) -> None:
        self._rate_limiter = rate_limiter or RateLimiter()
        self._http: httpx.AsyncClient | None = None

    def _get_http(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=60.0)
        return self._http

    async def embed_chunks(
        self, chunks: list[Chunk]
    ) -> tuple[list[list[float]], list[SparseVector]]:
        """Embed a list of chunks. Returns (dense_vectors, sparse_vectors)."""
        texts = [c.content for c in chunks]
        return await self.embed_texts(texts)

    async def embed_texts(
        self, texts: list[str]
    ) -> tuple[list[list[float]], list[SparseVector]]:
        """Embed a list of texts. Returns (dense_vectors, sparse_vectors).

        Sparse vectors will be empty if Gemini fallback is used.
        """
        if not texts:
            return [], []

        # Try Jina first (returns both dense + sparse)
        if settings.jina_api_key:
            try:
                return await self._embed_jina(texts)
            except Exception as e:
                logger.warning("Jina embedding failed: %s — falling back to Gemini", e)

        # Fallback to Gemini (dense only, empty sparse)
        if settings.gemini_api_key:
            try:
                dense = await self._embed_gemini(texts)
                sparse = _empty_sparse_vectors(len(texts))
                return dense, sparse
            except Exception as e:
                logger.error("Gemini embedding also failed: %s", e)
                raise

        raise RuntimeError("No embedding provider available — set JINA_API_KEY or GEMINI_API_KEY")

    async def embed_query(self, query: str) -> tuple[list[float], SparseVector]:
        """Embed a single query string. Returns (dense_vector, sparse_vector)."""
        dense_list, sparse_list = await self.embed_texts([query])
        return dense_list[0], sparse_list[0]

    async def embed_queries(
        self, queries: list[str]
    ) -> list[list[float]]:
        """Embed multiple queries (dense only). Used for batch retrieval tests."""
        dense_list, _ = await self.embed_texts(queries)
        return dense_list

    async def _embed_jina(
        self, texts: list[str]
    ) -> tuple[list[list[float]], list[SparseVector]]:
        """Embed via Jina Embeddings API, requesting both dense and sparse."""
        await self._rate_limiter.acquire("jina")
        http = self._get_http()

        all_dense: list[list[float]] = []
        all_sparse: list[SparseVector] = []
        batch_size = 64  # Increased for faster ingestion

        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]

            response = await http.post(
                _JINA_EMBED_URL,
                headers={
                    "Authorization": f"Bearer {settings.jina_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "jina-embeddings-v3",
                    "input": batch,
                    "task": "retrieval.passage",
                    "return_sparse": True,  # Request sparse vectors alongside dense
                },
            )
            response.raise_for_status()
            data = response.json()

            # Sort by index to preserve order
            embeddings = sorted(data["data"], key=lambda x: x["index"])

            for emb in embeddings:
                all_dense.append(emb["embedding"])

                # Parse sparse embedding — Jina returns {"index": int, "value": float} pairs
                sparse_raw = emb.get("sparse_embedding")
                if sparse_raw:
                    indices = [int(k) for k in sparse_raw.keys()]
                    values = [float(v) for v in sparse_raw.values()]
                    all_sparse.append(SparseVector(indices=indices, values=values))
                else:
                    all_sparse.append(SparseVector())

            if i + batch_size < len(texts):
                await self._rate_limiter.acquire("jina")

        return all_dense, all_sparse

    async def _embed_gemini(self, texts: list[str]) -> list[list[float]]:
        """Embed via Gemini Embedding API (dense only)."""
        await self._rate_limiter.acquire("gemini")
        http = self._get_http()

        all_vectors: list[list[float]] = []
        batch_size = 100  # Gemini supports batch embedding

        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]

            url = f"{_GEMINI_EMBED_URL}/text-embedding-004:batchEmbedContents?key={settings.gemini_api_key}"
            requests_body = [
                {"model": "models/text-embedding-004", "content": {"parts": [{"text": t}]}}
                for t in batch
            ]

            response = await http.post(url, json={"requests": requests_body})
            response.raise_for_status()
            data = response.json()

            for emb in data.get("embeddings", []):
                all_vectors.append(emb["values"])

            if i + batch_size < len(texts):
                await self._rate_limiter.acquire("gemini")

        return all_vectors

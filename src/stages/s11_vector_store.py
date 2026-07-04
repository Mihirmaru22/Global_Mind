"""Stage 11 — Vector Store.

Qdrant Cloud free cluster as primary (1GB RAM, no query metering).
Falls back to a local in-memory store for development/testing.

Hybrid search: dense cosine similarity + Jina sparse vectors fused via
Reciprocal Rank Fusion (RRF), replacing the previous BM25-lite heuristic.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol, runtime_checkable

from src.core.config import settings
from src.models.schemas import Chunk, RetrievedChunk
from src.stages.s10_embeddings import SparseVector

logger = logging.getLogger(__name__)


@runtime_checkable
class VectorStore(Protocol):
    """Protocol for vector store implementations — swappable."""

    async def upsert(
        self,
        chunks: list[Chunk],
        vectors: list[list[float]],
        sparse_vectors: list[SparseVector] | None = None,
    ) -> None: ...

    async def search_dense(
        self,
        query_vector: list[float],
        top_k: int = 30,
        filters: dict[str, Any] | None = None,
    ) -> list[RetrievedChunk]: ...

    async def search_hybrid(
        self,
        query_vector: list[float],
        sparse_vector: SparseVector | None = None,
        query_text: str = "",
        top_k: int = 30,
        filters: dict[str, Any] | None = None,
    ) -> list[RetrievedChunk]: ...

    async def delete_document(self, document_id: str) -> None: ...
    async def get_stats(self) -> dict[str, Any]: ...


class QdrantStore:
    """Qdrant Cloud vector store with true hybrid dense+sparse search."""

    def __init__(
        self,
        collection_name: str = "globle_mind",
        vector_size: int = 1024,
    ) -> None:
        self._collection_name = collection_name
        self._vector_size = vector_size
        self._client: Any = None  # qdrant_client.AsyncQdrantClient
        self._has_sparse: bool = False  # Set True once sparse collection is confirmed

    async def _get_client(self) -> Any:
        if self._client is None:
            from qdrant_client import AsyncQdrantClient

            if settings.qdrant_url and settings.qdrant_api_key:
                self._client = AsyncQdrantClient(
                    url=settings.qdrant_url,
                    api_key=settings.qdrant_api_key,
                )
            else:
                # Local in-memory for dev/testing
                self._client = AsyncQdrantClient(location=":memory:")
                logger.info("Using in-memory Qdrant (no QDRANT_URL configured)")

            await self._ensure_collection()

        return self._client

    async def _ensure_collection(self) -> None:
        """Create collection with both dense and sparse vector support.

        If the collection already exists, check whether it already has
        the sparse vector config. If not (legacy collection), recreate it.
        """
        from qdrant_client.models import (
            Distance,
            SparseVectorParams,
            VectorParams,
        )

        client = self._client
        collections = await client.get_collections()
        existing_names = [c.name for c in collections.collections]

        if self._collection_name in existing_names:
            # Check if existing collection has sparse vector support
            info = await client.get_collection(self._collection_name)
            sparse_config = getattr(info.config, "sparse_vectors_config", None)
            if sparse_config and "text_sparse" in (sparse_config or {}):
                self._has_sparse = True
                logger.info(
                    "Collection '%s' already exists with sparse support",
                    self._collection_name,
                )
                return
            else:
                # Legacy collection without sparse — recreate it
                logger.warning(
                    "Collection '%s' exists but lacks sparse vectors — recreating with sparse support",
                    self._collection_name,
                )
                await client.delete_collection(self._collection_name)

        # Create fresh collection with dense + sparse support
        await client.create_collection(
            collection_name=self._collection_name,
            vectors_config=VectorParams(
                size=self._vector_size,
                distance=Distance.COSINE,
            ),
            sparse_vectors_config={
                "text_sparse": SparseVectorParams(),
            },
        )
        self._has_sparse = True
        logger.info(
            "Created Qdrant collection '%s' (vector_size=%d, sparse=True)",
            self._collection_name,
            self._vector_size,
        )

    async def upsert(
        self,
        chunks: list[Chunk],
        vectors: list[list[float]],
        sparse_vectors: list[SparseVector] | None = None,
    ) -> None:
        """Store chunks with their dense (and optionally sparse) embeddings."""
        import hashlib

        from qdrant_client.models import PointStruct

        client = await self._get_client()

        # Pad sparse_vectors if not provided or mismatched length
        if sparse_vectors is None or len(sparse_vectors) != len(chunks):
            sparse_vectors = [SparseVector() for _ in chunks]

        def _stable_id(chunk_id: str) -> int:
            """Stable positive integer ID from chunk_id string (63-bit to avoid Qdrant signed overflow)."""
            return int(hashlib.sha256(chunk_id.encode()).hexdigest(), 16) % (2**63)

        points = []
        for chunk, vector, sparse in zip(chunks, vectors, sparse_vectors):
            payload = {
                "chunk_id": chunk.chunk_id,
                "document_id": chunk.document_id,
                "content": chunk.content,
                "chunk_type": chunk.chunk_type.value,
                "page_number": chunk.page_number,
                "section_hierarchy": chunk.section_hierarchy,
                "parent_chunk_id": chunk.parent_chunk_id,
                "document_type": chunk.document_type.value,
                "source_file": chunk.source_file,
                "confidence": chunk.confidence,
                "token_count": chunk.token_count,
            }

            # Build the vectors dict — always include dense; add sparse if available
            vectors_dict: dict[str, Any] = {"": vector}  # unnamed = dense
            if self._has_sparse and not sparse.is_empty():
                from qdrant_client.models import SparseVector as QdrantSparseVector
                vectors_dict["text_sparse"] = QdrantSparseVector(
                    indices=sparse.indices,
                    values=sparse.values,
                )

            points.append(
                PointStruct(
                    id=_stable_id(chunk.chunk_id),
                    vector=vectors_dict,
                    payload=payload,
                )
            )

        # Batch upsert
        batch_size = 100
        for i in range(0, len(points), batch_size):
            batch = points[i : i + batch_size]
            await client.upsert(
                collection_name=self._collection_name,
                points=batch,
            )

        logger.info("Upserted %d chunks to Qdrant", len(points))

    async def search_dense(
        self,
        query_vector: list[float],
        top_k: int = 30,
        filters: dict[str, Any] | None = None,
    ) -> list[RetrievedChunk]:
        """Dense (semantic) vector search with optional metadata filtering."""
        client = await self._get_client()
        qdrant_filter = self._build_filter(filters) if filters else None

        response = await client.query_points(
            collection_name=self._collection_name,
            query=query_vector,
            limit=top_k,
            query_filter=qdrant_filter,
        )

        return [self._point_to_retrieved_chunk(r, "dense") for r in response.points]

    async def search_hybrid(
        self,
        query_vector: list[float],
        sparse_vector: SparseVector | None = None,
        query_text: str = "",
        top_k: int = 30,
        filters: dict[str, Any] | None = None,
    ) -> list[RetrievedChunk]:
        """True hybrid search: dense + sparse fused via Reciprocal Rank Fusion (RRF).

        Falls back to dense-only if sparse vector is empty (e.g., Gemini fallback).
        """
        qdrant_filter = self._build_filter(filters) if filters else None

        # If no sparse vector available, degrade gracefully to dense-only
        if sparse_vector is None or sparse_vector.is_empty() or not self._has_sparse:
            return await self.search_dense(query_vector, top_k=top_k, filters=filters)

        client = await self._get_client()

        try:
            from qdrant_client.models import (
                Fusion,
                FusionQuery,
                Prefetch,
                SparseVector as QdrantSparseVector,
            )

            response = await client.query_points(
                collection_name=self._collection_name,
                prefetch=[
                    # Dense search leg
                    Prefetch(
                        query=query_vector,
                        using="",  # default (unnamed) dense vector
                        limit=top_k * 2,
                        filter=qdrant_filter,
                    ),
                    # Sparse search leg
                    Prefetch(
                        query=QdrantSparseVector(
                            indices=sparse_vector.indices,
                            values=sparse_vector.values,
                        ),
                        using="text_sparse",
                        limit=top_k * 2,
                        filter=qdrant_filter,
                    ),
                ],
                query=FusionQuery(fusion=Fusion.RRF),
                limit=top_k,
            )

            return [self._point_to_retrieved_chunk(r, "hybrid_rrf") for r in response.points]

        except Exception as e:
            logger.warning("Hybrid RRF search failed: %s — falling back to dense", e)
            return await self.search_dense(query_vector, top_k=top_k, filters=filters)

    async def delete_document(self, document_id: str) -> None:
        """Delete all chunks belonging to a document."""
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        client = await self._get_client()

        await client.delete(
            collection_name=self._collection_name,
            points_selector=Filter(
                must=[
                    FieldCondition(
                        key="document_id",
                        match=MatchValue(value=document_id),
                    )
                ]
            ),
        )
        logger.info("Deleted document %s from Qdrant", document_id)

    async def get_stats(self) -> dict[str, Any]:
        """Return collection statistics."""
        client = await self._get_client()
        info = await client.get_collection(self._collection_name)
        return {
            "collection": self._collection_name,
            "points_count": info.points_count,
            "vectors_count": getattr(info, "vectors_count", getattr(info, "indexed_vectors_count", 0)),
            "has_sparse": self._has_sparse,
            "status": info.status.value,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_filter(filters: dict[str, Any]) -> Any:
        """Build a Qdrant Filter from a plain dict.

        Supported keys:
          document_type (str)  — exact match
          source_file (str)    — substring match
          page_number (int)    — minimum page number
          document_id (str)    — exact document match
          chunk_type (str)     — exact chunk type match
        """
        from qdrant_client.models import (
            FieldCondition,
            Filter,
            MatchText,
            MatchValue,
            Range,
        )

        conditions = []

        if "document_type" in filters:
            conditions.append(
                FieldCondition(key="document_type", match=MatchValue(value=filters["document_type"]))
            )
        if "document_id" in filters:
            conditions.append(
                FieldCondition(key="document_id", match=MatchValue(value=filters["document_id"]))
            )
        if "chunk_type" in filters:
            conditions.append(
                FieldCondition(key="chunk_type", match=MatchValue(value=filters["chunk_type"]))
            )
        if "source_file" in filters:
            conditions.append(
                FieldCondition(key="source_file", match=MatchText(text=filters["source_file"]))
            )
        if "page_number" in filters:
            conditions.append(
                FieldCondition(key="page_number", range=Range(gte=filters["page_number"]))
            )

        return Filter(must=conditions) if conditions else None

    @staticmethod
    def _point_to_retrieved_chunk(point: Any, method: str) -> RetrievedChunk:
        """Convert a Qdrant search result point to a RetrievedChunk."""
        payload = point.payload
        chunk = Chunk(
            chunk_id=payload.get("chunk_id", ""),
            document_id=payload.get("document_id", ""),
            chunk_type=payload.get("chunk_type", "prose"),
            content=payload.get("content", ""),
            token_count=payload.get("token_count", 0),
            page_number=payload.get("page_number", 0),
            section_hierarchy=payload.get("section_hierarchy", []),
            parent_chunk_id=payload.get("parent_chunk_id"),
            document_type=payload.get("document_type", "general"),
            source_file=payload.get("source_file", ""),
            confidence=payload.get("confidence", 1.0),
        )
        return RetrievedChunk(
            chunk=chunk,
            score=point.score,
            retrieval_method=method,
        )

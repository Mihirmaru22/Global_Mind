"""Query Pipeline — orchestrates Stages 12–14.

Takes a question, retrieves relevant chunks, reranks, and generates an answer.
"""

from __future__ import annotations

import logging

from src.core.config import settings
from src.core.provider_client import ProviderRouter
from src.core.rate_limiter import RateLimiter
from src.models.schemas import QueryResult
from src.stages.s10_embeddings import EmbeddingService
from src.stages.s11_vector_store import QdrantStore
from src.stages.s12_s13_s14_retrieval import Generator, Reranker, Retriever

logger = logging.getLogger(__name__)


class QueryPipeline:
    """Orchestrates the query flow: retrieve → rerank → generate."""

    def __init__(
        self,
        router: ProviderRouter | None = None,
        embedding_service: EmbeddingService | None = None,
        vector_store: QdrantStore | None = None,
    ) -> None:
        self._rate_limiter = RateLimiter()
        self._router = router or ProviderRouter()
        self._embeddings = embedding_service or EmbeddingService(self._rate_limiter)
        self._store = vector_store or QdrantStore()
        self._retriever = Retriever(self._store, self._embeddings)
        self._reranker = Reranker(self._rate_limiter)
        self._generator = Generator(self._router)

    async def query(
        self,
        question: str,
        filters: dict | None = None,
    ) -> QueryResult:
        """Run a full RAG query: retrieve → rerank → generate.

        Args:
            question: The user's natural-language question.
            filters: Optional metadata filters. Supported keys:
                     document_type, source_file, page_number, document_id, chunk_type.
        """
        logger.info("=== Query: %s ===", question[:100])

        # Stage 12 — Retrieval
        logger.info("[Stage 12] Retrieving chunks")
        retrieved = await self._retriever.retrieve(
            question, top_k=settings.retrieval_top_k, filters=filters
        )
        logger.info("Retrieved %d chunks", len(retrieved))

        if not retrieved:
            return QueryResult(
                query=question,
                answer="No relevant documents found. Please upload documents first.",
                model_used="none",
                reasoning_task="no_results",
            )

        # Stage 13 — Reranking
        logger.info("[Stage 13] Reranking")
        reranked = await self._reranker.rerank(
            question, retrieved, top_k=settings.rerank_top_k
        )
        logger.info("Reranked to %d chunks", len(reranked))

        # Stage 14 — Generation
        logger.info("[Stage 14] Generating answer")
        result = await self._generator.generate(question, reranked)
        result.chunks_retrieved = len(retrieved)
        result.chunks_after_rerank = len(reranked)

        logger.info("=== Query complete ===")
        return result

    async def query_stream(self, question: str, filters: dict | None = None):
        """Run a full RAG query and yield SSE stream chunks.

        Args:
            question: The user's natural-language question.
            filters: Optional metadata filters (same keys as query()).
        """
        from typing import AsyncGenerator
        from src.models.schemas import QueryResult

        logger.info("=== Query Stream: %s ===", question[:100])

        # Stage 12 — Retrieval
        retrieved = await self._retriever.retrieve(
            question, top_k=settings.retrieval_top_k, filters=filters
        )
        if not retrieved:
            yield "No relevant documents found. Please upload documents first."
            yield QueryResult(
                query=question,
                answer="No relevant documents found. Please upload documents first.",
                model_used="none",
                reasoning_task="no_results",
            )
            return

        # Stage 13 — Reranking
        reranked = await self._reranker.rerank(
            question, retrieved, top_k=settings.rerank_top_k
        )

        # Stage 14 — Generation
        async for chunk in self._generator.generate_stream(question, reranked):
            yield chunk

        logger.info("=== Query stream complete ===")

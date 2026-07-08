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
from src.stages.s12_s13_s14_retrieval import (
    Generator,
    Reranker,
    Retriever,
    _enforce_document_diversity,
    _is_exhaustive_query,
)
from src.stages.s12b_sql_retrieval import SQLRetriever

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
        self._sql_retriever = SQLRetriever(self._router)
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

        # Short-circuit: "what files/documents do you have?" — answer from registry
        if _is_document_listing_query(question):
            answer = _build_document_list_answer()
            return QueryResult(
                query=question,
                answer=answer,
                model_used="registry",
                reasoning_task="document_listing",
            )

        exhaustive = _is_exhaustive_query(question)
        if exhaustive:
            logger.info("Exhaustive query detected — boosting top_k and skipping rerank")

        # Step: Intent Classification
        intent = await _classify_sql_intent(question, self._router)
        # An exhaustive enumeration ("list every X across all documents") is
        # inherently a document-wide scan. If the router sent it down the
        # SQL-only path it would answer from one structured table and miss the
        # documents entirely — so guarantee vector retrieval runs alongside.
        if exhaustive and intent == "SQL":
            logger.info("Exhaustive query classified SQL-only — upgrading to BOTH for document coverage")
            intent = "BOTH"
        logger.info(f"Query intent classified as: {intent}")

        retrieved = []
        sql_chunks = []

        # Stage 12b — SQL Retrieval
        if intent in ["SQL", "BOTH"]:
            logger.info("[Stage 12b] Executing Text-to-SQL")
            sql_chunks = await self._sql_retriever.retrieve(question)
            if sql_chunks:
                logger.info("SQL query succeeded and returned rows.")
            else:
                logger.info("SQL query returned no results or failed.")

        # Stage 12 — Vector Retrieval
        if intent in ["VECTOR", "BOTH"]:
            logger.info("[Stage 12] Retrieving vector chunks")
            vector_chunks = await self._retriever.retrieve(
                question,
                top_k=settings.retrieval_top_k,
                filters=filters,
                exhaustive=exhaustive,
            )
            logger.info("Retrieved %d vector chunks", len(vector_chunks))
            retrieved.extend(vector_chunks)

        # Merge SQL results into the context
        if sql_chunks:
            # Prepend SQL results so they get highest priority
            retrieved = sql_chunks + retrieved

        if not retrieved:
            fallback_msg = "No relevant documents found. Please upload documents first."
            if intent == "SQL":
                fallback_msg = "I couldn't retrieve that from the live data — try rephrasing the question."
                
            return QueryResult(
                query=question,
                answer=fallback_msg,
                model_used="none",
                reasoning_task="no_results",
            )

        # Stage 13 — Reranking (skipped for exhaustive queries to preserve recall breadth)
        if exhaustive:
            reranked = _enforce_document_diversity(retrieved, settings.rerank_top_k)
        else:
            logger.info("[Stage 13] Reranking")
            reranked = await self._reranker.rerank(
                question, retrieved, top_k=settings.rerank_top_k
            )
            reranked = _enforce_document_diversity(reranked, settings.rerank_top_k)
        logger.info("Final context: %d chunks", len(reranked))

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

        # Short-circuit: document listing question — answer from registry
        if _is_document_listing_query(question):
            answer = _build_document_list_answer()
            yield answer
            yield QueryResult(
                query=question,
                answer=answer,
                model_used="registry",
                reasoning_task="document_listing",
            )
            return

        exhaustive = _is_exhaustive_query(question)
        if exhaustive:
            logger.info("Exhaustive query detected — boosting top_k and skipping rerank")

        # Step: Intent Classification
        intent = await _classify_sql_intent(question, self._router)
        # See query(): an exhaustive enumeration must always scan documents,
        # never answer from the SQL table alone.
        if exhaustive and intent == "SQL":
            logger.info("Exhaustive query classified SQL-only — upgrading to BOTH for document coverage")
            intent = "BOTH"
        logger.info(f"Query intent classified as: {intent}")

        retrieved = []
        sql_chunks = []

        # Stage 12b — SQL Retrieval
        if intent in ["SQL", "BOTH"]:
            sql_chunks = await self._sql_retriever.retrieve(question)

        # Stage 12 — Vector Retrieval
        if intent in ["VECTOR", "BOTH"]:
            vector_chunks = await self._retriever.retrieve(
                question,
                top_k=settings.retrieval_top_k,
                filters=filters,
                exhaustive=exhaustive,
            )
            retrieved.extend(vector_chunks)

        if sql_chunks:
            retrieved = sql_chunks + retrieved

        if not retrieved:
            fallback_msg = "No relevant documents found. Please upload documents first."
            if intent == "SQL":
                fallback_msg = "I couldn't retrieve that from the live data — try rephrasing the question."

            yield fallback_msg
            yield QueryResult(
                query=question,
                answer=fallback_msg,
                model_used="none",
                reasoning_task="no_results",
            )
            return

        # Stage 13 — Reranking (skipped for exhaustive queries)
        if exhaustive:
            reranked = _enforce_document_diversity(retrieved, settings.rerank_top_k)
        else:
            reranked = await self._reranker.rerank(
                question, retrieved, top_k=settings.rerank_top_k
            )
            reranked = _enforce_document_diversity(reranked, settings.rerank_top_k)

        # Stage 14 — Generation
        async for chunk in self._generator.generate_stream(question, reranked):
            yield chunk

        logger.info("=== Query stream complete ===")


# ---------------------------------------------------------------------------
# Document listing helpers
# ---------------------------------------------------------------------------

_LISTING_KEYWORDS = [
    "what files", "which files", "what documents", "which documents",
    "list files", "list documents", "list all", "show files", "show documents",
    "what have you", "what do you have", "what have you ingested",
    "what documents do you", "what files do you", "documents uploaded",
    "files uploaded", "ingested files", "available documents", "available files",
    "what is in your", "what's in your", "knowledge base",
]


def _is_document_listing_query(question: str) -> bool:
    """Return True if the question is asking to list ingested documents."""
    q = question.lower().strip()
    return any(kw in q for kw in _LISTING_KEYWORDS)


def _build_document_list_answer() -> str:
    """Build a human-friendly answer from the ingestion registry."""
    from src.core.ingestion_registry import IngestionRegistry
    import datetime

    registry = IngestionRegistry()
    entries = list(registry.get_all().values())

    if not entries:
        return "I don't have any documents ingested yet. Please upload some files first."

    lines = [f"I currently have **{len(entries)} document(s)** in my knowledge base:\n"]
    for i, entry in enumerate(entries, 1):
        file_name = entry.get("file_name", "Unknown")
        chunks = entry.get("total_chunks", "?")
        ingested_at = entry.get("ingested_at", "")
        # Format date nicely — convert to IST (UTC+5:30)
        try:
            dt = datetime.datetime.fromisoformat(ingested_at)
            ist = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
            dt_ist = dt.astimezone(ist)
            date_str = dt_ist.strftime("%Y-%m-%d %I:%M %p IST")
        except Exception:
            date_str = ingested_at[:10] if ingested_at else "unknown"
        lines.append(f"{i}. **{file_name}** — {chunks} chunks (ingested {date_str})")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# SQL Intent Helpers
# ---------------------------------------------------------------------------

_SQL_KEYWORDS = [
    "total", "average", "sum", "count", "how many", "maximum", "minimum",
    "top", "bottom", "last quarter", "revenue", "sales", "profit",
]

async def _classify_sql_intent(query: str, router: ProviderRouter) -> str:
    """Classify if a query needs VECTOR, SQL, or BOTH.
    
    Uses a fast regex/keyword pre-filter. If unsure, falls back to the `classification` LLM.
    """
    q = query.lower()
    
    # 1. Heuristic Pre-filter: if it explicitly asks for metrics, default to SQL
    if any(kw in q for kw in _SQL_KEYWORDS):
        return "SQL"

    # 2. LLM Fallback for ambiguous cases
    system_prompt = """You are a query router.
Classify the user's question into one of three categories:
VECTOR: The user is asking about concepts, policies, explanations, or general text.
SQL: The user is asking for exact numerical aggregations, counts, totals, or database metrics.
BOTH: The question strictly requires BOTH conceptual text and exact data (e.g., "Based on the policy, what is our total revenue?"). Only use BOTH if you absolutely need document context in addition to numbers.

Reply with EXACTLY one word: VECTOR, SQL, or BOTH."""

    try:
        response = await router.chat(
            task="classification",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": query},
            ],
            max_tokens=10
        )
        result = response.strip().upper()
        if result in ["VECTOR", "SQL", "BOTH"]:
            return result
    except Exception as e:
        logger.warning(f"Intent classification LLM failed, defaulting to VECTOR: {e}")
        
    return "VECTOR"

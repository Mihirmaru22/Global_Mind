"""Query Pipeline — orchestrates Stages 12–14.

Takes a question, retrieves relevant chunks, reranks, and generates an answer.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from src.core.config import settings
from src.core.provider_client import ProviderRouter
from src.core.rate_limiter import RateLimiter
from src.models.schemas import QueryResult, ThinkingStep
from src.stages.s10_embeddings import EmbeddingService
from src.stages.s11_vector_store import QdrantStore
from src.stages.s12_s13_s14_retrieval import (
    Generator,
    Reranker,
    Retriever,
    _enforce_document_diversity,
    _is_exhaustive_query,
    _is_visualization_query,
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
        preferred_provider: str | None = None,
    ) -> None:
        self._rate_limiter = RateLimiter()
        # A single router drives retrieval, reranking, and generation, so the
        # soft pin applies uniformly across the whole query.
        self._router = router or ProviderRouter(preferred_provider=preferred_provider)
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
        history: list[dict] | None = None,
    ) -> QueryResult:
        """Run a full RAG query: retrieve → rerank → generate.

        Args:
            question: The user's natural-language question.
            filters: Optional metadata filters. Supported keys:
                     document_type, source_file, page_number, document_id, chunk_type.
            history: Prior conversation turns (dicts with role/content), used to
                     resolve follow-ups into standalone queries and to keep the
                     answer coherent with the conversation.
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

        # Consult the conversation ONLY when the message looks like it depends on
        # it. A self-contained or new-topic question skips history entirely and is
        # answered exactly as it would be with no conversation — so history never
        # biases an unrelated question. When it is a follow-up, rewrite it into a
        # standalone query so retrieval continues the current thread.
        needs_context = bool(history) and _looks_like_followup(question)
        search_query = question
        if needs_context:
            search_query = await _contextualize_query(question, history, self._router)
            if search_query != question:
                logger.info("Contextualized query: '%s' -> '%s'", question, search_query)
        gen_history = history if needs_context else None

        exhaustive = _is_exhaustive_query(search_query)
        if exhaustive:
            logger.info("Exhaustive query detected — boosting top_k and skipping rerank")

        # Step: Intent Classification
        intent = await _classify_sql_intent(search_query, self._router)
        # An exhaustive enumeration ("list every X across all documents") is
        # inherently a document-wide scan. If the router sent it down the
        # SQL-only path it would answer from one structured table and miss the
        # documents entirely — so guarantee vector retrieval runs alongside.
        if exhaustive and intent == "SQL":
            logger.info("Exhaustive query classified SQL-only — upgrading to BOTH for document coverage")
            intent = "BOTH"
        # A visualization request ("bar chart of total units") often trips a
        # metric keyword like "total" and gets routed to SQL-only, but the
        # values to chart may live in the documents. Keep both sources in play.
        elif _is_visualization_query(search_query) and intent == "SQL":
            logger.info("Visualization query classified SQL-only — upgrading to BOTH so charts can use document data")
            intent = "BOTH"
        logger.info(f"Query intent classified as: {intent}")

        retrieved = []
        sql_chunks = []

        # Stage 12b — SQL Retrieval (additive: precise figures from the live DB)
        if intent in ["SQL", "BOTH"]:
            logger.info("[Stage 12b] Executing Text-to-SQL")
            sql_chunks = await self._sql_retriever.retrieve(search_query)
            if sql_chunks:
                logger.info("SQL query succeeded and returned rows.")
            else:
                logger.info("SQL query returned no results or failed.")

        # Stage 12 — Vector Retrieval (always runs)
        # Document retrieval is never skipped. SQL augments answers with exact
        # figures, but it must never *replace* document knowledge: the live DB
        # has only the gpu_sales table, so a question whose answer lives solely
        # in the documents ("cheapest iPhone") would otherwise be hijacked by
        # whatever rows that table returns. Non-deterministic intent
        # classification made this worse — regenerating the same question would
        # flip between a correct document answer and a wrong SQL-only one.
        # Retrieving documents unconditionally and letting the reranker pick the
        # relevant chunks makes the outcome consistent and correct.
        logger.info("[Stage 12] Retrieving vector chunks")
        vector_chunks = await self._retriever.retrieve(
            search_query,
            top_k=settings.retrieval_top_k,
            filters=filters,
            exhaustive=exhaustive,
        )
        logger.info("Retrieved %d vector chunks", len(vector_chunks))
        retrieved.extend(vector_chunks)

        # Merge SQL results into the context (prepended; the reranker re-scores
        # everything by relevance, so an off-topic SQL result is demoted).
        if sql_chunks:
            retrieved = sql_chunks + retrieved

        if not retrieved:
            fallback_msg = "No relevant documents found. Please upload documents first."

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
                search_query, retrieved, top_k=settings.rerank_top_k
            )
            reranked = _enforce_document_diversity(reranked, settings.rerank_top_k)
        logger.info("Final context: %d chunks", len(reranked))

        # Stage 14 — Generation (the user's original question + conversation,
        # but only when the question actually depends on it)
        logger.info("[Stage 14] Generating answer")
        result = await self._generator.generate(question, reranked, history=gen_history)
        result.chunks_retrieved = len(retrieved)
        result.chunks_after_rerank = len(reranked)

        logger.info("=== Query complete ===")
        return result

    async def query_stream(
        self, question: str, filters: dict | None = None, history: list[dict] | None = None
    ):
        """Run a full RAG query and yield SSE stream chunks.

        Args:
            question: The user's natural-language question.
            filters: Optional metadata filters (same keys as query()).
            history: Prior conversation turns for follow-up resolution.
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

        # Reasoning trace ("thinking") — each step is streamed live to the UI as
        # it happens and collected onto the final QueryResult so it persists.
        thinking: list[ThinkingStep] = []

        def _think(label: str, detail: str = "") -> ThinkingStep:
            step = ThinkingStep(label=label, detail=detail)
            thinking.append(step)
            return step

        # Consult the conversation ONLY when the message looks like a follow-up
        # (see query()) — a self-contained/new-topic question stays stateless so
        # history can't bias it.
        needs_context = bool(history) and _looks_like_followup(question)
        search_query = question
        if needs_context:
            search_query = await _contextualize_query(question, history, self._router)
            if search_query != question:
                logger.info("Contextualized query: '%s' -> '%s'", question, search_query)
                yield _think("Read the conversation", f"resolved to: {search_query}")
        gen_history = history if needs_context else None

        exhaustive = _is_exhaustive_query(search_query)
        if exhaustive:
            logger.info("Exhaustive query detected — boosting top_k and skipping rerank")

        # Step: Intent Classification
        intent = await _classify_sql_intent(search_query, self._router)
        # See query(): an exhaustive enumeration must always scan documents,
        # never answer from the SQL table alone.
        if exhaustive and intent == "SQL":
            logger.info("Exhaustive query classified SQL-only — upgrading to BOTH for document coverage")
            intent = "BOTH"
        # See query(): a chart request must keep document retrieval in play even
        # when a metric keyword routed it to SQL.
        elif _is_visualization_query(search_query) and intent == "SQL":
            logger.info("Visualization query classified SQL-only — upgrading to BOTH so charts can use document data")
            intent = "BOTH"
        logger.info(f"Query intent classified as: {intent}")
        _intent_detail = {
            "SQL": "needs figures from the live database",
            "VECTOR": "needs context from the documents",
            "BOTH": "needs both live data and documents",
        }.get(intent, intent)
        yield _think("Understanding the question", _intent_detail)

        retrieved = []
        sql_chunks = []

        # Stage 12b — SQL Retrieval (additive)
        if intent in ["SQL", "BOTH"]:
            sql_chunks = await self._sql_retriever.retrieve(search_query)
            if sql_chunks:
                # Surface the actual generated SQL, not a canned phrase — every
                # question produces a different query.
                sql_match = re.search(r"SQL Query Executed: `(.+?)`", sql_chunks[0].chunk.content)
                sql_detail = sql_match.group(1) if sql_match else "returned matching rows"
                yield _think("Queried the live database", sql_detail)
            else:
                yield _think("Queried the live database", "no matching rows — checking documents instead")

        # Stage 12 — Vector Retrieval (always runs; see query() for rationale).
        # Document context is never skipped so a document-only answer can't be
        # hijacked by the gpu_sales table, and regenerating stays consistent.
        vector_chunks = await self._retriever.retrieve(
            search_query,
            top_k=settings.retrieval_top_k,
            filters=filters,
            exhaustive=exhaustive,
        )
        retrieved.extend(vector_chunks)
        # Name the actual source files this question matched against, so two
        # different questions never show the same trace.
        doc_names = list(dict.fromkeys(
            Path(c.chunk.source_file).name for c in vector_chunks if c.chunk.source_file
        ))
        if doc_names:
            shown = ", ".join(doc_names[:3])
            more = f" +{len(doc_names) - 3} more" if len(doc_names) > 3 else ""
            doc_detail = f"{len(vector_chunks)} passage(s) in {shown}{more}"
        else:
            doc_detail = f"{len(vector_chunks)} passage(s)" if vector_chunks else "no matches"
        yield _think("Searched the documents", doc_detail)

        if sql_chunks:
            retrieved = sql_chunks + retrieved

        if not retrieved:
            fallback_msg = "No relevant documents found. Please upload documents first."

            yield fallback_msg
            yield QueryResult(
                query=question,
                answer=fallback_msg,
                model_used="none",
                reasoning_task="no_results",
                thinking=thinking,
            )
            return

        # Stage 13 — Reranking (skipped for exhaustive queries)
        if exhaustive:
            reranked = _enforce_document_diversity(retrieved, settings.rerank_top_k)
        else:
            reranked = await self._reranker.rerank(
                search_query, retrieved, top_k=settings.rerank_top_k
            )
            reranked = _enforce_document_diversity(reranked, settings.rerank_top_k)
        top_source = Path(reranked[0].chunk.source_file).name if reranked and reranked[0].chunk.source_file else None
        rank_detail = f"kept the {len(reranked)} best — top match: {top_source}" if top_source else f"kept the top {len(reranked)}"
        yield _think("Ranked the most relevant sources", rank_detail)
        yield _think("Writing the answer")

        # Stage 14 — Generation. generate_stream yields answer text chunks and,
        # finally, the QueryResult — attach the collected thinking to it and
        # note which provider/model actually answered, so the trace closes out
        # with a real, per-question detail rather than a static label. The
        # user's original question drives the answer; history is included only
        # for genuine follow-ups (gen_history), never forced on new topics.
        async for chunk in self._generator.generate_stream(question, reranked, history=gen_history):
            if isinstance(chunk, QueryResult):
                if chunk.model_used:
                    thinking.append(ThinkingStep(label="Answered using", detail=chunk.model_used))
                chunk.thinking = thinking
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
    # "doc"/"docs" phrasings — the colloquial shorthand for the above. Without
    # these, "what docs you have" falls through to RAG retrieval and only
    # describes the handful of chunks that happened to match, contradicting the
    # authoritative registry listing.
    "what docs", "which docs", "list docs", "show docs", "docs do you",
    "docs you have", "available docs", "docs uploaded", "ingested docs",
    # Count-style questions are also answered from the registry, not text-to-SQL.
    "how many documents", "how many docs", "how many files",
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
# Conversational memory
# ---------------------------------------------------------------------------

_CONTEXTUALIZE_PROMPT = """You rewrite a user's follow-up message into a standalone question, using the conversation ONLY to resolve references that genuinely need it.

Rules:
- If the message depends on the conversation (pronouns like "it"/"that"/"them", or continuations like "compare", "make a table", "the second one", "why is it better"), rewrite it into a self-contained question by pulling in the missing subject from the conversation.
- If the message is ALREADY self-contained, or introduces a NEW topic not discussed above, return it EXACTLY unchanged. Do not force the earlier subject onto an unrelated question.
- Never add facts or assumptions — only resolve references.
- Keep it concise. Output ONLY the resulting question — no preamble, no quotes.

Conversation:
{history}

Follow-up: {question}

Standalone question:"""


# Cues that a message leans on the prior conversation rather than standing
# alone. Deliberately excludes weak, ubiquitous words ("and", "also") to avoid
# flagging self-contained questions.
_FOLLOWUP_CUES = re.compile(
    r"\b(it|its|it'?s|that|those|these|them|they|the (?:first|second|third|last|other|same|above|previous|former|latter)"
    r"|compare|comparison|vs\.?|versus|make a table|make table|tabulate|chart it|graph it|plot it"
    r"|how about|what about|expand|elaborate|continue|instead|difference|again|rephrase|the rest)\b",
    re.IGNORECASE,
)


def _looks_like_followup(question: str) -> bool:
    """Heuristic: does this message likely depend on the prior conversation?

    Very short messages and referential/continuation cues suggest a follow-up.
    Anything else is treated as self-contained, so history is never consulted
    and a fresh, unrelated question is answered exactly as it would be with no
    conversation at all — no bias toward earlier topics.
    """
    q = question.strip()
    if not q:
        return False
    if len(q.split()) <= 4:
        return True
    return bool(_FOLLOWUP_CUES.search(q))


def _format_history(history: list[dict] | None, *, max_turns: int = 6, max_chars: int = 700) -> str:
    """Compact the last few conversation turns into a plain transcript."""
    if not history:
        return ""
    lines: list[str] = []
    for msg in history[-max_turns:]:
        if msg.get("kind") == "ingestion" or msg.get("status") == "loading":
            continue
        content = (msg.get("content") or "").strip()
        if not content:
            continue
        role = "User" if msg.get("role") == "user" else "Assistant"
        lines.append(f"{role}: {content[:max_chars]}")
    return "\n".join(lines)


async def _contextualize_query(
    question: str, history: list[dict] | None, router: ProviderRouter
) -> str:
    """Rewrite a follow-up into a standalone query for retrieval.

    Without this, a message like "make a table to compare" carries no subject,
    so retrieval matches arbitrary documents instead of continuing the current
    thread. Returns the original question when there's no history or the rewrite
    is unavailable.
    """
    convo = _format_history(history)
    if not convo:
        return question
    try:
        rewritten = await router.chat(
            task="fast_support",
            messages=[
                {"role": "user", "content": _CONTEXTUALIZE_PROMPT.format(history=convo, question=question)},
            ],
            max_tokens=120,
            temperature=0.0,
        )
        rewritten = (rewritten or "").strip().strip('"').strip()
        if rewritten and len(rewritten) <= 400:
            return rewritten
    except Exception as e:
        logger.warning("Query contextualization failed: %s — using original question", e)
    return question


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

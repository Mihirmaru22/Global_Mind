"""Stages 12–14 — Retrieval, Reranking, and Generation.

Stage 12: True hybrid dense+sparse retrieval with RRF fusion (top 20-50)
          BM25-lite heuristic REMOVED — replaced by real Qdrant sparse vectors.
Stage 13: Jina Reranker v3 → top 5-8
Stage 14: Task-routed LLM generation with citations
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import httpx

from src.core.config import settings
from src.core.provider_client import ProviderRouter
from src.core.rate_limiter import RateLimiter
from src.models.schemas import Citation, Chunk, QueryResult, RetrievedChunk
from src.stages.s10_embeddings import EmbeddingService
from src.stages.s11_vector_store import QdrantStore

logger = logging.getLogger(__name__)

_JINA_RERANK_URL = "https://api.jina.ai/v1/rerank"


# ---------------------------------------------------------------------------
# Stage 12 — Retrieval
# ---------------------------------------------------------------------------

class Retriever:
    """True hybrid retriever: Jina dense + Jina sparse vectors, RRF-fused in Qdrant.

    Supports optional metadata filters to constrain retrieval to specific
    document types, source files, page ranges, etc.
    """

    def __init__(
        self,
        store: QdrantStore,
        embedding_service: EmbeddingService,
    ) -> None:
        self._store = store
        self._embeddings = embedding_service

    async def retrieve(
        self,
        query: str,
        top_k: int = 30,
        filters: dict[str, Any] | None = None,
        exhaustive: bool = False,
    ) -> list[RetrievedChunk]:
        """Retrieve the top-k most relevant chunks for a query.

        Args:
            query: Natural language question.
            top_k: Number of results to retrieve.
            filters: Optional metadata filter dict. Supported keys:
                     document_type, source_file, page_number, document_id, chunk_type.
            exhaustive: When True, boosts top_k and disables per-document caps to
                        maximise recall for "list all X" style queries.

        Returns:
            List of RetrievedChunk sorted by descending relevance score.
        """
        effective_top_k = min(top_k * 2, 120) if exhaustive else top_k

        # Get dense + sparse query embeddings in one API call
        dense_vector, sparse_vector = await self._embeddings.embed_query(query)

        # Hybrid RRF search (degrades gracefully to dense-only if sparse is empty)
        results = await self._store.search_hybrid(
            query_vector=dense_vector,
            sparse_vector=sparse_vector,
            query_text=query,
            top_k=effective_top_k,
            filters=filters,
        )

        return results


# ---------------------------------------------------------------------------
# Stage 13 — Reranking
# ---------------------------------------------------------------------------

class Reranker:
    """Reranks retrieved chunks using Jina Reranker v3."""

    def __init__(self, rate_limiter: RateLimiter | None = None) -> None:
        self._rate_limiter = rate_limiter or RateLimiter()
        self._http: httpx.AsyncClient | None = None

    def _get_http(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=30.0)
        return self._http

    async def rerank(
        self, query: str, chunks: list[RetrievedChunk], top_k: int = 6
    ) -> list[RetrievedChunk]:
        """Rerank chunks and return the top-k."""
        if not chunks:
            return []

        if settings.jina_api_key:
            try:
                return await self._rerank_jina(query, chunks, top_k)
            except Exception as e:
                logger.warning("Jina reranking failed: %s — using retrieval scores", e)

        # Fallback: just return top-k by retrieval score
        return sorted(chunks, key=lambda r: r.score, reverse=True)[:top_k]

    async def _rerank_jina(
        self, query: str, chunks: list[RetrievedChunk], top_k: int
    ) -> list[RetrievedChunk]:
        """Rerank via Jina Reranker API."""
        await self._rate_limiter.acquire("jina")
        http = self._get_http()

        documents = [c.chunk.content for c in chunks]

        response = await http.post(
            _JINA_RERANK_URL,
            headers={
                "Authorization": f"Bearer {settings.jina_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "jina-reranker-v2-base-multilingual",
                "query": query,
                "documents": documents,
                "top_n": top_k,
            },
        )
        response.raise_for_status()
        data = response.json()

        reranked: list[RetrievedChunk] = []
        for result in data.get("results", []):
            idx = result["index"]
            score = result["relevance_score"]
            reranked_chunk = chunks[idx]
            reranked_chunk.score = score
            reranked_chunk.retrieval_method = "reranked"
            reranked.append(reranked_chunk)

        return reranked


# ---------------------------------------------------------------------------
# Stage 14 — Generation
# ---------------------------------------------------------------------------

class Generator:
    """Task-routed LLM generation with citation support."""

    def __init__(self, router: ProviderRouter) -> None:
        self._router = router

    async def generate(
        self,
        query: str,
        chunks: list[RetrievedChunk],
        *,
        task: str | None = None,
    ) -> QueryResult:
        """Generate an answer from retrieved chunks.

        Automatically routes to the best model for the inferred task type.
        """
        if not chunks:
            return QueryResult(
                query=query,
                answer="I couldn't find any relevant information to answer your question.",
                model_used="none",
                reasoning_task="no_chunks",
            )

        # Determine task type if not provided
        if task is None:
            task = _classify_query_task(query)

        # Build context from chunks
        context = _build_context(chunks)

        # Build the prompt
        system_prompt = _build_system_prompt(task)
        user_prompt = f"""Context (retrieved document chunks):
---
{context}
---

Question: {query}

Answer the question using ONLY the information provided in the context above.
Each excerpt is tagged with a bracketed source marker like [a1b2c3d4_0007]. Cite your claims inline by copying the exact marker(s) in brackets — e.g. "Opus scored 86.8% [a1b2c3d4_0007]." These render as clean numbered references, so do NOT add a separate column or heading for them and do NOT refer to them as "chunks" in your prose.
If the context doesn't contain enough information to answer, say so explicitly."""

        # Generate
        response = await self._router.chat(
            task,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=2048,
        )

        # Extract citations and format the answer text
        citations, clean_answer = _extract_and_format_citations(response, chunks)

        return QueryResult(
            query=query,
            answer=clean_answer,
            citations=citations,
            model_used=task,
            reasoning_task=task,
            chunks_retrieved=len(chunks),
            chunks_after_rerank=len(chunks),
        )

    async def generate_stream(
        self,
        query: str,
        chunks: list[RetrievedChunk],
        *,
        task: str | None = None,
    ):
        """Stage 14: Answer generation via LLM stream.

        Yields string chunks during generation, and a final QueryResult object
        when the stream completes.
        """
        if not chunks:
            yield "I don't have any information about that in my current documents."
            yield QueryResult(
                query=query,
                answer="I don't have any information about that in my current documents.",
                citations=[],
                model_used="none",
                reasoning_task="none",
                chunks_retrieved=0,
                chunks_after_rerank=0,
            )
            return

        if task is None:
            task = _classify_query_task(query)

        context = _build_context(chunks)
        system_prompt = _build_system_prompt(task)
        user_prompt = f"""Context (retrieved document chunks):
---
{context}
---

Question: {query}

Answer the question using ONLY the information provided in the context above.
Each excerpt is tagged with a bracketed source marker like [a1b2c3d4_0007]. Cite your claims inline by copying the exact marker(s) in brackets — e.g. "Opus scored 86.8% [a1b2c3d4_0007]." These render as clean numbered references, so do NOT add a separate column or heading for them and do NOT refer to them as "chunks" in your prose.
If the context doesn't contain enough information to answer, say so explicitly."""

        full_answer_parts = []
        async for chunk_text in self._router.chat_stream(
            task,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=2048,
        ):
            full_answer_parts.append(chunk_text)
            yield chunk_text

        full_answer = "".join(full_answer_parts)
        citations, clean_answer = _extract_and_format_citations(full_answer, chunks)

        yield QueryResult(
            query=query,
            answer=clean_answer,
            citations=citations,
            model_used=task,
            reasoning_task=task,
            chunks_retrieved=len(chunks),
            chunks_after_rerank=len(chunks),
        )


def _classify_query_task(query: str) -> str:
    """Infer the best LLM task type from the query."""
    query_lower = query.lower()

    if any(kw in query_lower for kw in ["summarize", "summary", "overview", "brief"]):
        return "summarization"
    if any(kw in query_lower for kw in ["why", "how", "explain", "reason", "analyze", "compare"]):
        return "reasoning"
    if any(kw in query_lower for kw in ["extract", "list", "find all", "what are the"]):
        return "extraction"

    return "general_qa"


_EXHAUSTIVE_KEYWORDS = [
    "list every", "list all", "all companies", "every company", "all products",
    "every product", "all entities", "every entity", "all mentions", "all models",
    "every model", "all documents", "enumerate", "comprehensive list",
    "complete list", "full list", "all names", "every name", "all people",
    "every person", "all locations", "every location", "across all", "across documents",
]


def _is_exhaustive_query(query: str) -> bool:
    """Return True if the query asks for an exhaustive enumeration."""
    q = query.lower()
    return any(kw in q for kw in _EXHAUSTIVE_KEYWORDS)


def _enforce_document_diversity(
    chunks: list[RetrievedChunk],
    target_k: int,
) -> list[RetrievedChunk]:
    """Guarantee proportional document representation in the final context.

    Algorithm:
    1. Group chunks by document_id.
    2. Compute per-document quota = ceil(target_k / num_unique_docs), min 2.
    3. Fill slots round-robin by score, respecting per-document quota.
    4. If slots remain after all quotas are filled, top up from leftovers.

    This prevents a single high-volume or high-similarity document from
    crowding out all chunks from other documents.
    """
    import math
    from collections import defaultdict

    if not chunks:
        return chunks

    # Group by document preserving score order (chunks are already sorted desc)
    doc_buckets: dict[str, list[RetrievedChunk]] = defaultdict(list)
    for c in chunks:
        doc_buckets[c.chunk.document_id].append(c)

    num_docs = len(doc_buckets)
    if num_docs <= 1:
        # Single document — no diversity enforcement needed
        return chunks[:target_k]

    # Per-document slot quota
    quota = max(2, math.ceil(target_k / num_docs))
    logger.debug(
        "Document diversity: %d docs, target_k=%d, quota=%d per doc",
        num_docs, target_k, quota,
    )

    # Fill slots: take up to `quota` from each document in round-robin passes
    selected: list[RetrievedChunk] = []
    pointers = {doc_id: 0 for doc_id in doc_buckets}
    leftover: list[RetrievedChunk] = []

    # Pass 1: take quota from each doc (preserving intra-doc score order)
    for doc_id, bucket in doc_buckets.items():
        taken = bucket[:quota]
        selected.extend(taken)
        leftover.extend(bucket[quota:])

    # Trim to target_k
    selected = selected[:target_k]

    # Pass 2: if we still have room, fill from leftover sorted by score
    if len(selected) < target_k:
        leftover_sorted = sorted(leftover, key=lambda r: r.score, reverse=True)
        selected.extend(leftover_sorted[: target_k - len(selected)])

    # Re-sort the final selection by score so the LLM sees best chunks first
    selected.sort(key=lambda r: r.score, reverse=True)

    doc_counts = defaultdict(int)
    for c in selected:
        doc_counts[c.chunk.document_id] += 1
    logger.info(
        "Post-diversity chunks: %d total from %d docs — %s",
        len(selected),
        len(doc_counts),
        dict(doc_counts),
    )

    return selected


_VISUALIZATION_GUIDANCE = """

Formatting and visualization:
- Present tabular or comparison data as a GitHub-flavored Markdown table.
- When the user asks for a chart, graph, or diagram — or when one would communicate the answer more clearly — render it as a fenced ```mermaid code block. The app renders Mermaid natively, so DO NOT claim you lack tools to create visualizations.
  - Proportions / share of a whole → `pie`
  - Comparing values across categories, or trends → `xychart-beta` (bar or line)
  - Processes, flows, hierarchies → `flowchart`
  - Steps over time → `timeline`; interactions → `sequenceDiagram`
- Only chart numbers that actually appear in the context. If the exact values needed for a chart are missing, say which values are missing and chart whatever related data IS available (e.g. benchmark scores, context-window sizes) rather than refusing outright.
- Keep Mermaid syntax valid and self-contained; put every data point on its own line."""


def _build_system_prompt(task: str) -> str:
    """Build a task-appropriate system prompt."""
    base = "You are a precise document analysis assistant. "

    prompts = {
        "general_qa": base + "Answer questions accurately based on the provided context. Always cite your sources using their bracketed source markers.",
        "reasoning": base + "Perform careful multi-step reasoning. Show your reasoning process. Cite all sources with their bracketed markers.",
        "extraction": base + "Extract structured information precisely. Use JSON format when appropriate. Cite sources with their bracketed markers.",
        "summarization": base + "Provide comprehensive summaries. Cover all key points from the context. Cite sources with their bracketed markers.",
    }

    return prompts.get(task, prompts["general_qa"]) + _VISUALIZATION_GUIDANCE


def _build_context(chunks: list[RetrievedChunk]) -> str:
    """Format retrieved chunks into a context string, bounded by a token limit."""
    parts: list[str] = []
    current_tokens = 0
    MAX_CONTEXT_TOKENS = 6000

    for chunk in chunks:
        c = chunk.chunk
        header = f"[{c.chunk_id}] (page {c.page_number}, type: {c.chunk_type.value})"
        chunk_text = f"{header}\n{c.content}"
        
        # Rough token estimate
        est_tokens = len(chunk_text) // 4
        
        if current_tokens + est_tokens > MAX_CONTEXT_TOKENS and parts:
            logger.info("Context length bounded to %d tokens (dropped %d lower-ranked chunks)", 
                       current_tokens, len(chunks) - len(parts))
            break
            
        parts.append(chunk_text)
        current_tokens += est_tokens

    return "\n\n---\n\n".join(parts)


def _extract_and_format_citations(answer: str, chunks: list[RetrievedChunk]) -> tuple[list[Citation], str]:
    """Extract chunk IDs, replace with readable footnotes, and append a source list.

    Handles two citation shapes the model produces:
      1. Single-ID brackets:  [<doc>_chunk_0043]
      2. Multi-ID brackets:   [<doc>_chunk_0043, <doc>_chunk_0027, ...]

    Every referenced chunk maps to a stable footnote number (deduped by the
    chunk's *source file + page*, so ten chunks from page 8 of one PDF collapse
    into a single [1] rather than [1][2]...[10]). Any chunk-ID bracket that
    can't be resolved to a retrieved chunk is stripped rather than left raw,
    so internal IDs never leak into the visible answer.
    """
    import re

    # A single chunk-id token, e.g. "418c66529513d93e_chunk_0043"
    _CHUNK_ID = r"[a-f0-9]+_chunk_\d+"
    # A bracket containing one or more comma-separated chunk-ids (and whitespace)
    _CITATION_BRACKET = re.compile(rf"\[\s*{_CHUNK_ID}(?:\s*,\s*{_CHUNK_ID})*\s*\]")

    chunk_by_id = {c.chunk.chunk_id: c for c in chunks}

    citations: list[Citation] = []
    sources_text: list[str] = []
    # Footnote numbers are assigned per unique (source_file, page) so repeated
    # chunks from the same page share one number.
    footnote_by_source: dict[tuple[str, int], int] = {}

    def _footnote_for(chunk: RetrievedChunk) -> int:
        key = (chunk.chunk.source_file, chunk.chunk.page_number)
        if key not in footnote_by_source:
            idx = len(footnote_by_source) + 1
            footnote_by_source[key] = idx
            citations.append(Citation(
                chunk_id=chunk.chunk.chunk_id,
                source_file=chunk.chunk.source_file,
                page_number=chunk.chunk.page_number,
                relevance_score=chunk.score,
            ))
            page_text = f" (Page {chunk.chunk.page_number})" if chunk.chunk.page_number else ""
            # Show the clean document name, never the absolute path or chunk id.
            doc_name = Path(chunk.chunk.source_file).name or chunk.chunk.source_file
            sources_text.append(f"{idx}. {doc_name}{page_text}")
        return footnote_by_source[key]

    def _replace_bracket(match: re.Match) -> str:
        raw_ids = [tok.strip() for tok in match.group(0).strip("[]").split(",")]
        footnotes: list[int] = []
        for cid in raw_ids:
            chunk = chunk_by_id.get(cid)
            if chunk is not None:
                fn = _footnote_for(chunk)
                if fn not in footnotes:
                    footnotes.append(fn)
        # If none resolved, drop the bracket entirely (no raw IDs leak through)
        return "".join(f"[{fn}]" for fn in footnotes)

    clean_answer = _CITATION_BRACKET.sub(_replace_bracket, answer)

    # Safety net: strip any stray single chunk-id bracket the pattern above
    # somehow missed, so internal IDs are never shown to the user.
    clean_answer = re.sub(rf"\[\s*{_CHUNK_ID}\s*\]", "", clean_answer)

    if sources_text:
        clean_answer += "\n\n**References**\n\n" + "\n".join(sources_text)

    return citations, clean_answer

"""Stages 12–14 — Retrieval, Reranking, and Generation.

Stage 12: True hybrid dense+sparse retrieval with RRF fusion (top 20-50)
          BM25-lite heuristic REMOVED — replaced by real Qdrant sparse vectors.
Stage 13: Jina Reranker v3 → top 5-8
Stage 14: Task-routed LLM generation with citations
"""

from __future__ import annotations

import json
import logging
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
    ) -> list[RetrievedChunk]:
        """Retrieve the top-k most relevant chunks for a query.

        Args:
            query: Natural language question.
            top_k: Number of results to retrieve.
            filters: Optional metadata filter dict. Supported keys:
                     document_type, source_file, page_number, document_id, chunk_type.

        Returns:
            List of RetrievedChunk sorted by descending relevance score.
        """
        # Get dense + sparse query embeddings in one API call
        dense_vector, sparse_vector = await self._embeddings.embed_query(query)

        # Hybrid RRF search (degrades gracefully to dense-only if sparse is empty)
        results = await self._store.search_hybrid(
            query_vector=dense_vector,
            sparse_vector=sparse_vector,
            query_text=query,
            top_k=top_k,
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
For each claim, cite the chunk ID(s) in square brackets, like [chunk_id].
If the context doesn't contain enough information to answer, say so explicitly."""

        # Generate
        response = await self._router.chat(
            task,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=4096,
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
For each claim, cite the chunk ID(s) in square brackets, like [chunk_id].
If the context doesn't contain enough information to answer, say so explicitly."""

        full_answer_parts = []
        async for chunk_text in self._router.chat_stream(
            task,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=4096,
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


def _build_system_prompt(task: str) -> str:
    """Build a task-appropriate system prompt."""
    base = "You are a precise document analysis assistant. "

    prompts = {
        "general_qa": base + "Answer questions accurately based on the provided context. Always cite your sources using chunk IDs.",
        "reasoning": base + "Perform careful multi-step reasoning. Show your reasoning process. Cite all sources.",
        "extraction": base + "Extract structured information precisely. Use JSON format when appropriate. Cite sources.",
        "summarization": base + "Provide comprehensive summaries. Cover all key points from the context. Cite sources.",
    }

    return prompts.get(task, prompts["general_qa"])


def _build_context(chunks: list[RetrievedChunk]) -> str:
    """Format retrieved chunks into a context string."""
    parts: list[str] = []
    for chunk in chunks:
        c = chunk.chunk
        header = f"[{c.chunk_id}] (page {c.page_number}, type: {c.chunk_type.value})"
        parts.append(f"{header}\n{c.content}")
    return "\n\n---\n\n".join(parts)


def _extract_and_format_citations(answer: str, chunks: list[RetrievedChunk]) -> tuple[list[Citation], str]:
    """Extract chunk IDs, replace with readable footnotes, and append a source list."""
    import re

    citations: list[Citation] = []
    cited_ids: list[str] = []

    # Find all unique cited chunk IDs in order of appearance
    for match in re.finditer(r"\[([a-f0-9_]+(?:_chunk_\d+)?)\]", answer):
        chunk_id = match.group(1)
        if chunk_id not in cited_ids:
            cited_ids.append(chunk_id)

    clean_answer = answer
    sources_text: list[str] = []

    for idx, chunk_id in enumerate(cited_ids, 1):
        # Find the actual chunk
        chunk = next((c for c in chunks if c.chunk.chunk_id == chunk_id), None)
        if chunk:
            citations.append(Citation(
                chunk_id=chunk_id,
                source_file=chunk.chunk.source_file,
                page_number=chunk.chunk.page_number,
                relevance_score=chunk.score,
            ))
            # Replace all occurrences of [chunk_id] with [idx]
            clean_answer = clean_answer.replace(f"[{chunk_id}]", f"[{idx}]")

            # Add to sources list
            page_text = f" (Page {chunk.chunk.page_number})" if chunk.chunk.page_number else ""
            sources_text.append(f"[{idx}] {chunk.chunk.source_file}{page_text}")

    if sources_text:
        clean_answer += "\n\n**Sources:**\n" + "\n".join(sources_text)

    return citations, clean_answer

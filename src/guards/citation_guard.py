"""RAG Citation & Grounding Guard (Strictly Lightweight, Zero-Cost Shadow Mode).

Verifies citation validity and claim grounding using fast in-memory token/set operations.
CRITICAL CONSTRAINT: ZERO LLM calls. Pure Python string/set operations (< 1ms).
"""

from __future__ import annotations

import re
import time
from typing import Any

from src.models.trace import GuardResult
from src.utils.error_classification import FailureCategory
from src.utils.feature_flags import is_feature_enabled

_CITATION_RE = re.compile(r"\[(?:Chunk|Doc)-([a-zA-Z0-9_\-]+)\]", re.IGNORECASE)
_STOP_WORDS = frozenset({
    "a", "an", "the", "in", "on", "at", "to", "for", "of", "with", "by", "from",
    "is", "are", "was", "were", "be", "been", "being", "have", "has", "had",
    "and", "or", "but", "not", "as", "if", "that", "this", "these", "those",
    "it", "its", "they", "their", "we", "our", "you", "your", "what", "which",
    "who", "whom", "whose", "when", "where", "why", "how", "according",
})


def _tokenize(text: str) -> set[str]:
    """Tokenize and filter stop words from text."""
    words = re.findall(r"\b[a-zA-Z0-9_\-\.%]+\b", text.lower())
    return {w for w in words if w not in _STOP_WORDS and len(w) > 1}


def evaluate_rag_citations(
    answer: str,
    retrieved_chunks: list[dict[str, Any]] | list[Any],
    citations: list[str] | None = None,
    enforce: bool | None = None,
) -> GuardResult:
    """Lightweight deterministic verification of RAG citations and grounding in < 1ms."""
    t0 = time.perf_counter()
    if enforce is None:
        enforce = is_feature_enabled("guard_rag_citation_enforce")
    mode = "ENFORCED" if enforce else "SHADOW"

    if not answer or not answer.strip():
        latency_ms = (time.perf_counter() - t0) * 1000
        return GuardResult(
            guard_name="rag_citation",
            passed=True,
            mode=mode,
            message="Empty answer; skipped citation check",
            latency_ms=round(latency_ms, 3),
        )

    # 1. Map retrieved chunks by ID
    chunk_map: dict[str, str] = {}
    for c in retrieved_chunks:
        if isinstance(c, dict):
            cid = str(c.get("id") or c.get("chunk_id") or "")
            text = str(c.get("text") or c.get("content") or "")
        else:
            cid = str(getattr(c, "id", "") or getattr(c, "chunk_id", ""))
            text = str(getattr(c, "text", "") or getattr(c, "content", ""))
        if cid:
            chunk_map[cid] = text

    # Extract inline citations and combine with explicit list
    inline_ids = _CITATION_RE.findall(answer)
    declared_citations = list(citations or []) + inline_ids

    # 2. If no chunks were retrieved, citations are not expected
    if not chunk_map and not declared_citations:
        latency_ms = (time.perf_counter() - t0) * 1000
        return GuardResult(
            guard_name="rag_citation",
            passed=True,
            mode=mode,
            message="No RAG retrieval in query path; guard bypassed",
            latency_ms=round(latency_ms, 3),
        )

    # 3. Check for hallucinated chunk IDs
    if declared_citations and chunk_map:
        hallucinated = [cid for cid in declared_citations if cid not in chunk_map]
        if hallucinated:
            latency_ms = (time.perf_counter() - t0) * 1000
            return GuardResult(
                guard_name="rag_citation",
                passed=False,
                mode=mode,
                failure_category=FailureCategory.CITATION_MISMATCH.value,
                message=f"Answer cites chunk IDs {hallucinated} which do not exist in retrieved chunk set",
                latency_ms=round(latency_ms, 3),
                metadata={"hallucinated_citations": hallucinated, "valid_chunks": list(chunk_map.keys())},
            )

    # 4. Token Overlap Grounding Check (between answer sentences and cited chunks)
    answer_tokens = _tokenize(answer)
    all_chunk_tokens: set[str] = set()
    for text in chunk_map.values():
        all_chunk_tokens.update(_tokenize(text))

    if chunk_map and answer_tokens:
        overlap = answer_tokens & all_chunk_tokens
        # Jaccard / Overlap coefficient against answer keywords
        overlap_ratio = len(overlap) / len(answer_tokens) if answer_tokens else 1.0

        if overlap_ratio < 0.10 and len(answer_tokens) >= 8:
            latency_ms = (time.perf_counter() - t0) * 1000
            return GuardResult(
                guard_name="rag_citation",
                passed=False,
                mode=mode,
                failure_category=FailureCategory.UNSUPPORTED_ANSWER_CLAIM.value,
                message=f"Answer keywords have low overlap ({round(overlap_ratio*100, 1)}%) with retrieved chunk context",
                latency_ms=round(latency_ms, 3),
                metadata={"overlap_ratio": round(overlap_ratio, 3), "overlap_token_count": len(overlap)},
            )

    latency_ms = (time.perf_counter() - t0) * 1000
    return GuardResult(
        guard_name="rag_citation",
        passed=True,
        mode=mode,
        message="Citations successfully verified against retrieved chunk set with valid token overlap",
        latency_ms=round(latency_ms, 3),
        metadata={"cited_count": len(declared_citations), "chunk_count": len(chunk_map)},
    )

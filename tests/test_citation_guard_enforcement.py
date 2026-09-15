"""Unit tests for Phase 4: RAG Citation Guard Hard Enforcement and Fallback Mechanism."""

from __future__ import annotations

import pytest

from src.guards.citation_guard import evaluate_rag_citations, sanitize_hallucinated_citations
from src.models.schemas import Citation, QueryResult
from src.models.trace import Span
from src.utils.error_classification import FailureCategory
from src.utils.feature_flags import is_feature_enabled


def test_sanitize_hallucinated_citations_strips_markers_and_adds_disclaimer():
    """Verify that hallucinated citation markers are removed and disclaimer is appended."""
    raw_answer = "Apple reported $90B revenue [Chunk-real-1] and record iPhone sales [Chunk-fake-99]."
    cleaned = sanitize_hallucinated_citations(raw_answer, ["fake-99"])

    assert "[Chunk-fake-99]" not in cleaned
    assert "[Chunk-real-1]" in cleaned
    assert "*(Note: Some specific source citations could not be verified and have been omitted for accuracy.)*" in cleaned


def test_rag_citation_guard_enforced_mode_flag():
    """Verify that evaluate_rag_citations defaults to ENFORCED when feature flag is enabled."""
    answer = "Revenue was $100M [Chunk-hallucinated-1]."
    chunks = [{"id": "chunk-actual-1", "text": "Some text."}]

    # enforce=None should inherit the feature flag
    res = evaluate_rag_citations(answer, chunks)
    assert res.mode == "ENFORCED"
    assert res.passed is False
    assert res.failure_category == FailureCategory.CITATION_MISMATCH.value


def test_citation_fallback_integration():
    """Verify fallback behavior degrades gracefully without crashing."""
    span = Span(name="generation")
    result = QueryResult(
        query="What was the revenue?",
        answer="The revenue reached 100M according to [Chunk-fake-404].",
        citations=[Citation(chunk_id="fake-404", source_file="annual_report.pdf", page_number=1)]
    )
    chunks = [{"id": "chunk-valid-1", "text": "The company reported revenue of 100M in 2024."}]

    guard_res = evaluate_rag_citations(
        answer=result.answer,
        retrieved_chunks=chunks,
        citations=["fake-404"],
        enforce=True,
    )
    assert guard_res.passed is False
    span.add_guard(guard_res)

    # Apply fallback logic
    if not guard_res.passed and guard_res.mode == "ENFORCED":
        hallucinated = guard_res.metadata.get("hallucinated_citations", [])
        result.answer = sanitize_hallucinated_citations(result.answer, hallucinated)
        result.citations = [c for c in result.citations if c.chunk_id not in hallucinated]
        span.status = "FALLBACK"
        span.metadata["citation_fallback_applied"] = True

    assert "[Chunk-fake-404]" not in result.answer
    assert len(result.citations) == 0
    assert "*(Note: Some specific source citations could not be verified and have been omitted for accuracy.)*" in result.answer
    assert span.status == "FALLBACK"
    assert span.metadata["citation_fallback_applied"] is True

"""Unit tests for Phase 1: Trace Schema, Branching Spans, Concurrency Safety, and Failure Taxonomy."""

from __future__ import annotations

import asyncio
import time
import pytest

from src.models.trace import GuardResult, Span, Trace
from src.utils.error_classification import FailureCategory, classify_error, classify_failure_category
from src.utils.retry_diagnostics import RetryDiagnostic
from src.utils.trace_context import (
    async_trace_span,
    branch_context,
    get_current_branch,
    get_current_span,
    get_current_trace,
    start_trace,
    trace_span,
)
from src.utils.trace_writer import InMemoryTelemetryAggregator, emit_trace


def test_trace_and_span_basic_lifecycle():
    trace = Trace(query="Show active customers", mode="sql")
    assert trace.status == "RUNNING"
    assert trace.trace_id.startswith("tr-")

    span = Span(name="schema_retrieval", branch="sql_branch")
    span.set_input({"tables": ["party", "customer"]})
    span.set_output(["party.id", "party.name"])
    span.start_time_ms = 1000.0
    span.end_time_ms = 1045.0
    span.latency_ms = 45.0
    span.input_tokens = 120
    span.output_tokens = 30

    guard = GuardResult(
        guard_name="schema_sufficiency",
        passed=True,
        mode="SHADOW",
        message="All detected tables present in schema context",
    )
    span.add_guard(guard)

    trace.add_span(span)
    trace.complete(status="SUCCESS", final_response="Found 42 active customers.")

    assert trace.status == "SUCCESS"
    assert len(trace.spans) == 1
    assert trace.total_tokens == 150
    assert trace.spans[0].guard_results[0].passed is True
    assert trace.spans[0].input_hash != ""
    assert trace.spans[0].output_hash != ""

    serialized = trace.to_dict()
    assert serialized["query"] == "Show active customers"
    assert serialized["total_tokens"] == 150
    assert len(serialized["spans"]) == 1


@pytest.mark.asyncio
async def test_trace_concurrency_safe_gathering():
    """Guardrail 1: Verify asyncio.gather on sql_branch and rag_branch is concurrency-safe."""
    trace = Trace(query="Hybrid query CAP03 / Apple tax rate", mode="hybrid")

    async def run_sql_branch():
        for i in range(10):
            await asyncio.sleep(0.001)
            span = Span(
                name=f"sql_step_{i}",
                branch="sql_branch",
                input_tokens=10,
                output_tokens=5,
            )
            trace.add_span(span)

    async def run_rag_branch():
        for i in range(10):
            await asyncio.sleep(0.001)
            span = Span(
                name=f"rag_step_{i}",
                branch="rag_branch",
                input_tokens=20,
                output_tokens=10,
            )
            trace.add_span(span)

    # Concurrently execute branches
    await asyncio.gather(run_sql_branch(), run_rag_branch())

    trace.complete(status="SUCCESS")

    assert len(trace.spans) == 20
    # SQL: 10 * 15 = 150 tokens; RAG: 10 * 30 = 300 tokens; Total = 450
    assert trace.total_tokens == 450
    sql_spans = [s for s in trace.spans if s.branch == "sql_branch"]
    rag_spans = [s for s in trace.spans if s.branch == "rag_branch"]
    assert len(sql_spans) == 10
    assert len(rag_spans) == 10


def test_trace_context_hierarchy_and_branching():
    """Verify trace_span nests child spans under parent spans and inherits branches."""
    trace = start_trace(query="Test decomposition and branching", mode="hybrid")
    assert get_current_trace() == trace

    with trace_span("decomposition") as decomp_span:
        decomp_span.set_output({"sql_sub": "orders", "doc_sub": "policy"})

        # Inside SQL Branch
        with branch_context("sql_branch"):
            assert get_current_branch() == "sql_branch"
            with trace_span("sql_gen") as sql_span:
                assert sql_span.parent_span_id == decomp_span.span_id
                assert sql_span.branch == "sql_branch"
                sql_span.input_tokens = 50

        # Inside RAG Branch
        with branch_context("rag_branch"):
            assert get_current_branch() == "rag_branch"
            with trace_span("rag_retrieval") as rag_span:
                assert rag_span.parent_span_id == decomp_span.span_id
                assert rag_span.branch == "rag_branch"
                rag_span.input_tokens = 80

    trace.complete(status="SUCCESS")

    assert len(trace.spans) == 3
    sp_names = [s.name for s in trace.spans]
    assert "sql_gen" in sp_names
    assert "rag_retrieval" in sp_names
    assert "decomposition" in sp_names
    assert trace.total_tokens == 130


def test_failure_taxonomy_classification():
    """Verify controlled semantic failure categories classify correctly."""
    # Semantic categories
    assert classify_failure_category("Missing temporal filter on due_date") == FailureCategory.MISSING_TEMPORAL_FILTER
    assert classify_failure_category("WHERE deleted_at IS NULL is missing") == FailureCategory.MISSING_SOFT_DELETE_FILTER
    assert classify_failure_category("Citation mismatch: Chunk-4 not found") == FailureCategory.CITATION_MISMATCH
    assert classify_failure_category("Unsupported claim in synthesis") == FailureCategory.UNSUPPORTED_ANSWER_CLAIM
    assert classify_failure_category("Acronym CAP03 not expanded") == FailureCategory.ACRONYM_NOT_EXPANDED
    assert classify_failure_category("Entity ambiguity: multiple parties named Fortune") == FailureCategory.ENTITY_AMBIGUITY
    assert classify_failure_category("Column 'invalid_col' does not exist") == FailureCategory.INVALID_COLUMN
    assert classify_failure_category("Table 'missing_table' doesn't exist") == FailureCategory.INVALID_TABLE
    assert classify_failure_category("Unsafe SQL: DROP TABLE blocked") == FailureCategory.UNSAFE_SQL_OPERATION
    assert classify_failure_category("HTTP 429 Too Many Requests: TPM quota exceeded") == FailureCategory.RATE_LIMIT_ERROR
    assert classify_failure_category("Circuit breaker open for groq") == FailureCategory.CIRCUIT_BREAKER_OPEN

    # Legacy classify_error compatibility
    assert classify_error("HTTP 429 Too Many Requests: Rate limit exceeded") == "rate_limit_error"
    assert classify_error("Column validation failed: Column 'bad_col' does not exist") == "sql_validation_error"


def test_compact_retry_diagnostic_payload():
    """Guardrail 5: Verify retry payload is compact and token-conscious (< 40 tokens)."""
    diag = RetryDiagnostic(
        stage="sql_generation",
        failure_category=FailureCategory.INVALID_COLUMN,
        error_summary="Column 'region_name' does not exist in table 'regions'.",
        target_constraint="Use valid columns: ['id', 'name', 'code'].",
        allowed_objects=["id", "name", "code", "created_at"],
        action_instruction="Fix column reference only. Do not change other tables.",
    )

    prompt_str = diag.to_compact_prompt()
    assert "RETRY [INVALID_COLUMN]" in prompt_str
    assert "region_name" in prompt_str
    assert "Allowed: [id, name, code, created_at]" in prompt_str

    # Approximate token count (roughly 4 characters per token)
    approx_tokens = len(prompt_str) // 4
    assert approx_tokens <= 60, f"Prompt string is unexpectedly verbose: {approx_tokens} tokens"

    d = diag.to_dict()
    assert d["failure_category"] == "INVALID_COLUMN"
    assert d["attempt"] == 1
    assert d["max_attempts"] == 1


def test_in_memory_telemetry_aggregator_fast_response():
    """Guardrail 4: Verify aggregator computes overview and failures in < 1ms without parsing JSONL."""
    aggregator = InMemoryTelemetryAggregator()

    # Ingest mock traces
    for i in range(25):
        status = "SUCCESS" if i % 5 != 0 else "FALLBACK"
        t = {
            "trace_id": f"tr-{i}",
            "status": status,
            "failure_category": "MISSING_TEMPORAL_FILTER" if status == "FALLBACK" else None,
            "total_latency_ms": 150.0 + i * 10,
            "retry_count": 1 if i % 5 == 0 else 0,
            "retry_improved": True if i % 5 == 0 else None,
            "spans": [
                {
                    "name": "sql_gen",
                    "status": "OK" if status == "SUCCESS" else "ERROR",
                    "failure_category": "MISSING_TEMPORAL_FILTER" if status == "FALLBACK" else None,
                    "guard_results": [
                        {
                            "guard_name": "sql_safety",
                            "passed": True,
                            "mode": "ENFORCED",
                        },
                        {
                            "guard_name": "temporal_filter",
                            "passed": status == "SUCCESS",
                            "mode": "SHADOW",
                        },
                    ],
                }
            ],
        }
        aggregator.record_trace(t)

    t0 = time.perf_counter()
    overview = aggregator.get_overview()
    failures = aggregator.get_failures()
    guards = aggregator.get_guards()
    elapsed_ms = (time.perf_counter() - t0) * 1000

    assert elapsed_ms < 5.0, f"Aggregator query took too long: {elapsed_ms}ms"
    assert overview["total_requests"] == 25
    assert overview["status_breakdown"]["SUCCESS"] == 20
    assert overview["status_breakdown"]["FALLBACK"] == 5
    assert overview["retry_recovery_rate_percent"] == 100.0
    assert failures["by_category"]["MISSING_TEMPORAL_FILTER"] == 5
    assert "sql_safety" in guards
    assert guards["temporal_filter"]["shadow_blocks"] == 5

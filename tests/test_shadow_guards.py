"""Unit tests for Phase 3 Shadow Guards (Temporal, Schema Sufficiency, and RAG Citation)."""

from __future__ import annotations

import time
import pytest

from src.guards.citation_guard import evaluate_rag_citations
from src.guards.schema_guard import evaluate_schema_sufficiency
from src.guards.temporal_guard import evaluate_temporal_filter, has_temporal_intent
from src.utils.error_classification import FailureCategory


# --- Temporal Filter Guard Tests ---

def test_temporal_guard_detects_intent():
    assert has_temporal_intent("Show active sales orders that were overdue as of 2025-06-01") is True
    assert has_temporal_intent("List purchases created between 2025-01-01 and 2025-03-31") is True
    assert has_temporal_intent("Stock adjustments recorded on 2025-06-03") is True
    assert has_temporal_intent("Count active categories") is False
    assert has_temporal_intent("Show list of suppliers") is False


def test_temporal_guard_passes_when_filter_present():
    query = "Show active sales orders that were overdue as of 2025-06-01"
    sql = "SELECT * FROM sales_order WHERE due_date <= '2025-06-01' AND deleted_at IS NULL;"
    res = evaluate_temporal_filter(query, sql)

    assert res.passed is True
    assert res.mode == "SHADOW"
    assert res.guard_name == "sql_temporal"


def test_temporal_guard_flags_missing_filter():
    query = "Show active sales orders that were overdue as of 2025-06-01"
    sql = "SELECT * FROM sales_order WHERE deleted_at IS NULL;"  # Missing date predicate
    res = evaluate_temporal_filter(query, sql)

    assert res.passed is False
    assert res.failure_category == FailureCategory.MISSING_TEMPORAL_FILTER.value
    assert res.mode == "SHADOW"


def test_temporal_guard_bypasses_non_temporal_query():
    query = "Count active categories"
    sql = "SELECT COUNT(*) FROM category WHERE deleted_at IS NULL;"
    res = evaluate_temporal_filter(query, sql)

    assert res.passed is True
    assert "bypassed" in res.message


# --- Schema Sufficiency Guard Tests ---

def test_schema_guard_passes_when_tables_present():
    query = "Delivery challans for Fortune Packaging"
    schema = "CREATE TABLE delivery_challan (id INT); CREATE TABLE party (id INT, party_name VARCHAR(100));"
    res = evaluate_schema_sufficiency(query, schema)

    assert res.passed is True
    assert res.guard_name == "schema_sufficiency"
    assert res.mode == "SHADOW"


def test_schema_guard_flags_missing_table():
    query = "Show warehouses in northern zone"
    schema = "CREATE TABLE sales_order (id INT); CREATE TABLE product (id INT);"  # warehouse missing!
    res = evaluate_schema_sufficiency(query, schema)

    assert res.passed is False
    assert res.failure_category == FailureCategory.SCHEMA_RETRIEVAL_MISS.value
    assert "warehouse" in res.metadata["missing_tables"]


# --- RAG Citation Guard Tests ---

def test_rag_citation_guard_passes_grounded_answer():
    answer = "According to Apple's 10-K filing [Chunk-apple-10k-1], the effective tax rate was 14.7% for fiscal year 2023."
    chunks = [
        {
            "id": "apple-10k-1",
            "text": "The effective tax rate in fiscal 2023 was 14.7% compared to 16.2% in fiscal 2022 due to foreign tax rate differentials.",
        }
    ]
    res = evaluate_rag_citations(answer, chunks)

    assert res.passed is True
    assert res.guard_name == "rag_citation"
    assert res.mode in ("SHADOW", "ENFORCED")


def test_rag_citation_guard_flags_hallucinated_chunk():
    answer = "The company reported record quarterly revenues of $90B [Chunk-fake-99]."
    chunks = [{"id": "chunk-real-1", "text": "Apple reported revenue."}]
    res = evaluate_rag_citations(answer, chunks)

    assert res.passed is False
    assert res.failure_category == FailureCategory.CITATION_MISMATCH.value
    assert "fake-99" in res.metadata["hallucinated_citations"]


def test_rag_citation_guard_flags_low_overlap():
    answer = "The enterprise deployed seventeen nuclear reactors across the solar system for cryogenic quantum supercomputers."
    chunks = [{"id": "chunk-1", "text": "Annual report details software subscription revenue models and customer renewal rates."}]
    res = evaluate_rag_citations(answer, chunks, citations=["chunk-1"])

    assert res.passed is False
    assert res.failure_category == FailureCategory.UNSUPPORTED_ANSWER_CLAIM.value


# --- Latency Budget Test (< 5ms) ---

def test_shadow_guards_latency_budget():
    """Directive 2: Verify all shadow guards execute in < 5ms without LLM or disk I/O."""
    # Warm up to eliminate one-time sqlglot dialect table and regex JIT overhead
    evaluate_temporal_filter("orders in 2025", "SELECT * FROM sales_order WHERE due_date <= '2025-01-01';")
    evaluate_schema_sufficiency("orders", "CREATE TABLE sales_order (id INT);")
    evaluate_rag_citations("answer [Chunk-1]", [{"id": "Chunk-1", "text": "answer"}])

    query = "Show active sales orders that were overdue as of 2025-06-01"
    sql = "SELECT * FROM sales_order WHERE due_date <= '2025-06-01' AND deleted_at IS NULL;"
    schema = "CREATE TABLE sales_order (id INT, due_date DATE, deleted_at DATETIME);"
    answer = "Overdue sales orders were filtered by due date [Chunk-1]."
    chunks = [{"id": "Chunk-1", "text": "Sales orders overdue date."}]

    t0 = time.perf_counter()
    res1 = evaluate_temporal_filter(query, sql)
    res2 = evaluate_schema_sufficiency(query, schema)
    res3 = evaluate_rag_citations(answer, chunks)
    total_ms = (time.perf_counter() - t0) * 1000

    assert total_ms < 5.0, f"Shadow guards exceeded 5ms latency budget: {total_ms}ms"
    assert res1.latency_ms < 3.0
    assert res2.latency_ms < 2.0
    assert res3.latency_ms < 3.0

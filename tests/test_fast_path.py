"""Tests for Layer 2: Fast-Path Execution & Synthesis Bypass (COUNT, SUM, LIST, Circuit Breaker)."""

from __future__ import annotations

import re
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from src.core.provider_client import ProviderRouter
from src.models.schemas import Chunk, ChunkType, DocumentType, RetrievedChunk
from src.stages.s12_s13_s14_retrieval import Generator
from src.utils.fast_path import (
    DISABLED_TEMPLATES,
    FAIL_RATE_THRESHOLD,
    _fail_counters,
    build_aggregate_micro_prompt,
    fast_path_format,
    format_aggregate_fast_path,
    format_list_fast_path,
    is_pure_factual,
    is_template_enabled,
)
from src.utils.query_classifier import QueryType


def extract_numbers(text: str) -> list[float]:
    """Extract all numerical values from text for factual equivalence testing."""
    clean = text.replace(",", "")
    matches = re.findall(r"[-+]?\d*\.?\d+", clean)
    return [float(m) for m in matches if m]


def assert_factual_equivalent(template_output: str, llm_output: str) -> None:
    """Assert that template output and LLM output contain equivalent numeric data."""
    t_nums = set(extract_numbers(template_output))
    l_nums = set(extract_numbers(llm_output))
    assert t_nums == l_nums, f"Factual mismatch: template nums {t_nums} != llm nums {l_nums}"


def test_fast_path_formatters():
    """Test 1: Formatters produce clean markdown output."""
    table_md = "| id | name |\n|---|---|\n| 1 | Acme |"

    # List formatter
    list_res = format_list_fast_path(table_md)
    assert "Here are the records matching your request:" in list_res
    assert table_md in list_res

    # Micro prompt builder
    messages = build_aggregate_micro_prompt("What is total sales?", table_md)
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert "single-sentence summary" in messages[0]["content"]
    assert table_md in messages[1]["content"]

    # Aggregate formatter
    agg_res = format_aggregate_fast_path("Total sales reached $500,000.", table_md)
    assert "Total sales reached $500,000.\n\n" in agg_res
    assert table_md in agg_res


def test_count_template_formatting():
    table_md = "| count |\n|:---|\n| 1500 |"
    res = fast_path_format(QueryType.COUNT, table_md, "How many delivery challans are there?")
    assert res is not None
    assert "There are 1,500 delivery challans." in res
    assert_factual_equivalent(res, "The database reports a total count of 1500 delivery challans.")


def test_sum_template_formatting():
    table_md = "| total_amount |\n|:---|\n| 52450.75 |"
    res = fast_path_format(QueryType.SUM, table_md, "What is the total invoice amount for customer?")
    assert res is not None
    assert "The total invoice amount is 52,450.75." in res
    assert_factual_equivalent(res, "According to records, total invoice amount equals 52450.75.")


def test_disqualifiers_route_to_llm():
    table_md = "| count |\n|:---|\n| 12 |"
    # Contains contextual disqualifiers: "due to", "why", "compared to"
    assert is_pure_factual("How many customers had issues due to the billing policy?") is False
    assert fast_path_format(QueryType.COUNT, table_md, "How many customers had issues due to the billing policy?") is None

    assert is_pure_factual("Why did total production drop compared to last month?") is False
    assert fast_path_format(QueryType.COUNT, table_md, "Why did total production drop compared to last month?") is None


def test_circuit_breaker_and_manual_override(monkeypatch):
    _fail_counters.clear()
    assert is_template_enabled(QueryType.COUNT) is True

    # Simulate 50 trials with 2 failures (4% failure rate > 1%)
    _fail_counters[QueryType.COUNT] = (2, 50)
    assert is_template_enabled(QueryType.COUNT) is False

    # Reset
    _fail_counters.clear()

    # Manual override test
    monkeypatch.setattr("src.utils.fast_path.DISABLED_TEMPLATES", {QueryType.SUM})
    assert is_template_enabled(QueryType.SUM) is False
    assert is_template_enabled(QueryType.COUNT) is True


@pytest.mark.asyncio
async def test_list_query_bypasses_synthesis_llm():
    """Test: list_query with fast_path_enabled calls LLM zero times."""
    mock_router = MagicMock(spec=ProviderRouter)
    mock_router.usage = MagicMock(model_copy=MagicMock(return_value={}))
    mock_router.last_used = "mock-model"

    generator = Generator(router=mock_router)

    table_chunk = RetrievedChunk(
        chunk=Chunk(
            chunk_id="sql_1",
            document_id="live_db",
            chunk_type=ChunkType.SQL_RESULT,
            content="SQL Query Executed: `SELECT * FROM customers`\n\n| id | name |\n|---|---|\n| 1 | Acme Corp |",
            document_type=DocumentType.GENERAL,
        ),
        score=1.0,
    )

    with patch("src.stages.s12_s13_s14_retrieval.is_feature_enabled", return_value=True):
        result = await generator.generate(
            query="list all customers",
            chunks=[table_chunk],
        )

        assert "Acme Corp" in result.answer
        assert "Here are the records matching your request" in result.answer
        assert mock_router.chat.call_count == 0


@pytest.mark.asyncio
async def test_aggregate_query_uses_micro_prompt():
    """Test: aggregate_query uses fast path or micro synthesis."""
    mock_router = MagicMock(spec=ProviderRouter)
    mock_router.usage = MagicMock(model_copy=MagicMock(return_value={}))
    mock_router.last_used = "mock-model"
    mock_router.chat = AsyncMock(return_value="Total customers active: 100.")

    generator = Generator(router=mock_router)

    table_chunk = RetrievedChunk(
        chunk=Chunk(
            chunk_id="sql_1",
            document_id="live_db",
            chunk_type=ChunkType.SQL_RESULT,
            content="SQL Query Executed: `SELECT COUNT(*) FROM customers`\n\n| count |\n|:---|\n| 100 |",
            document_type=DocumentType.GENERAL,
        ),
        score=1.0,
    )

    with patch("src.stages.s12_s13_s14_retrieval.is_feature_enabled", return_value=True):
        result = await generator.generate(
            query="how many customers are there?",
            chunks=[table_chunk],
        )

        assert "100" in result.answer
        assert "There are 100 customers." in result.answer
        assert mock_router.chat.call_count == 0  # 0 LLM calls!

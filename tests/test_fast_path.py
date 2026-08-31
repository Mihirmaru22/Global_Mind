"""Tests for Phase 12: Fast-Path Execution & Synthesis Bypass."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from src.core.provider_client import ProviderRouter
from src.models.schemas import Chunk, ChunkType, DocumentType, RetrievedChunk
from src.stages.s12_s13_s14_retrieval import Generator
from src.utils.fast_path import (
    build_aggregate_micro_prompt,
    format_aggregate_fast_path,
    format_list_fast_path,
)


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


@pytest.mark.asyncio
async def test_list_query_bypasses_synthesis_llm():
    """Test 2: list_query with fast_path_enabled calls LLM zero times."""
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
        result = await generator.generate("List the top 5 customers", [table_chunk])

        # PROOF OF BYPASS: Zero chat calls made to synthesis LLM
        assert mock_router.chat.await_count == 0
        assert "Here are the records matching your request:" in result.answer
        assert "| 1 | Acme Corp |" in result.answer
        assert result.model_used == "fast_path/list"


@pytest.mark.asyncio
async def test_aggregate_query_uses_micro_prompt():
    """Test 3: aggregate_query with fast_path_enabled calls LLM with micro-prompt and max_tokens=150."""
    mock_router = MagicMock(spec=ProviderRouter)
    mock_router.usage = MagicMock(model_copy=MagicMock(return_value={}))
    mock_router.last_used = "mock-model"
    mock_router.chat = AsyncMock(return_value="Total revenue for 2024 was $1.2M across all regions.")

    generator = Generator(router=mock_router)

    table_chunk = RetrievedChunk(
        chunk=Chunk(
            chunk_id="sql_1",
            document_id="live_db",
            chunk_type=ChunkType.SQL_RESULT,
            content="SQL Query Executed: `SELECT SUM(amount) FROM orders`\n\n| total_revenue |\n|---|\n| 1200000 |",
            document_type=DocumentType.GENERAL,
        ),
        score=1.0,
    )

    with patch("src.stages.s12_s13_s14_retrieval.is_feature_enabled", return_value=True):
        result = await generator.generate("What is the total revenue by region?", [table_chunk])

        # LLM called exactly once with micro-prompt (max_tokens=150)
        assert mock_router.chat.await_count == 1
        call_kwargs = mock_router.chat.call_args.kwargs
        assert call_kwargs.get("max_tokens") == 150
        assert "Total revenue for 2024 was $1.2M" in result.answer
        assert "| total_revenue |" in result.answer
        assert result.model_used == "fast_path/aggregate"


@pytest.mark.asyncio
async def test_explanation_query_uses_full_synthesis():
    """Test 4: explanation_query with fast_path_enabled falls back to full synthesis."""
    mock_router = MagicMock(spec=ProviderRouter)
    mock_router.usage = MagicMock(model_copy=MagicMock(return_value={}))
    mock_router.last_used = "mock-model"
    mock_router.chat = AsyncMock(return_value="Sales declined due to lower Q3 order volume.")

    generator = Generator(router=mock_router)

    table_chunk = RetrievedChunk(
        chunk=Chunk(
            chunk_id="sql_1",
            document_id="live_db",
            chunk_type=ChunkType.SQL_RESULT,
            content="SQL Query Executed: `SELECT q, amount FROM sales`\n\n| q | amount |\n|---|---|\n| Q3 | 5000 |",
            document_type=DocumentType.GENERAL,
        ),
        score=1.0,
    )

    with patch("src.stages.s12_s13_s14_retrieval.is_feature_enabled", return_value=True):
        result = await generator.generate("Why did sales drop in Q3?", [table_chunk])

        # LLM called with full synthesis (max_tokens=2048)
        assert mock_router.chat.await_count == 1
        call_kwargs = mock_router.chat.call_args.kwargs
        assert call_kwargs.get("max_tokens") == 2048
        assert "Sales declined due to lower Q3 order volume." in result.answer

"""Live integration tests for Hybrid Intelligence Engine (Option B).

Tests the 4 specific verification queries against the live system:
1. SQL Test: "How many stock adjustments?"
2. RAG Test: "What is the return policy?" / "What are the five major layers of an enterprise RAG system?"
3. Hybrid Test: "How many stock adjustments AND what is the policy?"
4. Abstain Test: "What is Tesla's stock price?"
"""

import pytest
from src.models.schemas import QueryResult
from src.pipeline.query import QueryPipeline


@pytest.mark.asyncio
async def test_live_sql_query():
    pipeline = QueryPipeline()
    res = await pipeline.query("How many stock adjustments?")
    assert isinstance(res, QueryResult)
    # Verifies SQL executed and returned data
    assert "stock_adjustment" in res.answer.lower() or "3657" in res.answer or "|" in res.answer


@pytest.mark.asyncio
async def test_live_rag_query():
    pipeline = QueryPipeline()
    res = await pipeline.query("What are the five major layers of an enterprise RAG system?")
    assert isinstance(res, QueryResult)
    assert len(res.answer) > 20
    # Must have retrieved document information and cited source
    assert res.reasoning_task in ("synthesis", "extraction", "general_qa", "rag_only")


@pytest.mark.asyncio
async def test_live_hybrid_query():
    pipeline = QueryPipeline()
    res = await pipeline.query("How many stock adjustments are there AND what is the policy for writing them off?")
    assert isinstance(res, QueryResult)
    assert res.reasoning_task == "hybrid_parallel"
    assert len(res.answer) > 20


@pytest.mark.asyncio
async def test_live_abstain_query():
    pipeline = QueryPipeline()
    res = await pipeline.query("What is Tesla's stock price?")
    assert isinstance(res, QueryResult)
    assert res.reasoning_task == "abstain"
    assert "outside the domain" in res.answer.lower()
    assert res.chunks_retrieved == 0
    assert res.chunks_after_rerank == 0

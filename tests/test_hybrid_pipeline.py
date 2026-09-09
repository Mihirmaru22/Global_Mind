"""Unit and integration tests for Hybrid Intelligence Engine (Option B)."""

import pytest
from unittest.mock import AsyncMock, patch

from src.models.schemas import QueryResult, Chunk, RetrievedChunk, ChunkType, DocumentType, TokenUsage
from src.pipeline.query import QueryPipeline


@pytest.fixture
def mock_pipeline():
    router = AsyncMock()
    router.last_used = "mock/model"
    router.usage = TokenUsage()
    store = AsyncMock()
    embeddings = AsyncMock()

    pipeline = QueryPipeline(
        router=router,
        vector_store=store,
        embedding_service=embeddings,
    )
    pipeline._force_hybrid_routing = True
    return pipeline


@pytest.mark.asyncio
async def test_classify_intent_parses_json(mock_pipeline):
    mock_pipeline._router.chat = AsyncMock(
        return_value='{"route_type": "SQL_ONLY", "confidence_score": 0.98, "sql_intent": {"needed": true}}'
    )
    intent = await mock_pipeline._classify_intent("How many stock adjustments?")
    assert intent["route_type"] == "SQL_ONLY"
    assert intent["confidence_score"] == 0.98


@pytest.mark.asyncio
async def test_classify_intent_handles_markdown_blocks(mock_pipeline):
    mock_pipeline._router.chat = AsyncMock(
        return_value='```json\n{"route_type": "RAG_ONLY", "confidence_score": 0.95}\n```'
    )
    intent = await mock_pipeline._classify_intent("What is the return policy?")
    assert intent["route_type"] == "RAG_ONLY"
    assert intent["confidence_score"] == 0.95


@pytest.mark.asyncio
async def test_classify_intent_fallback_on_invalid_json(mock_pipeline):
    mock_pipeline._router.chat = AsyncMock(return_value="not a json response")
    intent = await mock_pipeline._classify_intent("What is our general policy?")
    assert intent["route_type"] in ("HYBRID_PARALLEL", "SQL_ONLY")
    assert intent["confidence_score"] == 0.5


@pytest.mark.asyncio
async def test_abstain_branch_returns_zero_retrieval(mock_pipeline):
    mock_pipeline._classify_intent = AsyncMock(return_value={"route_type": "ABSTAIN", "confidence_score": 0.99})
    mock_pipeline._sql_retriever.retrieve = AsyncMock()
    mock_pipeline._retriever.retrieve = AsyncMock()

    result = await mock_pipeline.query("What is Tesla's stock price?")

    assert isinstance(result, QueryResult)
    assert result.reasoning_task == "abstain"
    assert "outside the domain" in result.answer
    assert mock_pipeline._sql_retriever.retrieve.await_count == 0
    assert mock_pipeline._retriever.retrieve.await_count == 0


@pytest.mark.asyncio
async def test_sql_only_branch_bypasses_vector_retrieval(mock_pipeline):
    sql_chunk = RetrievedChunk(
        chunk=Chunk(
            chunk_id="sql_1",
            document_id="live_db",
            content="| count |\n| --- |\n| 42 |",
            chunk_type=ChunkType.SQL_RESULT,
            page_number=0,
            document_type=DocumentType.GENERAL,
            source_file="live_database",
        ),
        score=1.0,
        retrieval_method="text-to-sql",
    )
    mock_pipeline._classify_intent = AsyncMock(return_value={"route_type": "SQL_ONLY", "confidence_score": 0.98})
    mock_pipeline._sql_retriever.retrieve = AsyncMock(return_value=[sql_chunk])
    mock_pipeline._retriever.retrieve = AsyncMock()
    mock_pipeline._reranker.rerank = AsyncMock()

    result = await mock_pipeline.query("How many stock adjustments?")

    assert isinstance(result, QueryResult)
    assert "| 42 |" in result.answer
    assert mock_pipeline._sql_retriever.retrieve.await_count == 1
    # Crucial constraint: vector search and reranker are completely bypassed
    assert mock_pipeline._retriever.retrieve.await_count == 0
    assert mock_pipeline._reranker.rerank.await_count == 0


@pytest.mark.asyncio
async def test_rag_only_branch_bypasses_sql_retrieval(mock_pipeline):
    doc_chunk = RetrievedChunk(
        chunk=Chunk(
            chunk_id="doc_1",
            document_id="doc_1",
            content="Returns are accepted within 30 days.",
            chunk_type=ChunkType.PROSE,
            page_number=1,
            document_type=DocumentType.GENERAL,
            source_file="return_policy.pdf",
        ),
        score=0.9,
    )
    mock_pipeline._classify_intent = AsyncMock(return_value={"route_type": "RAG_ONLY", "confidence_score": 0.95})
    mock_pipeline._sql_retriever.retrieve = AsyncMock()
    mock_pipeline._retriever.retrieve = AsyncMock(return_value=[doc_chunk])
    mock_pipeline._reranker.rerank = AsyncMock(return_value=[doc_chunk])
    mock_pipeline._generator.generate = AsyncMock(
        return_value=QueryResult(
            query="What is the return policy?",
            answer="Items can be returned within 30 days [Source: return_policy.pdf, Page 1].",
            citations=[],
            model_used="mock_rag",
            reasoning_task="synthesis",
        )
    )

    result = await mock_pipeline.query("What is the return policy?")

    assert isinstance(result, QueryResult)
    assert "returned within 30 days" in result.answer
    # Crucial constraint: SQL retrieval is completely bypassed
    assert mock_pipeline._sql_retriever.retrieve.await_count == 0
    assert mock_pipeline._retriever.retrieve.await_count == 1


@pytest.mark.asyncio
async def test_hybrid_parallel_executes_both_and_merges(mock_pipeline):
    sql_chunk = RetrievedChunk(
        chunk=Chunk(
            chunk_id="sql_1",
            document_id="live_db",
            content="| count |\n| --- |\n| 7 |",
            chunk_type=ChunkType.SQL_RESULT,
            page_number=0,
            document_type=DocumentType.GENERAL,
            source_file="live_database",
        ),
        score=1.0,
        retrieval_method="text-to-sql",
    )
    doc_chunk = RetrievedChunk(
        chunk=Chunk(
            chunk_id="doc_1",
            document_id="doc_1",
            content="Stock adjustments require manager approval.",
            chunk_type=ChunkType.PROSE,
            page_number=2,
            document_type=DocumentType.GENERAL,
            source_file="inventory_policy.pdf",
        ),
        score=0.88,
    )

    mock_pipeline._classify_intent = AsyncMock(return_value={"route_type": "HYBRID_PARALLEL", "confidence_score": 0.99})
    mock_pipeline._sql_retriever.retrieve = AsyncMock(return_value=[sql_chunk])
    mock_pipeline._retriever.retrieve = AsyncMock(return_value=[doc_chunk])
    mock_pipeline._reranker.rerank = AsyncMock(return_value=[doc_chunk])
    mock_pipeline._generator.generate = AsyncMock(
        return_value=QueryResult(
            query="policy",
            answer="Manager approval is required [Source: inventory_policy.pdf, Page 2].",
            citations=[],
            model_used="mock_rag",
            reasoning_task="synthesis",
        )
    )

    with patch("src.pipeline.query.merge_hybrid_responses", new_callable=AsyncMock) as mock_merger:
        mock_merger.return_value = {
            "unified_answer": "There are 7 stock adjustments recorded, and manager approval is required per policy [Source: inventory_policy.pdf, Page 2].",
            "confidence_score": 0.98,
        }

        result = await mock_pipeline.query("How many stock adjustments AND what is the policy?")

        assert isinstance(result, QueryResult)
        assert "7 stock adjustments" in result.answer
        assert "manager approval" in result.answer
        assert mock_pipeline._sql_retriever.retrieve.await_count == 1
        assert mock_pipeline._retriever.retrieve.await_count == 1
        assert mock_merger.await_count == 1


@pytest.mark.asyncio
async def test_hybrid_stream_thinking_steps(mock_pipeline):
    mock_pipeline._classify_intent = AsyncMock(return_value={"route_type": "ABSTAIN", "confidence_score": 0.99})

    chunks = []
    async for chunk in mock_pipeline.query_stream("Who won the 1994 World Cup?"):
        chunks.append(chunk)

    final = chunks[-1]
    assert isinstance(final, QueryResult)
    assert final.reasoning_task == "abstain"
    # Verify thinking steps include the classified route
    route_step = next((s for s in final.thinking if s.label == "Routing intent"), None)
    assert route_step is not None
    assert "ABSTAIN" in route_step.detail

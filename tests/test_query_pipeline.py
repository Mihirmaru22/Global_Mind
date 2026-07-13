"""Integration tests for the Query Pipeline."""

import pytest
from unittest.mock import AsyncMock

from src.models.schemas import QueryResult, Chunk, RetrievedChunk, ChunkType, DocumentType
from src.pipeline.query import QueryPipeline
from src.stages.s10_embeddings import SparseVector


@pytest.fixture
def mock_router():
    router = AsyncMock()
    
    async def mock_chat(*args, **kwargs):
        return "This is a mock answer based on the context."

    async def mock_chat_stream(*args, **kwargs):
        yield "This "
        yield "is a mock "
        yield "stream answer."

    router.chat = mock_chat
    router.chat_stream = mock_chat_stream
    # The generator reads router.last_used for QueryResult.model_used; the real
    # router sets this to a "provider/model" string once a call completes.
    router.last_used = "mock/model"
    return router


@pytest.fixture
def mock_store():
    store = AsyncMock()
    return store


@pytest.fixture
def mock_embeddings():
    service = AsyncMock()
    
    async def mock_embed_queries(queries):
        return [[0.1] * 384 for _ in queries]
        
    async def mock_embed_query(query):
        return ([0.1] * 384, SparseVector())
        
    service.embed_queries = mock_embed_queries
    service.embed_query = mock_embed_query
    return service


@pytest.mark.asyncio
async def test_query_pipeline_empty_retrieval(mock_router, mock_store, mock_embeddings):
    # Setup mock to return no chunks
    mock_store.search_hybrid = AsyncMock(return_value=[])
    
    pipeline = QueryPipeline(
        router=mock_router,
        vector_store=mock_store,
        embedding_service=mock_embeddings
    )
    
    result = await pipeline.query("What is the capital of France?")
    
    assert isinstance(result, QueryResult)
    assert result.query == "What is the capital of France?"
    assert "No relevant documents found" in result.answer
    assert result.chunks_retrieved == 0


@pytest.mark.asyncio
async def test_query_pipeline_success(mock_router, mock_store, mock_embeddings):
    # Setup mock to return some chunks
    mock_chunk = Chunk(
        chunk_id="chunk-1",
        document_id="doc-1",
        content="Paris is the capital of France.",
        chunk_type=ChunkType.PROSE,
        page_number=1,
        document_type=DocumentType.GENERAL,
        source_file="test.txt"
    )
    retrieved_chunk = RetrievedChunk(chunk=mock_chunk, score=0.9)
    mock_store.search_hybrid = AsyncMock(return_value=[retrieved_chunk])
    
    pipeline = QueryPipeline(
        router=mock_router,
        vector_store=mock_store,
        embedding_service=mock_embeddings
    )
    
    result = await pipeline.query("What is the capital of France?")
    
    assert isinstance(result, QueryResult)
    assert result.query == "What is the capital of France?"
    assert "This is a mock answer" in result.answer
    assert result.chunks_retrieved == 1
    assert result.chunks_after_rerank == 1


@pytest.mark.asyncio
async def test_query_pipeline_stream_success(mock_router, mock_store, mock_embeddings):
    # Setup mock to return some chunks
    mock_chunk = Chunk(
        chunk_id="chunk-1",
        document_id="doc-1",
        content="Paris is the capital of France.",
        chunk_type=ChunkType.PROSE,
        page_number=1,
        document_type=DocumentType.GENERAL,
        source_file="test.txt"
    )
    retrieved_chunk = RetrievedChunk(chunk=mock_chunk, score=0.9)
    mock_store.search_hybrid = AsyncMock(return_value=[retrieved_chunk])
    
    pipeline = QueryPipeline(
        router=mock_router,
        vector_store=mock_store,
        embedding_service=mock_embeddings
    )
    
    chunks = []
    async for chunk in pipeline.query_stream("What is the capital of France?"):
        chunks.append(chunk)
        
    assert len(chunks) > 0
    final_result = chunks[-1]
    
    assert isinstance(final_result, QueryResult)
    assert final_result.query == "What is the capital of France?"
    assert "stream answer" in final_result.answer
    assert final_result.chunks_retrieved == 1

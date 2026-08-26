"""Unit tests for StreamTokenCounter and stream budget circuit breaker."""

import asyncio
import pytest
from src.utils.stream_token_counter import StreamTokenCounter, TokenBudgetExceededError


def test_stream_token_counter_basic_counting():
    """Test basic chunk counting and status reporting."""
    counter = StreamTokenCounter(hard_limit=100, safety_buffer=10)
    assert counter.current_count == 0
    assert not counter.is_exceeded

    added = counter.add_chunk("SELECT * FROM party WHERE id = 1;")
    assert added > 0
    assert counter.current_count == added
    assert not counter.check_limit()


def test_dynamic_tokenizer_selection():
    """Test model/provider-aware dynamic tokenizer resolution."""
    counter_llama = StreamTokenCounter(hard_limit=1000, model_name="meta/llama-3.3-70b-instruct", provider_name="nvidia_nim")
    assert counter_llama.tokenizer_model == "o200k_base"

    counter_groq = StreamTokenCounter(hard_limit=1000, model_name="openai/gpt-oss-120b", provider_name="groq")
    assert counter_groq.tokenizer_model == "cl100k_base"


def test_stream_mock_10_chunks_interrupt_at_8k():
    """Mock a stream of 10 chunks (~1000 tokens each) and assert trigger after 8th chunk."""
    counter = StreamTokenCounter(hard_limit=8000, safety_buffer=50)

    # A chunk of repetitive text that generates approx ~1000 tokens
    unit_text = "SELECT column_a, column_b, column_c FROM large_table JOIN other_table ON id = other_id WHERE status = 'ACTIVE' "
    # Calculate repeats to hit exactly ~1000 tokens per chunk
    sample_count = len(counter._encoder.encode(unit_text))
    multiplier = 1000 // sample_count
    one_thousand_token_chunk = unit_text * multiplier

    chunks_processed = 0
    exceeded_caught = False

    for i in range(10):
        counter.add_chunk(one_thousand_token_chunk)
        chunks_processed += 1

        if counter.check_limit():
            exceeded_caught = True
            break

    # Should have processed 8 or 9 chunks before hitting limit + buffer
    assert exceeded_caught is True
    assert chunks_processed in (8, 9)
    # Total count must be bounded
    assert counter.current_count >= 8000
    assert counter.current_count <= 9100

    with pytest.raises(TokenBudgetExceededError):
        counter.raise_if_exceeded()


@pytest.mark.asyncio
async def test_async_stream_with_budget_wrapper():
    """Test async generator streaming cut and synthetic completion injection."""
    async def mock_stream_chunks():
        for i in range(10):
            yield f"CHUNK_{i}_" + ("word " * 250)  # ~250 tokens per chunk

    counter = StreamTokenCounter(hard_limit=500, safety_buffer=20)
    received_chunks = []
    stream_interrupted = False

    async for chunk in mock_stream_chunks():
        counter.add_chunk(chunk)
        received_chunks.append(chunk)

        if counter.check_limit():
            stream_interrupted = True
            # Yield final synthetic indicator
            received_chunks.append("[FINISH_REASON:LENGTH]")
            break

    assert stream_interrupted is True
    assert len(received_chunks) <= 4  # 500 tokens is reached in ~2-3 chunks + synthetic
    assert counter.current_count >= 500


@pytest.mark.asyncio
async def test_parallel_stream_counters():
    """Verify thread and async isolation when multiple StreamTokenCounter instances run concurrently."""
    counter_1 = StreamTokenCounter(hard_limit=1000, safety_buffer=50)
    counter_2 = StreamTokenCounter(hard_limit=1000, safety_buffer=50)

    async def worker(counter: StreamTokenCounter, text: str, iterations: int):
        for _ in range(iterations):
            counter.add_chunk(text)
            await asyncio.sleep(0.001)

    t1 = asyncio.create_task(worker(counter_1, "SELECT * FROM orders WHERE id = 1 ", 15))
    t2 = asyncio.create_task(worker(counter_2, "SELECT * FROM orders WHERE id = 1 ", 30))
    await asyncio.gather(t1, t2)

    assert counter_1.chunks_received == 15
    assert counter_2.chunks_received == 30
    assert counter_1.current_count < counter_2.current_count


def test_json_malformed_retry_trigger():
    """Verify that a stream cut mid-JSON (e.g. unclosed braces) triggers TokenBudgetExceededError cleanly."""
    counter = StreamTokenCounter(hard_limit=50, safety_buffer=10)
    
    # Simulate a stream that emits partial JSON and breaches budget
    partial_json_chunk_1 = '{"thought": "analyzing query", "sql": "'
    partial_json_chunk_2 = 'SELECT id, name, created_at, status FROM large_party_registry_table WHERE status = ACTIVE AND deleted_at IS NULL AND ' * 3

    counter.add_chunk(partial_json_chunk_1)
    assert not counter.check_limit()

    counter.add_chunk(partial_json_chunk_2)
    assert counter.check_limit() is True
    
    with pytest.raises(TokenBudgetExceededError) as exc_info:
        counter.raise_if_exceeded()
    
    assert exc_info.value.limit == 50
    assert exc_info.value.count >= 60

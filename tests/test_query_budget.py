"""Unit tests for QueryBudgetController real-time enforcement and boundary limits."""

import asyncio
import pytest
from src.utils.query_budget import QueryBudgetController, QueryBudgetExceededError
from src.utils.stream_token_counter import StreamTokenCounter, TokenBudgetExceededError


def test_query_budget_boundary_limits():
    """Verify behavior at 7999, 8000, 8200 (safety buffer), and 8201 tokens."""
    controller = QueryBudgetController(hard_limit=8000, safety_buffer=200)

    # Set token count to 7999
    controller.counter.current_count = 7999
    assert controller.can_proceed() is True
    controller.counter.raise_if_exceeded()  # Should not raise

    # Set token count to 8000
    controller.counter.current_count = 8000
    assert controller.can_proceed() is True
    controller.counter.raise_if_exceeded()  # Should not raise (within buffer)

    # Set token count to 8200 (hard_limit + buffer exactly)
    controller.counter.current_count = 8200
    assert controller.counter.check_limit() is True
    with pytest.raises(TokenBudgetExceededError) as exc_info:
        controller.counter.raise_if_exceeded()
    assert exc_info.value.count == 8200
    assert exc_info.value.limit == 8000

    # Set token count to 8201
    controller.counter.current_count = 8201
    with pytest.raises(TokenBudgetExceededError):
        controller.counter.raise_if_exceeded()


def test_query_budget_increase_limit_for_retry():
    """Verify increase_limit allows +1K recovery during smart retry."""
    controller = QueryBudgetController(hard_limit=8000, safety_buffer=200)
    controller.counter.current_count = 8150

    # Increase limit by 1000 -> new limit 9000 (+200 buffer = 9200)
    controller.increase_limit(1000)
    assert controller.max_tokens == 9000
    assert controller.counter.hard_limit == 9000
    assert controller.counter.check_limit() is False
    assert controller.can_proceed() is True
    controller.counter.raise_if_exceeded()  # Should not raise now


def test_parallel_stream_counters_isolation():
    """Verify no race conditions occur when two separate stream counters run concurrently."""
    counter_a = StreamTokenCounter(hard_limit=1000, safety_buffer=50)
    counter_b = StreamTokenCounter(hard_limit=1000, safety_buffer=50)

    async def stream_worker(counter: StreamTokenCounter, chunk_text: str, n_chunks: int):
        for _ in range(n_chunks):
            counter.add_chunk(chunk_text)
            await asyncio.sleep(0.001)

    async def run_parallel():
        # counter A receives 200 tokens (10 chunks of 20 tokens)
        # counter B receives 800 tokens (40 chunks of 20 tokens)
        t_a = asyncio.create_task(stream_worker(counter_a, "SELECT id FROM test ", 10))
        t_b = asyncio.create_task(stream_worker(counter_b, "SELECT id FROM test ", 40))
        await asyncio.gather(t_a, t_b)

    asyncio.run(run_parallel())

    assert counter_a.current_count > 0
    assert counter_b.current_count > 0
    assert counter_a.current_count != counter_b.current_count
    assert counter_a.chunks_received == 10
    assert counter_b.chunks_received == 40
    assert counter_a.current_count < 1000
    assert counter_b.current_count < 1000

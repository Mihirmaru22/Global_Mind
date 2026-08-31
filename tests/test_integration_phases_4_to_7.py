"""Dynamic End-to-End Integration Tests for Phases 4 through 7 (The Hard Check).

Mathematically and dynamically validates:
1. Successful Delta Repair within Query Budget (Phase 5 & 6)
2. Delta Repair Budget Exhaustion halting at MAX_DELTA_REPAIR_ATTEMPTS (Phase 6 & 7)
3. Provider Circuit Breaker Tripping on consecutive 429s (Phase 7)
4. Token Budget Hard Enforcement under massive schema load (Phase 5)
"""

from __future__ import annotations

import sqlite3
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from src.core import config, db_client
from src.core.provider_client import ProviderRouter
from src.models.schemas import ChunkType
from src.prompts.delta_repair import build_delta_repair_payload, count_tokens, MAX_TOTAL_REPAIR_TOKENS
from src.stages.s12b_sql_retrieval import SQLRetriever
from src.stages.sql_repair import MAX_DELTA_REPAIR_ATTEMPTS
from src.utils.circuit_breaker import (
    CircuitBreakerOpenError,
    ProviderCircuitBreaker,
    get_shared_circuit_breaker,
)
from src.utils.query_budget import (
    QueryBudgetController,
    get_current_budget_controller,
    set_current_budget_controller,
)
from src.utils.telemetry import get_or_create_query_id, set_current_query_id


@pytest.fixture
def audit_test_db(tmp_path, monkeypatch):
    """Temporary SQLite database for audit execution."""
    db_path = tmp_path / "hard_check_audit.db"
    con = sqlite3.connect(db_path)
    con.executescript(
        """
        CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT, city TEXT);
        CREATE TABLE orders (id INTEGER PRIMARY KEY, customer_id INTEGER, amount REAL, order_date TEXT);
        INSERT INTO customers (id, name, city) VALUES (1, 'Acme Corp', 'NYC'), (2, 'Globex', 'LA');
        INSERT INTO orders (id, customer_id, amount, order_date) VALUES (1, 1, 5000.0, '2026-01-15');
        """
    )
    con.commit()
    con.close()

    monkeypatch.setattr(config.settings, "db_engine", "sqlite", raising=False)
    monkeypatch.setattr(db_client, "DB_PATH", db_path, raising=False)
    SQLRetriever.clear_schema_cache()
    SQLRetriever.clear_result_cache()
    return db_path


class DummyHTTPError(Exception):
    def __init__(self, status_code: int, message: str = "") -> None:
        super().__init__(f"HTTP {status_code}: {message}")
        self.status_code = status_code


@pytest.mark.asyncio
async def test_audit_1_successful_delta_repair_within_budget(audit_test_db, monkeypatch):
    """Test 1: Successful Delta Repair within Budget.
    
    - Mock initial SQL generation to return SQL with non-existent column.
    - Mock DB execution to fail.
    - Mock Delta Repair to return valid SQL.
    - Mock DB execution to succeed.
    - Assert budget records exactly 2 calls (1 gen, 1 repair).
    """
    mock_router = MagicMock(spec=ProviderRouter)
    mock_router.chat = AsyncMock(side_effect=[
        "SELECT id, non_existent_column FROM customers",  # Initial generation (fails DB execution)
        "SELECT id, name FROM customers",  # Delta Repair attempt 1 (succeeds)
    ])

    test_qid = "audit-q1-successful-repair"
    set_current_query_id(test_qid)
    budget = QueryBudgetController(query_id=test_qid, max_llm_calls=4, max_repairs=2, max_tokens=15000)
    set_current_budget_controller(budget)

    try:
        with patch("src.stages.s12b_sql_retrieval.is_feature_enabled", return_value=True):
            retriever = SQLRetriever(router=mock_router)
            chunks = await retriever.retrieve("Show all customer names")

            # Check that query succeeded and returned customer data
            assert len(chunks) == 1
            assert chunks[0].chunk.chunk_type == ChunkType.SQL_RESULT
            assert "Acme Corp" in chunks[0].chunk.content

            # Assert router was called exactly twice (1 gen + 1 repair)
            assert mock_router.chat.await_count == 2

            # Assert budget recorded the calls
            active_budget = get_current_budget_controller()
            assert active_budget is not None
            assert active_budget.llm_calls == 2
            assert active_budget.repair_attempts == 1
            assert active_budget.can_proceed() is True
    finally:
        set_current_query_id(None)
        set_current_budget_controller(None)


@pytest.mark.asyncio
async def test_audit_2_budget_exhaustion_max_repairs_exceeded(audit_test_db, monkeypatch):
    """Test 2: Budget Exhaustion (Max Repairs Exceeded).
    
    - Mock initial SQL generation to fail DB execution.
    - Mock 1st Delta Repair to return failing SQL.
    - Mock 2nd Delta Repair to return failing SQL.
    - Assert exactly 2 repairs are attempted (MAX_DELTA_REPAIR_ATTEMPTS=2).
    - Assert no 3rd repair is attempted and query halts gracefully returning empty results.
    """
    mock_router = MagicMock(spec=ProviderRouter)
    mock_router.chat = AsyncMock(side_effect=[
        "SELECT id, bad_col_1 FROM customers",  # Initial generation
        "SELECT id, bad_col_2 FROM customers",  # Repair attempt 1
        "SELECT id, bad_col_3 FROM customers",  # Repair attempt 2
        "SELECT id, bad_col_4 FROM customers",  # Should NOT be reached
    ])

    test_qid = "audit-q2-max-repairs"
    set_current_query_id(test_qid)
    budget = QueryBudgetController(query_id=test_qid, max_llm_calls=4, max_repairs=2, max_tokens=15000)
    set_current_budget_controller(budget)

    try:
        with patch("src.stages.s12b_sql_retrieval.is_feature_enabled", return_value=True):
            retriever = SQLRetriever(router=mock_router)
            chunks = await retriever.retrieve("Show customer names")

            # Must fail cleanly without crashing
            assert chunks == []

            # 1 initial generation + 2 repairs = 3 LLM calls total
            assert mock_router.chat.await_count == 3
            active_budget = get_current_budget_controller()
            assert active_budget is not None
            assert active_budget.repair_attempts == MAX_DELTA_REPAIR_ATTEMPTS
            assert active_budget.llm_calls == 3
    finally:
        set_current_query_id(None)
        set_current_budget_controller(None)


@pytest.mark.asyncio
async def test_audit_3_circuit_breaker_trips_on_consecutive_429s():
    """Test 3: Circuit Breaker Trip (Consecutive 429s).
    
    - Reset global circuit breaker.
    - Mock provider client to raise 429 3 consecutive times.
    - Assert breaker trips (is_open == True).
    - Assert on 4th call, request is intercepted locally before hitting network.
    """
    cb = get_shared_circuit_breaker()
    cb.reset_all()

    provider_name = "test_audit_provider"
    assert cb.is_open(provider_name) is False

    # Simulate 3 consecutive 429 errors
    for _ in range(3):
        cb.record_failure(provider_name, DummyHTTPError(429, "Rate limit exceeded"))

    # Assert breaker is now OPEN
    assert cb.is_open(provider_name) is True

    # Test interception via ProviderRouter
    router = ProviderRouter()
    mock_provider = MagicMock()
    mock_provider.is_available = True
    mock_provider.chat = AsyncMock(return_value="should not be called")
    router._providers = {provider_name: mock_provider}

    # Configure a route pointing only to this provider
    from src.core.provider_client import ProviderOption, TaskRoute
    router._routes["reasoning"] = TaskRoute([
        ProviderOption(provider_name=provider_name, model="test-model", priority=1)
    ])

    with pytest.raises(RuntimeError, match="All providers exhausted"):
        await router.chat("reasoning", [{"role": "user", "content": "hello"}])

    # The mock network provider must NOT have been called because circuit breaker was open
    assert mock_provider.chat.await_count == 0


def test_audit_4_token_budget_enforcement_massive_schema():
    """Test 4: Token Budget Enforcement (Phase 5 Math).
    
    - Pass a massive schema (50 tables, 20 columns each) to build_delta_repair_payload.
    - Assert total payload token count is strictly < 500.
    """
    massive_schema = {
        f"table_{i}": [f"column_{j}_{'long_suffix_' * 3}" for j in range(20)]
        for i in range(50)
    }

    payload = build_delta_repair_payload(
        failed_sql="SELECT col_1, col_2 FROM table_1 WHERE id = 123",
        error_message='column "col_1" does not exist in table "table_1"',
        error_type="column_not_found",
        schema_context=massive_schema,
        user_intent="Retrieve records from table 1 with ID 123",
    )

    sys_tokens = count_tokens(payload[0]["content"])
    user_tokens = count_tokens(payload[1]["content"])
    total_tokens = sys_tokens + user_tokens

    assert total_tokens < MAX_TOTAL_REPAIR_TOKENS
    assert total_tokens < 500
    assert "Schema context omitted" in payload[1]["content"] or "Table names only" in payload[1]["content"]

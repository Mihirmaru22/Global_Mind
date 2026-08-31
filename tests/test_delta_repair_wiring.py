"""Deterministic unit and integration tests for Delta Repair Executor and Pipeline Wiring."""

from __future__ import annotations

import sqlite3
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from src.core import config, db_client
from src.core.provider_client import ProviderRouter
from src.models.schemas import ChunkType
from src.stages.s12b_sql_retrieval import SQLRetriever
from src.stages.sql_repair import (
    MAX_DELTA_REPAIR_ATTEMPTS,
    attempt_delta_repair,
    extract_schema_context_from_ddl,
    extract_sql_from_response,
)


@pytest.fixture
def live_test_db(tmp_path, monkeypatch):
    """Temporary SQLite database fixture matching project standards."""
    db_path = tmp_path / "delta_repair_test.db"
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


def test_extract_sql_from_response_fenced():
    """Verify stripping markdown code fences."""
    raw = "```sql\nSELECT id, name FROM users\n```"
    assert extract_sql_from_response(raw) == "SELECT id, name FROM users"

    raw_no_lang = "```\nSELECT id, name FROM users\n```"
    assert extract_sql_from_response(raw_no_lang) == "SELECT id, name FROM users"


def test_extract_sql_from_response_prose_prefix():
    """Verify extracting SQL from conversational prose responses."""
    raw = "Here is the corrected SQL query:\nSELECT id, name FROM users WHERE active = 1;"
    assert extract_sql_from_response(raw) == "SELECT id, name FROM users WHERE active = 1"

    raw_with = "Sure! Use this WITH clause:\nWITH cte AS (SELECT 1 AS n) SELECT * FROM cte"
    assert extract_sql_from_response(raw_with).startswith("WITH cte AS")


def test_extract_schema_context_from_ddl():
    """Verify DDL schema parsing to compact {table: [columns]} mapping."""
    ddl = """
    CREATE TABLE users (
        id INTEGER PRIMARY KEY,
        username VARCHAR(50),
        email VARCHAR(100),
        created_at TIMESTAMP
    );

    CREATE TABLE orders (
        id INTEGER PRIMARY KEY,
        user_id INTEGER,
        total_amount NUMERIC(10, 2)
    );
    """
    context = extract_schema_context_from_ddl(ddl)
    assert "users" in context
    assert "orders" in context
    assert "username" in context["users"]
    assert "email" in context["users"]
    assert "total_amount" in context["orders"]


@pytest.mark.asyncio
async def test_attempt_delta_repair_success():
    """Verify attempt_delta_repair calls router with compact payload and returns sanitized SQL."""
    mock_router = MagicMock()
    mock_router.chat = AsyncMock(return_value="```sql\nSELECT id, name FROM customers ORDER BY name\n```")

    repaired = await attempt_delta_repair(
        router=mock_router,
        failed_sql="SELECT id, customer_name FROM customers ORDER BY customer_name",
        error_message='column "customer_name" does not exist',
        error_type="column_not_found",
        schema_context={"customers": ["id", "name", "city"]},
        user_intent="List all customers",
        attempt_number=1,
        query_id="test-repair-001",
    )

    assert repaired == "SELECT id, name FROM customers ORDER BY name"
    assert mock_router.chat.await_count == 1
    call_kwargs = mock_router.chat.await_args.kwargs
    messages = call_kwargs["messages"]
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert "customer_name" in messages[1]["content"]
    assert call_kwargs["task"] == "repair"


@pytest.mark.asyncio
async def test_attempt_delta_repair_attempt_ceiling():
    """Verify that repair attempts beyond MAX_DELTA_REPAIR_ATTEMPTS return None immediately."""
    mock_router = MagicMock()
    mock_router.chat = AsyncMock()

    result = await attempt_delta_repair(
        router=mock_router,
        failed_sql="SELECT 1",
        error_message="err",
        attempt_number=MAX_DELTA_REPAIR_ATTEMPTS + 1,
    )
    assert result is None
    assert mock_router.chat.await_count == 0


@pytest.mark.asyncio
async def test_attempt_delta_repair_handles_exceptions_gracefully():
    """Verify that provider errors do not crash and return None safely."""
    mock_router = MagicMock()
    mock_router.chat = AsyncMock(side_effect=RuntimeError("Provider 500 error"))

    result = await attempt_delta_repair(
        router=mock_router,
        failed_sql="SELECT bad FROM tbl",
        error_message="some error",
        attempt_number=1,
        query_id="test-err-001",
    )
    assert result is None


@pytest.mark.asyncio
async def test_pipeline_wiring_delta_repair_enabled(live_test_db, monkeypatch):
    """Test full SQLRetriever flow when delta_repair_enabled=True repairs validation error."""
    mock_router = MagicMock(spec=ProviderRouter)

    # First call (_generate_sql) returns SQL with hallucinated column
    # Second call (attempt_delta_repair) returns repaired SQL with valid column
    mock_router.chat = AsyncMock(side_effect=[
        "SELECT id, non_existent_col FROM customers",  # Initial generation (fails DB execution)
        "SELECT id, name FROM customers",  # Delta Repair attempt 1 (succeeds)
    ])

    monkeypatch.setenv("FEATURE_DELTA_REPAIR_ENABLED", "true")

    with patch("src.stages.s12b_sql_retrieval.is_feature_enabled", side_effect=lambda flag: flag == "delta_repair_enabled"):
        retriever = SQLRetriever(router=mock_router)
        chunks = await retriever.retrieve("Show all customer names")

        assert len(chunks) == 1
        assert chunks[0].chunk.chunk_type == ChunkType.SQL_RESULT
        assert "Acme Corp" in chunks[0].chunk.content
        assert mock_router.chat.await_count == 2


@pytest.mark.asyncio
async def test_pipeline_wiring_delta_repair_disabled_uses_old_path(live_test_db, monkeypatch):
    """Test SQLRetriever flow when delta_repair_enabled=False falls back to full retry loop."""
    mock_router = MagicMock(spec=ProviderRouter)
    mock_router.chat = AsyncMock(return_value="SELECT id, name FROM customers")

    monkeypatch.setenv("FEATURE_DELTA_REPAIR_ENABLED", "false")

    with patch("src.stages.s12b_sql_retrieval.is_feature_enabled", return_value=False):
        retriever = SQLRetriever(router=mock_router)
        chunks = await retriever.retrieve("Show all customer names")

        assert len(chunks) == 1
        assert "Acme Corp" in chunks[0].chunk.content
        assert mock_router.chat.await_count == 1


@pytest.mark.asyncio
async def test_pipeline_budget_exhaustion_blocks_delta_repair(live_test_db, monkeypatch):
    """Test that if the query budget is exhausted, delta repair is not attempted and retrieval fails cleanly."""
    from src.utils.query_budget import QueryBudgetController, set_current_budget_controller

    mock_router = MagicMock(spec=ProviderRouter)
    mock_router.chat = AsyncMock(return_value="SELECT id, bad_column FROM customers")

    # Budget has 0 repairs allowed
    exhausted_budget = QueryBudgetController(query_id="exhausted-test", max_llm_calls=5, max_repairs=0, max_tokens=10000)
    set_current_budget_controller(exhausted_budget)

    try:
        with patch("src.stages.s12b_sql_retrieval.is_feature_enabled", return_value=True):
            retriever = SQLRetriever(router=mock_router)
            chunks = await retriever.retrieve("Show all customer names")

            # Fails gracefully with empty list without crashing
            assert chunks == []
            # Only initial generation call made; repair was blocked by budget controller
            assert mock_router.chat.await_count == 1
    finally:
        set_current_budget_controller(None)

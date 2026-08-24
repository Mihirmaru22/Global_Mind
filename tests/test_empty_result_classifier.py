"""Tests for Phase 11: Intelligent 0-Row Handling & AST Classification."""

from __future__ import annotations

import sqlite3
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from src.core import config, db_client
from src.core.provider_client import ProviderRouter
from src.models.schemas import ChunkType
from src.stages.s12b_sql_retrieval import SQLRetriever
from src.utils.empty_result_classifier import (
    SUSPICIOUS_EMPTY,
    VALID_EMPTY,
    classify_empty_result,
)


def test_valid_empty_no_filters():
    """Test 1: Plain SELECT on empty table without joins is valid_empty."""
    assert classify_empty_result("SELECT * FROM orders") == VALID_EMPTY
    assert classify_empty_result("SELECT id, name FROM customers") == VALID_EMPTY


def test_valid_empty_standard_filters():
    """Test 2: Standard realistic filters matching 0 records is valid_empty."""
    queries = [
        "SELECT * FROM orders WHERE status = 'shipped'",
        "SELECT id, total_amount FROM orders WHERE customer_id = 42 AND order_date >= '2024-01-01'",
        "SELECT id FROM products WHERE category IN ('Electronics', 'Appliances')",
        "SELECT id, name FROM customers WHERE city = 'Metropolis'",
        "SELECT o.id, c.name FROM orders o JOIN customers c ON o.customer_id = c.id WHERE o.order_date >= '2024-01-01'",
    ]
    for q in queries:
        assert classify_empty_result(q) == VALID_EMPTY, f"Query incorrectly marked as suspicious: {q}"


def test_suspicious_empty_join_without_where():
    """Test 3: Multi-table JOIN without WHERE returning 0 rows is suspicious_empty."""
    queries = [
        "SELECT o.id, c.name FROM orders o JOIN customers c ON o.id = c.id",
        "SELECT a.id, b.info FROM table_a a INNER JOIN table_b b ON a.fk_id = b.id",
    ]
    for q in queries:
        assert classify_empty_result(q) == SUSPICIOUS_EMPTY, f"Query with join but no WHERE should be suspicious: {q}"


def test_valid_aggregates():
    """Test 4: Aggregate queries returning 0 or NULL are classified as valid_empty."""
    queries = [
        "SELECT COUNT(*) FROM orders WHERE date > '2024-01-01'",
        "SELECT SUM(total_amount) AS revenue FROM sales_order WHERE financial_year_id = 5",
        "SELECT AVG(quantity) FROM order_items WHERE order_id = 999",
    ]
    for q in queries:
        assert classify_empty_result(q) == VALID_EMPTY, f"Aggregate query should be valid_empty: {q}"


def test_suspicious_date_and_like_filters():
    """Test 5: Impossible far-future dates and excessive LIKE strings are suspicious_empty."""
    assert classify_empty_result("SELECT * FROM orders WHERE created_at > '2099-01-01'") == SUSPICIOUS_EMPTY
    assert classify_empty_result("SELECT * FROM orders WHERE order_date >= '2100-12-31'") == SUSPICIOUS_EMPTY
    assert (
        classify_empty_result(
            "SELECT * FROM customers WHERE notes LIKE '%some extremely long hallucinated keyword string that exceeds forty chars%'"
        )
        == SUSPICIOUS_EMPTY
    )


@pytest.mark.asyncio
async def test_valid_empty_bypasses_delta_repair_loop(tmp_path, monkeypatch):
    """Test 6: When zero_row_handling_enabled is True, valid_empty does not invoke LLM repair."""
    db_path = tmp_path / "zero_row_valid.db"
    con = sqlite3.connect(db_path)
    con.executescript(
        """
        CREATE TABLE orders (id INTEGER PRIMARY KEY, status TEXT, amount REAL);
        -- Table is empty or has non-matching rows
        INSERT INTO orders (id, status, amount) VALUES (1, 'pending', 100.0);
        """
    )
    con.commit()
    con.close()

    monkeypatch.setattr(config.settings, "db_engine", "sqlite", raising=False)
    monkeypatch.setattr(db_client, "DB_PATH", db_path, raising=False)
    SQLRetriever.clear_schema_cache()
    SQLRetriever.clear_result_cache()

    mock_router = MagicMock(spec=ProviderRouter)
    # LLM outputs valid query that returns 0 rows (valid_empty)
    mock_router.chat = AsyncMock(return_value="SELECT id, amount FROM orders WHERE status = 'shipped'")

    def flag_override(flag):
        if flag in ("delta_repair_enabled", "zero_row_handling_enabled"):
            return True
        return False

    with patch("src.stages.s12b_sql_retrieval.is_feature_enabled", side_effect=flag_override):
        retriever = SQLRetriever(router=mock_router)
        chunks = await retriever.retrieve("Show all shipped orders")

        assert len(chunks) == 1
        assert chunks[0].chunk.chunk_type == ChunkType.SQL_RESULT
        assert "0 matching records" in chunks[0].chunk.content or "No matching records" in chunks[0].chunk.content

        # Crucial: LLM was called only ONCE for generation, zero times for repair!
        assert mock_router.chat.await_count == 1


@pytest.mark.asyncio
async def test_suspicious_empty_triggers_single_targeted_delta_repair(tmp_path, monkeypatch):
    """Test 7: When zero_row_handling_enabled is True, suspicious_empty triggers targeted repair."""
    db_path = tmp_path / "zero_row_suspicious.db"
    con = sqlite3.connect(db_path)
    con.executescript(
        """
        CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE orders (id INTEGER PRIMARY KEY, customer_id INTEGER, amount REAL);
        INSERT INTO customers (id, name) VALUES (1, 'Acme Corp');
        INSERT INTO orders (id, customer_id, amount) VALUES (10, 1, 500.0);
        """
    )
    con.commit()
    con.close()

    monkeypatch.setattr(config.settings, "db_engine", "sqlite", raising=False)
    monkeypatch.setattr(db_client, "DB_PATH", db_path, raising=False)
    SQLRetriever.clear_schema_cache()
    SQLRetriever.clear_result_cache()

    mock_router = MagicMock(spec=ProviderRouter)
    # 1. Initial SQL has bad join without WHERE -> returns 0 rows (suspicious_empty)
    # 2. Repair SQL fixes join -> returns data
    mock_router.chat = AsyncMock(side_effect=[
        "SELECT o.id, c.name FROM orders o JOIN customers c ON o.id = c.id",
        "SELECT o.id, c.name FROM orders o JOIN customers c ON o.customer_id = c.id",
    ])

    def flag_override(flag):
        if flag in ("delta_repair_enabled", "zero_row_handling_enabled"):
            return True
        return False

    with patch("src.stages.s12b_sql_retrieval.is_feature_enabled", side_effect=flag_override):
        retriever = SQLRetriever(router=mock_router)
        chunks = await retriever.retrieve("Show orders with customer names")

        assert len(chunks) == 1
        assert chunks[0].chunk.chunk_type == ChunkType.SQL_RESULT
        assert "Acme Corp" in chunks[0].chunk.content

        # router was called twice (1 gen + 1 delta repair)
        assert mock_router.chat.await_count == 2

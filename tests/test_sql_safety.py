"""Tests for Phase 10: SQL Safety Layer & AST Validation."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from src.core.provider_client import ProviderRouter
from src.models.schemas import ChunkType
from src.stages.s12b_sql_retrieval import SQLRetriever
from src.utils.golden_models import GoldenCase
from src.utils.sql_safety import (
    check_dangerous_patterns,
    is_destructive_sql,
    validate_sql_safety,
    validate_tables_and_columns,
)

GOLDEN_CASES_PATH = Path(__file__).resolve().parent / "golden" / "sql_repair" / "cases.json"


def test_destructive_sql_blocking():
    """Test 1: Destructive and multi-statement SQL are blocked, while read queries pass."""
    destructive_queries = [
        "DELETE FROM users WHERE id = 1",
        "UPDATE orders SET status = 'cancelled' WHERE id = 10",
        "INSERT INTO customers (name) VALUES ('Acme Corp')",
        "DROP TABLE products",
        "TRUNCATE TABLE audit_logs",
        "ALTER TABLE users ADD COLUMN age INT",
        "CREATE TABLE backdoor (id INT)",
        "GRANT ALL PRIVILEGES ON db.* TO 'hacker'@'%'",
        "REVOKE SELECT ON customers FROM 'user'@'%'",
        "SELECT id FROM customers; DROP TABLE orders;",
        "SELECT LOAD_FILE('/etc/passwd') AS secret",
        "SELECT SLEEP(10)",
        "SELECT * FROM customers INTO OUTFILE '/tmp/dump.txt'",
    ]

    for q in destructive_queries:
        assert is_destructive_sql(q) is True, f"Failed to block destructive query: {q}"

    safe_queries = [
        "SELECT id, name FROM customers WHERE id = 1",
        "SELECT c.name, SUM(o.amount) FROM customers c JOIN orders o ON c.id = o.customer_id GROUP BY c.name",
        "WITH active_orders AS (SELECT id, customer_id FROM orders WHERE status = 'active') SELECT * FROM active_orders",
        "SELECT id FROM branch_a UNION ALL SELECT id FROM branch_b",
    ]

    for q in safe_queries:
        assert is_destructive_sql(q) is False, f"Erroneously flagged safe query as destructive: {q}"


def test_dangerous_pattern_flagging():
    """Test 2: Dangerous patterns (SELECT * and CROSS JOIN) are flagged."""
    # 1. Star wildcard selections
    star_queries = [
        "SELECT * FROM orders",
        "SELECT o.*, c.name FROM orders o JOIN customers c ON o.customer_id = c.id",
    ]
    for q in star_queries:
        warnings = check_dangerous_patterns(q)
        assert len(warnings) >= 1
        assert any("SELECT *" in w or "Wildcard" in w for w in warnings)

    # 2. CROSS JOIN
    cross_join_query = "SELECT a.id, b.name FROM table_a a CROSS JOIN table_b b"
    warnings = check_dangerous_patterns(cross_join_query)
    assert len(warnings) >= 1
    assert any("CROSS JOIN" in w for w in warnings)

    # 3. Clean query produces no warnings
    clean_query = "SELECT a.id, b.name FROM table_a a JOIN table_b b ON a.id = b.a_id WHERE a.active = 1"
    assert check_dangerous_patterns(clean_query) == []


def test_validate_tables_and_columns_accuracy():
    """Test 3: Schema validation catches missing tables and hallucinated columns."""
    schema = {
        "customers": ["id", "name", "city", "created_at"],
        "orders": ["id", "customer_id", "total_amount", "order_date", "status"],
    }

    # 1. Valid query with aliases
    valid_sql = """
    SELECT c.name AS customer_name, SUM(o.total_amount) AS revenue
    FROM customers c
    JOIN orders o ON c.id = o.customer_id
    WHERE c.city = 'New York' AND o.status = 'completed'
    GROUP BY customer_name
    ORDER BY revenue DESC
    """
    is_valid, err = validate_tables_and_columns(valid_sql, schema)
    assert is_valid is True
    assert err == ""

    # 2. Hallucinated column on existing table
    bad_col_sql = "SELECT c.name, c.region_name FROM customers c"
    is_valid, err = validate_tables_and_columns(bad_col_sql, schema)
    assert is_valid is False
    assert "region_name" in err
    assert "customers" in err

    # 3. Non-existent table
    bad_tbl_sql = "SELECT id, amount FROM payments WHERE amount > 100"
    is_valid, err = validate_tables_and_columns(bad_tbl_sql, schema)
    assert is_valid is False
    assert "payments" in err
    assert "Available tables" in err


def test_function_and_aggregate_ignorance():
    """Test 4: SQL functions and aggregate expressions are not treated as columns."""
    schema = {
        "orders": ["id", "customer_id", "amount", "discount", "notes", "created_at"],
    }
    func_sql = """
    SELECT
        COUNT(id) AS order_count,
        SUM(amount) AS total_revenue,
        AVG(discount) AS avg_discount,
        MAX(created_at) AS latest_order,
        MIN(amount) AS lowest_amount,
        COALESCE(notes, 'none') AS clean_notes,
        UPPER(notes) AS uppercase_notes
    FROM orders
    WHERE amount > 0
    """
    is_valid, err = validate_tables_and_columns(func_sql, schema)
    assert is_valid is True
    assert err == ""


def test_golden_cases_ideal_sql_passes_validation():
    """Test 5: All 19 Golden Cases ideal SQL pass AST schema validation."""
    assert GOLDEN_CASES_PATH.exists()
    with open(GOLDEN_CASES_PATH, "r", encoding="utf-8") as f:
        cases_raw = json.load(f)

    golden_cases = [GoldenCase(**c) for c in cases_raw]
    assert len(golden_cases) >= 15

    for case in golden_cases:
        if not case.ideal_sql or not case.schema_context:
            continue
        is_valid, err = validate_tables_and_columns(case.ideal_sql, case.schema_context)
        assert is_valid is True, f"Golden Case {case.case_id} ideal SQL failed validation: {err}\nSQL: {case.ideal_sql}"


@pytest.mark.asyncio
async def test_sql_safety_pipeline_delta_repair_routing(tmp_path, monkeypatch):
    """Test 6: Validation errors under sql_safety_enabled route directly to Delta Repair."""
    import sqlite3
    from src.core import config, db_client

    db_path = tmp_path / "safety_test.db"
    con = sqlite3.connect(db_path)
    con.executescript(
        """
        CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT);
        INSERT INTO customers (id, name) VALUES (1, 'Acme Corp');
        """
    )
    con.commit()
    con.close()

    monkeypatch.setattr(config.settings, "db_engine", "sqlite", raising=False)
    monkeypatch.setattr(db_client, "DB_PATH", db_path, raising=False)
    SQLRetriever.clear_schema_cache()
    SQLRetriever.clear_result_cache()

    mock_router = MagicMock(spec=ProviderRouter)
    # LLM outputs SELECT * on first try (blocked by safety layer), then outputs valid query on repair
    mock_router.chat = AsyncMock(side_effect=[
        "SELECT * FROM customers",  # Initial generation (dangerous pattern SELECT *)
        "SELECT id, name FROM customers",  # Delta repair (repaired without SELECT *)
    ])

    def flag_override(flag):
        if flag in ("delta_repair_enabled", "sql_safety_enabled"):
            return True
        return False

    with patch("src.stages.s12b_sql_retrieval.is_feature_enabled", side_effect=flag_override):
        retriever = SQLRetriever(router=mock_router)
        chunks = await retriever.retrieve("Show all customer records")

        assert len(chunks) == 1
        assert chunks[0].chunk.chunk_type == ChunkType.SQL_RESULT
        assert "Acme Corp" in chunks[0].chunk.content

        # Assert router was called twice (1 gen + 1 delta repair)
        assert mock_router.chat.await_count == 2

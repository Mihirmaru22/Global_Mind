"""Comprehensive Integration Audit (Phases 8 to 11): Dynamic Verification Test.

Mathematically and programmatically proves end-to-end integration across:
- Phase 8: Dynamic Schema Token Budget & Shadow Telemetry
- Phase 9: AST Schema Compactor & DDL Stripping
- Phase 10: SQL Safety Layer & AST Validation
- Phase 11: Intelligent 0-Row Result Handling
"""

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
from src.utils.schema_budget import select_schema_within_budget
from src.utils.schema_compactor import compact_ddl, extract_join_hints
from src.utils.schema_token_estimator import estimate_schema_tokens
from src.utils.sql_safety import is_destructive_sql, validate_sql_safety


def test_1_schema_budget_and_compaction_pipeline():
    """Test 1: Massive raw DDLs are budgeted (<1500 tokens), compacted, audit cols stripped, FKs kept."""
    # 10 large table DDL candidates (~500 tokens each with verbose audit columns & constraints)
    candidates = []
    for i in range(1, 11):
        ddl = f"""
        CREATE TABLE entity_{i} (
            id INT PRIMARY KEY AUTO_INCREMENT,
            parent_id INT,
            entity_code VARCHAR(100) NOT NULL,
            display_name VARCHAR(255) NOT NULL,
            description TEXT,
            status VARCHAR(50) DEFAULT 'ACTIVE',
            amount DECIMAL(18, 4) DEFAULT 0.0000,
            tax_rate DECIMAL(5, 2) DEFAULT 0.00,
            priority_level INT DEFAULT 1,
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            deleted_at TIMESTAMP NULL,
            created_by INT,
            updated_by INT,
            CONSTRAINT fk_entity_{i}_parent FOREIGN KEY (parent_id) REFERENCES entity_{max(1, i-1)} (id)
        );
        """
        candidates.append({
            "table_name": f"entity_{i}",
            "ddl": ddl.strip(),
            "source": "vector_rag",
        })

    # Total raw tokens before budgeting
    total_raw_tokens = sum(estimate_schema_tokens(c["ddl"]) for c in candidates)
    assert total_raw_tokens > 2000, f"Expected total raw tokens > 2000, got {total_raw_tokens}"

    # 1. Budget selection capped at 1500 tokens
    selected, dropped = select_schema_within_budget(candidates, token_budget=1500, id_key="table_name")
    assert len(selected) > 0
    assert len(dropped) > 0
    assert len(selected) + len(dropped) == len(candidates)

    budgeted_raw_schema = "\n\n".join(c["ddl"] for c in selected)
    budgeted_tokens = estimate_schema_tokens(budgeted_raw_schema)
    assert budgeted_tokens <= 1500

    # 2. Compact selected candidates
    compacted_ddls = [compact_ddl(c["ddl"]) for c in selected]
    raw_ddls = [c["ddl"] for c in selected]
    join_hints = extract_join_hints(raw_ddls)

    compacted_schema = "\n".join(compacted_ddls)
    if join_hints:
        compacted_schema += "\n\n" + join_hints

    final_tokens = estimate_schema_tokens(compacted_schema)

    # 3. Assertions
    assert final_tokens < 1500, f"Compacted tokens ({final_tokens}) exceeded budget"
    assert final_tokens < budgeted_tokens * 0.7, "Expected >30% token reduction via compaction"

    # Audit columns must be stripped
    assert "created_at" not in compacted_schema
    assert "updated_at" not in compacted_schema
    assert "created_by" not in compacted_schema
    assert "updated_by" not in compacted_schema
    assert "deleted_at" not in compacted_schema

    # Primary and foreign keys must be preserved
    assert "PK" in compacted_schema
    assert "FK->" in compacted_schema or "Join Hints:" in compacted_schema


@pytest.mark.asyncio
async def test_2_safety_layer_interception_and_repair_routing(tmp_path, monkeypatch):
    """Test 2: Destructive SQL is blocked before DB execution and routed to Delta Repair."""
    db_path = tmp_path / "safety_audit.db"
    con = sqlite3.connect(db_path)
    con.executescript(
        """
        CREATE TABLE orders (id INTEGER PRIMARY KEY, status TEXT, amount REAL);
        INSERT INTO orders (id, status, amount) VALUES (1, 'pending', 150.0);
        """
    )
    con.commit()
    con.close()

    monkeypatch.setattr(config.settings, "db_engine", "sqlite", raising=False)
    monkeypatch.setattr(db_client, "DB_PATH", db_path, raising=False)
    SQLRetriever.clear_schema_cache()
    SQLRetriever.clear_result_cache()

    # Destructive SQL statement
    destructive_sql = "DELETE FROM orders WHERE status = 'pending'"
    assert is_destructive_sql(destructive_sql) is True

    mock_router = MagicMock(spec=ProviderRouter)
    # 1. Initial LLM generation generates destructive DELETE
    # 2. Delta Repair fixes it to read-only SELECT
    mock_router.chat = AsyncMock(side_effect=[
        destructive_sql,
        "SELECT id, status, amount FROM orders WHERE status = 'pending'",
    ])

    captured_failures = []
    def mock_capture(*args, **kwargs):
        captured_failures.append(kwargs)

    def flag_override(flag):
        if flag in ("delta_repair_enabled", "sql_safety_enabled"):
            return True
        return False

    with patch("src.stages.s12b_sql_retrieval.is_feature_enabled", side_effect=flag_override), \
         patch("src.stages.s12b_sql_retrieval.capture_sql_failure", side_effect=mock_capture):
        retriever = SQLRetriever(router=mock_router)
        chunks = await retriever.retrieve("Cancel pending orders")

        assert len(chunks) == 1
        assert chunks[0].chunk.chunk_type == ChunkType.SQL_RESULT
        assert "150.0" in chunks[0].chunk.content or "pending" in chunks[0].chunk.content

        # Assert router was called twice (1 gen + 1 delta repair)
        assert mock_router.chat.await_count == 2
        # Assert failure was captured for the destructive query
        assert len(captured_failures) >= 1
        assert captured_failures[0]["failed_sql"] == destructive_sql


@pytest.mark.asyncio
async def test_3_valid_empty_bypass_zero_llm_repairs(tmp_path, monkeypatch):
    """Test 3: Valid 0-row results immediately bypass repair loop with 0 extra LLM calls."""
    db_path = tmp_path / "valid_empty_audit.db"
    con = sqlite3.connect(db_path)
    con.executescript(
        """
        CREATE TABLE orders (id INTEGER PRIMARY KEY, region TEXT, amount REAL);
        INSERT INTO orders (id, region, amount) VALUES (1, 'North America', 250.0);
        """
    )
    con.commit()
    con.close()

    monkeypatch.setattr(config.settings, "db_engine", "sqlite", raising=False)
    monkeypatch.setattr(db_client, "DB_PATH", db_path, raising=False)
    SQLRetriever.clear_schema_cache()
    SQLRetriever.clear_result_cache()

    valid_empty_sql = "SELECT id, amount FROM orders WHERE region = 'Antarctica'"
    assert classify_empty_result(valid_empty_sql) == VALID_EMPTY

    mock_router = MagicMock(spec=ProviderRouter)
    mock_router.chat = AsyncMock(return_value=valid_empty_sql)

    captured_failures = []
    def mock_capture(*args, **kwargs):
        captured_failures.append(kwargs)

    def flag_override(flag):
        if flag in ("delta_repair_enabled", "zero_row_handling_enabled"):
            return True
        return False

    with patch("src.stages.s12b_sql_retrieval.is_feature_enabled", side_effect=flag_override), \
         patch("src.stages.s12b_sql_retrieval.capture_sql_failure", side_effect=mock_capture):
        retriever = SQLRetriever(router=mock_router)
        chunks = await retriever.retrieve("Show orders in Antarctica")

        assert len(chunks) == 1
        assert chunks[0].chunk.chunk_type == ChunkType.SQL_RESULT
        assert "0 matching records" in chunks[0].chunk.content or "No matching records" in chunks[0].chunk.content

        # PROOF OF LIFE: Exactly 1 LLM call (Initial generation), ZERO repair calls
        assert mock_router.chat.await_count == 1
        # PROOF OF LIFE: ZERO failure capture entries
        assert len(captured_failures) == 0


@pytest.mark.asyncio
async def test_4_suspicious_empty_triggers_single_repair(tmp_path, monkeypatch):
    """Test 4: Suspicious 0-row results trigger exactly ONE targeted Delta Repair."""
    db_path = tmp_path / "suspicious_empty_audit.db"
    con = sqlite3.connect(db_path)
    con.executescript(
        """
        CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE orders (id INTEGER PRIMARY KEY, customer_id INTEGER, amount REAL);
        INSERT INTO customers (id, name) VALUES (1, 'Global Corp');
        INSERT INTO orders (id, customer_id, amount) VALUES (101, 1, 999.0);
        """
    )
    con.commit()
    con.close()

    monkeypatch.setattr(config.settings, "db_engine", "sqlite", raising=False)
    monkeypatch.setattr(db_client, "DB_PATH", db_path, raising=False)
    SQLRetriever.clear_schema_cache()
    SQLRetriever.clear_result_cache()

    # Suspicious query: Join without WHERE returning 0 rows due to bad join keys
    suspicious_sql = "SELECT o.id, c.name FROM orders o JOIN customers c ON o.id = c.id"
    repaired_sql = "SELECT o.id, c.name FROM orders o JOIN customers c ON o.customer_id = c.id"

    assert classify_empty_result(suspicious_sql) == SUSPICIOUS_EMPTY

    mock_router = MagicMock(spec=ProviderRouter)
    mock_router.chat = AsyncMock(side_effect=[suspicious_sql, repaired_sql])

    def flag_override(flag):
        if flag in ("delta_repair_enabled", "zero_row_handling_enabled"):
            return True
        return False

    with patch("src.stages.s12b_sql_retrieval.is_feature_enabled", side_effect=flag_override):
        retriever = SQLRetriever(router=mock_router)
        chunks = await retriever.retrieve("Show all orders with customer names")

        assert len(chunks) == 1
        assert chunks[0].chunk.chunk_type == ChunkType.SQL_RESULT
        assert "Global Corp" in chunks[0].chunk.content

        # PROOF OF LIFE: Router called exactly twice (1 gen + 1 delta repair)
        assert mock_router.chat.await_count == 2

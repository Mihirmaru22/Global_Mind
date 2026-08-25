"""Tests for Phase 9: Schema Compaction & DDL Stripping."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch
import pytest

from src.utils.golden_models import GoldenCase
from src.utils.schema_compactor import AUDIT_COLUMNS, compact_ddl, extract_join_hints

GOLDEN_CASES_PATH = Path(__file__).resolve().parent / "golden" / "sql_repair" / "cases.json"


def test_basic_compaction_strips_audit_columns_and_keeps_pk_fk():
    """Test 1: Standard CREATE TABLE with PK, FK, and audit columns.
    
    Verifies that:
    - PK and FK are preserved with tags.
    - Regular business columns are preserved with simplified types.
    - Audit columns (created_at, updated_by, deleted_at) are stripped.
    """
    raw_ddl = """
    CREATE TABLE orders (
        id INT AUTO_INCREMENT PRIMARY KEY,
        customer_id INT NOT NULL,
        order_number VARCHAR(64) NOT NULL,
        total_amount DECIMAL(12, 2) DEFAULT '0.00',
        order_status VARCHAR(20) DEFAULT 'pending',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        created_by VARCHAR(50) DEFAULT NULL,
        updated_by VARCHAR(50) DEFAULT NULL,
        deleted_at TIMESTAMP NULL,
        CONSTRAINT fk_cust FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE RESTRICT
    );
    """
    compacted = compact_ddl(raw_ddl, dialect="mysql")

    # Assert table name present
    assert compacted.startswith("orders:")

    # Assert PK and FK preserved
    assert "id(int, PK)" in compacted or "id(int, PK" in compacted
    assert "customer_id(int, FK->customers.id)" in compacted or "FK->customers.id" in compacted

    # Assert core business columns preserved
    assert "order_number(varchar)" in compacted
    assert "total_amount(decimal)" in compacted
    assert "order_status(varchar)" in compacted

    # Assert audit columns are stripped
    for audit_col in ["created_at", "updated_at", "created_by", "updated_by", "deleted_at"]:
        assert audit_col not in compacted.lower()


def test_parse_failure_fallback_returns_raw_string():
    """Test 2: Malformed or non-SQL string falls back safely to original text without crashing."""
    malformed_sql = "INVALID NOT A TABLE STATEMENT (((( -- completely broken syntax"
    result = compact_ddl(malformed_sql)
    assert result == malformed_sql.strip()

    # Empty inputs
    assert compact_ddl("") == ""
    assert compact_ddl(None) == ""


def test_extract_join_hints_from_multiple_ddls():
    """Test 3: Extracting explicit FK constraints from DDLs into join hints block."""
    ddls = [
        """
        CREATE TABLE sales_order (
            id INT PRIMARY KEY,
            party_id INT NOT NULL,
            financial_year_id INT NOT NULL,
            CONSTRAINT fk_party FOREIGN KEY (party_id) REFERENCES party(id),
            CONSTRAINT fk_fy FOREIGN KEY (financial_year_id) REFERENCES financial_year(id)
        );
        """,
        """
        CREATE TABLE sales_order_products (
            id INT PRIMARY KEY,
            sales_order_id INT REFERENCES sales_order(id),
            product_id INT REFERENCES product(id)
        );
        """,
        """
        CREATE TABLE party (
            id INT PRIMARY KEY,
            party_name VARCHAR(100)
        );
        """
    ]

    hints = extract_join_hints(ddls)
    assert hints.startswith("Join Hints:")
    assert "- sales_order.party_id -> party.id" in hints
    assert "- sales_order.financial_year_id -> financial_year.id" in hints
    assert "- sales_order_products.sales_order_id -> sales_order.id" in hints
    assert "- sales_order_products.product_id -> product.id" in hints

    # When no FKs exist
    no_fk_ddl = ["CREATE TABLE simple (id INT, name TEXT);"]
    assert extract_join_hints(no_fk_ddl) == ""


def test_golden_cases_columns_preserved_after_compaction():
    """Test 4: Verify that all 19 Golden Cases maintain required columns after compaction."""
    assert GOLDEN_CASES_PATH.exists()
    with open(GOLDEN_CASES_PATH, "r", encoding="utf-8") as f:
        cases_raw = json.load(f)

    golden_cases = [GoldenCase(**c) for c in cases_raw]
    assert len(golden_cases) >= 15

    for case in golden_cases:
        for tbl_name, cols in case.schema_context.items():
            col_defs = []
            for col in cols:
                if col == "id":
                    col_defs.append(f"{col} INT PRIMARY KEY")
                elif col.endswith("_id"):
                    col_defs.append(f"{col} INT REFERENCES other_tbl(id)")
                else:
                    col_defs.append(f"{col} VARCHAR(100)")

            # Add audit columns to simulate real raw DDL
            col_defs.append("created_at TIMESTAMP")
            col_defs.append("updated_at TIMESTAMP")
            col_defs.append("deleted_at TIMESTAMP")

            ddl = f"CREATE TABLE {tbl_name} (\n  " + ",\n  ".join(col_defs) + "\n);"
            compacted = compact_ddl(ddl)

            assert compacted.startswith(f"{tbl_name}:")
            # Verify business columns (non-audit) are still in the compacted representation
            for col in cols:
                if col.lower() not in AUDIT_COLUMNS:
                    assert col in compacted, f"Business column '{col}' missing from compacted table '{tbl_name}' in case {case.case_id}!"
            # Verify audit columns were stripped
            assert "updated_at" not in compacted
            assert "deleted_at" not in compacted


@pytest.mark.asyncio
async def test_schema_compaction_feature_flag_pipeline_integration():
    """Test 5: Integration with s12b_sql_retrieval schema builder."""
    from src.stages.s12b_sql_retrieval import _build_scoped_schema_fallback

    full_schema = """
    CREATE TABLE sales_order (
        id INTEGER PRIMARY KEY,
        party_id INTEGER,
        order_number TEXT,
        total_amount REAL,
        created_at TEXT,
        updated_at TEXT,
        CONSTRAINT fk_party FOREIGN KEY (party_id) REFERENCES party(id)
    );
    CREATE TABLE party (
        id INTEGER PRIMARY KEY,
        party_name TEXT,
        city TEXT,
        created_at TEXT
    );
    """

    # 1. Feature Flag = False (Raw DDL used)
    with patch("src.stages.s12b_sql_retrieval.is_feature_enabled", side_effect=lambda flag: False):
        schema_raw = _build_scoped_schema_fallback(full_schema, "Show sales orders")
        assert "CREATE TABLE sales_order" in schema_raw
        assert "created_at" in schema_raw

    # 2. Feature Flag = True (Compacted schema used)
    def flag_override(flag):
        if flag == "schema_compaction_enabled":
            return True
        if flag == "token_budget_enabled":
            return True
        return False

    with patch("src.stages.s12b_sql_retrieval.is_feature_enabled", side_effect=flag_override):
        with patch("src.stages.s12b_sql_retrieval.log_telemetry") as mock_log:
            schema_compacted = _build_scoped_schema_fallback(full_schema, "Show sales orders")
            assert "sales_order: id(int, PK)" in schema_compacted or "sales_order:" in schema_compacted
            assert "CREATE TABLE" not in schema_compacted
            assert "created_at" not in schema_compacted.lower()

            # Verify telemetry was logged
            compaction_logs = [
                call.kwargs for call in mock_log.call_args_list
                if call.kwargs.get("stage") == "schema_compaction_applied"
            ]
            assert len(compaction_logs) >= 1
            entry = compaction_logs[0]
            assert "before_tokens" in entry["extra"]
            assert "after_tokens" in entry["extra"]
            assert entry["extra"]["token_savings"] >= 0

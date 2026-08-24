"""Tests for Phase 8: Dynamic Schema Token Budget & Shadow Mode."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from src.utils.feature_flags import is_feature_enabled
from src.utils.golden_models import GoldenCase
from src.utils.schema_budget import (
    DEFAULT_SCHEMA_TOKEN_BUDGET,
    select_schema_within_budget,
)
from src.utils.schema_token_estimator import estimate_schema_tokens

GOLDEN_CASES_PATH = Path(__file__).resolve().parent / "golden" / "sql_repair" / "cases.json"


def test_estimate_schema_tokens_various_formats():
    """Test token estimation across string DDL, dictionary, list, and edge cases."""
    # 1. Plain DDL string
    ddl = "CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT, city TEXT);"
    tokens_str = estimate_schema_tokens(ddl)
    assert tokens_str > 0
    assert 10 <= tokens_str <= 30

    # 2. Dictionary format
    schema_dict = {
        "customers": ["id", "name", "city", "created_at"],
        "orders": ["id", "customer_id", "total_amount"],
    }
    tokens_dict = estimate_schema_tokens(schema_dict)
    assert tokens_dict > 0
    assert 15 <= tokens_dict <= 40

    # 3. Dict with 'ddl' key
    cand_dict = {"table_name": "orders", "ddl": ddl}
    tokens_cand = estimate_schema_tokens(cand_dict)
    assert tokens_cand == tokens_str

    # 4. Empty inputs
    assert estimate_schema_tokens("") == 0
    assert estimate_schema_tokens(None) == 0
    assert estimate_schema_tokens({}) == 0
    assert estimate_schema_tokens([]) == 0


def test_select_schema_within_budget_basic_and_ordering():
    """Test that candidates are selected in priority order and stop when budget is reached."""
    candidates = [
        {"table_name": f"tbl_{i}", "ddl": f"CREATE TABLE tbl_{i} (id INT, col_{i} TEXT);", "score": 1.0 - i * 0.1}
        for i in range(10)
    ]
    # Each candidate is roughly 15 tokens.
    # A budget of 50 tokens should fit around 3 candidates.
    selected, dropped = select_schema_within_budget(candidates, token_budget=50, id_key="table_name")

    assert len(selected) > 0
    assert len(dropped) > 0
    assert len(selected) + len(dropped) == 10

    # Check ordering preservation: first selected candidate MUST be tbl_0
    assert selected[0]["table_name"] == "tbl_0"
    assert selected[1]["table_name"] == "tbl_1"

    # Total tokens of selected must not exceed budget
    total_tokens = sum(estimate_schema_tokens(c) for c in selected)
    assert total_tokens <= 50


def test_select_schema_within_budget_oversized_first_candidate():
    """Test that the first candidate is included even if it alone exceeds the budget."""
    huge_ddl = "CREATE TABLE huge (" + ", ".join(f"col_{i} TEXT" for i in range(200)) + ");"
    cand_huge = {"table_name": "huge", "ddl": huge_ddl}
    cand_small = {"table_name": "small", "ddl": "CREATE TABLE small (id INT);"}

    huge_cost = estimate_schema_tokens(cand_huge)
    assert huge_cost > 100

    # Budget is tiny (10 tokens), but first candidate must be kept
    selected, dropped = select_schema_within_budget([cand_huge, cand_small], token_budget=10)

    assert len(selected) == 1
    assert selected[0]["table_name"] == "huge"
    assert len(dropped) == 1
    assert dropped[0]["table_name"] == "small"


def test_select_schema_within_budget_empty_and_graceful():
    """Test edge cases with empty or invalid candidates."""
    assert select_schema_within_budget([]) == ([], [])
    assert select_schema_within_budget(None) == ([], [])

    # Handled invalid candidates gracefully without crashing
    weird_candidates = [{"broken": 123}, "raw string", 42]
    sel, drop = select_schema_within_budget(weird_candidates, token_budget=1000)
    assert len(sel) == 3
    assert len(drop) == 0


def test_golden_cases_schema_budget_selection():
    """Subphase 8.5: Verify that required tables from all 19 Golden Cases are selected.
    
    For each GoldenCase:
    - Extract required tables.
    - Create candidate pool with required tables ranked top + 20 dummy noise tables.
    - Assert required tables are selected within budget (500 tokens).
    """
    assert GOLDEN_CASES_PATH.exists(), f"Missing golden cases file: {GOLDEN_CASES_PATH}"
    with open(GOLDEN_CASES_PATH, "r", encoding="utf-8") as f:
        cases_raw = json.load(f)

    golden_cases = [GoldenCase(**c) for c in cases_raw]
    assert len(golden_cases) >= 15

    for case in golden_cases:
        required_tables = list(case.schema_context.keys())
        if not required_tables:
            continue

        # Build candidate pool: required tables at the head, followed by noise tables
        candidates = []
        for tbl in required_tables:
            cols = case.schema_context[tbl]
            ddl = f"CREATE TABLE {tbl} (\n  " + ",\n  ".join(f"{col} TEXT" for col in cols) + "\n);"
            candidates.append({"table_name": tbl, "ddl": ddl, "priority": "high"})

        # Add 20 dummy noise tables
        for i in range(20):
            noise_tbl = f"noise_table_{i}"
            noise_ddl = f"CREATE TABLE {noise_tbl} (\n  id INTEGER,\n  info_{i} TEXT\n);"
            candidates.append({"table_name": noise_tbl, "ddl": noise_ddl, "priority": "noise"})

        # Run budget selector with 500 token budget
        selected, dropped = select_schema_within_budget(candidates, token_budget=500, id_key="table_name")

        selected_table_names = {c["table_name"] for c in selected}
        dropped_table_names = {c["table_name"] for c in dropped}

        # Assert every required table was selected and not dropped
        for req in required_tables:
            assert req in selected_table_names, (
                f"Golden Case {case.case_id}: Required table '{req}' was not selected!"
            )
            assert req not in dropped_table_names, (
                f"Golden Case {case.case_id}: Required table '{req}' was dropped!"
            )


@pytest.mark.asyncio
async def test_shadow_mode_and_feature_flag_integration():
    """Test that s12b_sql_retrieval correctly logs shadow telemetry and respects feature flag."""
    from src.stages.s12b_sql_retrieval import _build_scoped_schema_fallback

    full_schema = """
    CREATE TABLE sales_order (id INTEGER PRIMARY KEY, customer_id INTEGER, total_amount REAL);
    CREATE TABLE party (id INTEGER PRIMARY KEY, party_name TEXT, city TEXT);
    CREATE TABLE product (id INTEGER PRIMARY KEY, product_name TEXT, price REAL);
    CREATE TABLE audit_logs (id INTEGER PRIMARY KEY, user_id INTEGER, action TEXT, created_at TEXT);
    CREATE TABLE system_config (key TEXT PRIMARY KEY, val TEXT);
    """

    # 1. Feature Flag = False (Shadow Mode)
    with patch("src.stages.s12b_sql_retrieval.is_feature_enabled", return_value=False):
        with patch("src.stages.s12b_sql_retrieval.log_telemetry") as mock_log:
            schema_out = _build_scoped_schema_fallback(full_schema, "Show sales orders and customer names")
            assert "sales_order" in schema_out
            assert mock_log.called
            call_kwargs = mock_log.call_args.kwargs
            assert call_kwargs["stage"] == "schema_budget_shadow"
            assert call_kwargs["extra"]["token_budget_enabled"] is False
            assert "original_table_count" in call_kwargs["extra"]
            assert "budgeted_table_count" in call_kwargs["extra"]

    # 2. Feature Flag = True (Cutover)
    with patch("src.stages.s12b_sql_retrieval.is_feature_enabled", side_effect=lambda f: f == "token_budget_enabled"):
        with patch("src.stages.s12b_sql_retrieval.log_telemetry") as mock_log:
            schema_out = _build_scoped_schema_fallback(full_schema, "Show sales orders and customer names")
            assert "sales_order" in schema_out
            assert mock_log.called
            call_kwargs = mock_log.call_args.kwargs
            assert call_kwargs["stage"] == "schema_budget_applied"
            assert call_kwargs["extra"]["token_budget_enabled"] is True

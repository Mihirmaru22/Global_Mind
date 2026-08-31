"""Comprehensive End-to-End Integration Audit Test for Phases 0 through 3."""

import json
from pathlib import Path
import pytest

from scripts.analytics.baseline_aggregator import aggregate_baseline_metrics
from scripts.analytics.telemetry_parser import parse_telemetry_file
from src.utils.error_classification import classify_error, normalize_error
from src.utils.failure_capture import capture_sql_failure
from src.utils.feature_flags import is_feature_enabled
from src.utils.sql_safety import is_destructive_sql, parse_sql, validate_tables_and_columns
from src.utils.telemetry import (
    get_current_query_id,
    get_or_create_query_id,
    log_telemetry,
    set_current_query_id,
    timed_stage,
)


def test_phase_0_scaffolding_wiring():
    """Verify Phase 0 feature flags and SQL safety stubs."""
    flags = [
        "delta_repair_enabled",
        "token_budget_enabled",
        "schema_compaction_enabled",
        "sql_safety_enabled",
        "zero_row_handling_enabled",
        "fast_path_enabled",
    ]
    for flag in flags:
        assert is_feature_enabled(flag) is False, f"Flag {flag} must default to False"

    parsed = parse_sql("SELECT * FROM test")
    assert parsed["is_valid"] is True
    assert is_destructive_sql("DELETE FROM test") is True
    assert is_destructive_sql("SELECT id FROM test") is False
    valid, msg = validate_tables_and_columns("SELECT 1", {})
    assert valid is True and msg == ""


def test_full_phases_0_to_3_integration_pipeline(tmp_path, monkeypatch):
    """Simulate a full query lifecycle that encounters a DB execution error.

    Proves end-to-end integration across:
    - Phase 1 Context & Telemetry
    - Phase 3 Failure Capture & Normalization
    - Phase 2 Parser & Baseline Aggregator
    """
    test_telemetry_file = tmp_path / "telemetry_events.jsonl"
    test_failure_file = tmp_path / "failed_queries.jsonl"

    # Patch default log files to test isolated files
    monkeypatch.setattr("src.utils.telemetry.TELEMETRY_FILE", test_telemetry_file)
    monkeypatch.setattr("src.utils.failure_capture.DEFAULT_FAILURE_LOG_FILE", test_failure_file)

    # 1. Pipeline Start: Context & Query ID generation
    qid = get_or_create_query_id()
    assert qid.startswith("gm-q-")
    assert get_current_query_id() == qid

    # 2. Stage 1: Schema Retrieval (telemetry event 1)
    with timed_stage("schema_retrieval", query_id=qid) as s1:
        s1["extra"] = {"tables_found": ["orders", "products"]}

    # 3. Stage 2: SQL Generation (telemetry event 2)
    fake_sql = "SELECT fake_col, SUM(amount) FROM orders GROUP BY fake_col"
    with timed_stage("sql_generation", query_id=qid) as s2:
        s2["input_tokens"] = 9200
        s2["output_tokens"] = 120
        s2["provider"] = "groq"
        s2["model"] = "qwen/qwen3.6-27b"

    # 4. Stage 3: SQL Execution Failure (telemetry event 3 & failure capture)
    raw_db_exception = """Traceback (most recent call last):
  File "/usr/local/lib/python3.12/site-packages/db_driver/client.py", line 128, in execute
    raise OperationalError("psycopg2.errors.UndefinedColumn: column \\"fake_col\\" does not exist in table orders")
OperationalError: psycopg2.errors.UndefinedColumn: column "fake_col" does not exist in table orders"""

    try:
        with timed_stage("sql_execution", query_id=qid) as s3:
            s3["failure_type"] = "db_execution_error"
            raise RuntimeError(raw_db_exception)
    except Exception as exc:
        capture_sql_failure(
            query_id=qid,
            stage="sql_execution",
            failed_sql=fake_sql,
            raw_error=exc,
            error_type="db_execution_error",
            schema_tables=["orders"],
            file_path=test_failure_file,
        )

    # =========================================================================
    # ASSERTIONS (THE HARD CHECK)
    # =========================================================================

    # --- Check 1: Phase 1 Telemetry File Verification ---
    assert test_telemetry_file.exists(), "Telemetry file was not created"
    telem_lines = test_telemetry_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(telem_lines) == 3, f"Expected exactly 3 telemetry events, got {len(telem_lines)}"

    events = [json.loads(line) for line in telem_lines]
    for ev in events:
        assert ev["query_id"] == qid, f"Query ID mismatch in event: {ev}"

    assert events[0]["stage"] == "schema_retrieval"
    assert events[0]["success"] is True

    assert events[1]["stage"] == "sql_generation"
    assert events[1]["input_tokens"] == 9200
    assert events[1]["output_tokens"] == 120
    assert events[1]["success"] is True

    assert events[2]["stage"] == "sql_execution"
    assert events[2]["success"] is False
    assert events[2]["failure_type"] == "db_execution_error"

    # --- Check 2: Phase 3 Failure Capture Verification ---
    assert test_failure_file.exists(), "Failure log was not created"
    fail_lines = test_failure_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(fail_lines) == 1, f"Expected exactly 1 failure record, got {len(fail_lines)}"

    fail_record = json.loads(fail_lines[0])
    assert fail_record["query_id"] == qid
    assert fail_record["stage"] == "sql_execution"
    assert fail_record["error_type"] == "db_execution_error"
    assert fail_record["failed_sql"] == fake_sql
    assert fail_record["schema_tables"] == ["orders"]

    # Verify error normalization & sanitization
    norm_err = fail_record["normalized_error"]
    assert "Traceback" not in norm_err, "Traceback must be scrubbed from normalized error"
    assert "/usr/local" not in norm_err, "File path must be scrubbed from normalized error"
    assert "fake_col" in norm_err, "Core error message must be preserved"

    # --- Check 3: Phase 2 Parser & Baseline Aggregator Verification ---
    grouped = parse_telemetry_file(test_telemetry_file)
    assert len(grouped) == 1
    assert qid in grouped
    assert len(grouped[qid]) == 3

    metrics = aggregate_baseline_metrics(grouped)
    assert metrics.total_queries == 1
    assert metrics.successful_queries == 0
    assert metrics.failed_queries == 1
    assert metrics.success_rate == 0.0
    assert metrics.failure_rate == 100.0
    assert metrics.failure_distribution.get("db_execution_error") == 1
    assert metrics.total_tokens == (9200 + 120)

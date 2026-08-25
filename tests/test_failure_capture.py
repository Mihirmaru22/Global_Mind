"""Unit tests for Phase 3 Failure Capture Layer."""

import json
from pathlib import Path
import pytest

from src.utils.error_classification import normalize_error
from src.utils.failure_capture import capture_sql_failure


def test_normalize_error_stripping():
    # 1. Strips local file paths
    raw_path_err = "Error in /usr/local/lib/python3.12/site-packages/psycopg2/errors.py: Column 'x' does not exist"
    norm_path = normalize_error(raw_path_err)
    assert "[path]" in norm_path
    assert "/usr/local" not in norm_path

    # 2. Strips tracebacks
    raw_tb_err = """Traceback (most recent call last):
  File "/data/shared/app.py", line 45, in execute
    raise OperationalError("no such table: orders")
OperationalError: no such table: orders"""
    norm_tb = normalize_error(raw_tb_err)
    assert "Traceback" not in norm_tb
    assert "OperationalError: no such table: orders" in norm_tb

    # 3. Masks credentials
    raw_auth_err = "Connection failed: host=127.0.0.1 user=admin password=SuperSecretPassword123 port=3306"
    norm_auth = normalize_error(raw_auth_err)
    assert "password=***" in norm_auth
    assert "SuperSecretPassword123" not in norm_auth

    # 4. Truncation to 500 chars
    very_long_err = "Long error message " * 50
    norm_long = normalize_error(very_long_err)
    assert len(norm_long) <= 500
    assert norm_long.endswith("...")


def test_capture_sql_failure_to_jsonl(tmp_path):
    target_file = tmp_path / "failed_queries.jsonl"

    record = capture_sql_failure(
        query_id="gm-q-fail-001",
        stage="sql_execution",
        failed_sql="SELECT region_name, SUM(amount) FROM orders GROUP BY region_name",
        raw_error="psycopg2.errors.UndefinedColumn: column \"region_name\" does not exist in table orders",
        error_type="sql_validation_error",
        schema_tables=["orders"],
        file_path=target_file,
    )

    assert record["query_id"] == "gm-q-fail-001"
    assert record["stage"] == "sql_execution"
    assert record["error_type"] == "sql_validation_error"
    assert record["failed_sql"] == "SELECT region_name, SUM(amount) FROM orders GROUP BY region_name"
    assert "region_name" in record["normalized_error"]
    assert record["schema_tables"] == ["orders"]

    # Verify file content
    assert target_file.exists()
    lines = target_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    disk_record = json.loads(lines[0])
    assert disk_record["query_id"] == "gm-q-fail-001"
    assert disk_record["error_type"] == "sql_validation_error"


def test_capture_sql_failure_defensive_behavior(tmp_path):
    # Invalid directory path that cannot be written
    invalid_path = tmp_path / "non_existent_subdir" / "locked" / "fail.jsonl"

    # Should not raise exception
    res = capture_sql_failure(
        query_id="q-defensive",
        stage="sql_validation",
        failed_sql="SELECT * FROM missing",
        raw_error="Table not found",
        file_path=invalid_path,
    )
    assert res["query_id"] == "q-defensive"

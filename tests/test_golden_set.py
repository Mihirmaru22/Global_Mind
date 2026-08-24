"""Unit tests for the Golden Test Set data models, ingestion, and evaluation harness."""

from pathlib import Path
import json
import pytest

from scripts.golden.generate_synthetic_cases import generate_synthetic_cases
from scripts.golden.ingest_failures import anonymize_sql_and_error, ingest_failures
from src.utils.golden_models import GoldenCase
from tests.golden.run_golden_tests import (
    check_sql_syntax,
    dummy_noop_repair,
    mock_perfect_repair,
    run_golden_evaluation,
)


def test_golden_case_model_validation():
    """Verify GoldenCase model validation and schema defaults."""
    case = GoldenCase(
        case_id="test_001",
        description="Test case description",
        user_question="What is the revenue?",
        failed_sql="SELECT rev FROM sales",
        error_message='column "rev" does not exist',
        error_type="column_not_found",
        schema_context={"sales": ["id", "revenue"]},
        expected_sql_contains=["revenue", "FROM sales"],
        must_not_contain=["rev"],
        ideal_sql="SELECT revenue FROM sales",
    )
    assert case.case_id == "test_001"
    assert case.schema_context == {"sales": ["id", "revenue"]}
    assert "revenue" in case.expected_sql_contains
    assert "rev" in case.must_not_contain


def test_anonymize_sql_and_error():
    """Verify PII and credential scrubbing patterns."""
    raw_query = "SELECT * FROM users WHERE email = 'john.doe@domain.com' AND phone = '555-123-4567' AND ssn = '123-45-6789' AND token = 'bearer abcdef1234567890abcdef1234567890'"
    cleaned = anonymize_sql_and_error(raw_query)

    assert "john.doe@domain.com" not in cleaned
    assert "[EMAIL]" in cleaned
    assert "555-123-4567" not in cleaned
    assert "[PHONE]" in cleaned
    assert "123-45-6789" not in cleaned
    assert "[SSN]" in cleaned
    assert "bearer" not in cleaned.lower()
    assert "[API_KEY]" in cleaned


def test_syntax_checker():
    """Verify SQL syntax validator."""
    valid, err = check_sql_syntax("SELECT id, name FROM users WHERE id = 1")
    assert valid is True
    assert err is None

    invalid, err2 = check_sql_syntax("SELECT id FROM WHERE")
    assert invalid is False
    assert err2 is not None


def test_golden_evaluation_harness_with_mock_repair(tmp_path):
    """Verify that run_golden_evaluation achieves 100% on ideal SQL."""
    test_cases_file = tmp_path / "test_cases.json"
    generate_synthetic_cases(output_file=test_cases_file)

    summary = run_golden_evaluation(mock_perfect_repair, cases_file=test_cases_file)
    assert summary.total_cases >= 15
    assert summary.passed_cases == summary.total_cases
    assert summary.failed_cases == 0
    assert summary.pass_rate == 100.0


def test_golden_evaluation_harness_with_noop_repair(tmp_path):
    """Verify that run_golden_evaluation fails appropriately on broken SQL."""
    test_cases_file = tmp_path / "test_cases.json"
    generate_synthetic_cases(output_file=test_cases_file)

    summary = run_golden_evaluation(dummy_noop_repair, cases_file=test_cases_file)
    assert summary.passed_cases == 0
    assert summary.failed_cases == summary.total_cases
    assert summary.pass_rate == 0.0


def test_ingest_failures_to_draft_cases(tmp_path):
    """Verify conversion from failed_queries.jsonl to draft_cases.json."""
    mock_failure_log = tmp_path / "mock_failures.jsonl"
    mock_draft_output = tmp_path / "draft_cases.json"

    sample_record = {
        "timestamp": "2026-08-24T12:00:00Z",
        "query_id": "test-q-123",
        "stage": "sql_execution",
        "error_type": "column_not_found",
        "failed_sql": "SELECT non_existent FROM orders WHERE user_email = 'secret@corp.com'",
        "raw_error": 'column "non_existent" does not exist',
        "schema_tables": ["orders"],
    }
    mock_failure_log.write_text(json.dumps(sample_record) + "\n", encoding="utf-8")

    drafts = ingest_failures(
        input_file=mock_failure_log,
        output_file=mock_draft_output,
    )
    assert len(drafts) == 1
    assert drafts[0]["case_id"] == "draft_test-q-123"
    assert "secret@corp.com" not in drafts[0]["failed_sql"]
    assert "[EMAIL]" in drafts[0]["failed_sql"]
    assert mock_draft_output.exists()

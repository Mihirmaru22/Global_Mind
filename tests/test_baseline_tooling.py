"""Unit tests for Phase 2 Baseline Measurement Tooling."""

import json
from pathlib import Path
import pytest

from scripts.analytics.baseline_aggregator import aggregate_baseline_metrics, _percentile
from scripts.analytics.generate_baseline_report import format_baseline_markdown, generate_report
from scripts.analytics.telemetry_parser import parse_telemetry_file


def test_percentile_calculation():
    vals = [10, 20, 30, 40, 50]
    assert _percentile(vals, 0) == 10.0
    assert _percentile(vals, 50) == 30.0
    assert _percentile(vals, 100) == 50.0
    assert _percentile([], 50) == 0.0


def test_parse_telemetry_file_with_malformed_lines(tmp_path):
    log_file = tmp_path / "test_events.jsonl"
    lines = [
        json.dumps({"query_id": "q1", "stage": "schema_retrieval", "latency_ms": 50, "success": True}),
        "INVALID_CORRUPTED_LINE_WITHOUT_JSON",
        "2026-08-24 12:00:00 [INFO] " + json.dumps({"query_id": "q1", "stage": "sql_generation", "input_tokens": 1000, "output_tokens": 100, "latency_ms": 1500, "success": True}),
        json.dumps({"query_id": "q2", "stage": "sql_generation", "input_tokens": 500, "output_tokens": 50, "latency_ms": 800, "success": False, "failure_type": "rate_limit_error"}),
    ]
    log_file.write_text("\n".join(lines), encoding="utf-8")

    grouped = parse_telemetry_file(log_file)
    assert "q1" in grouped
    assert "q2" in grouped
    assert len(grouped["q1"]) == 2
    assert len(grouped["q2"]) == 1
    assert grouped["q1"][1]["input_tokens"] == 1000
    assert grouped["q2"][0]["failure_type"] == "rate_limit_error"


def test_aggregate_baseline_metrics():
    grouped = {
        "q1": [
            {"stage": "schema_retrieval", "latency_ms": 50, "success": True},
            {"stage": "sql_generation", "input_tokens": 9000, "output_tokens": 100, "latency_ms": 2000, "success": True},
            {"stage": "sql_execution", "latency_ms": 50, "success": True, "extra": {"rows_returned": 10, "empty_result": False}},
            {"stage": "final_response", "latency_ms": 3000, "success": True},
        ],
        "q2": [
            {"stage": "schema_retrieval", "latency_ms": 50, "success": True},
            {"stage": "sql_generation", "input_tokens": 9500, "output_tokens": 0, "latency_ms": 800, "success": False, "failure_type": "rate_limit_error"},
            {"stage": "final_response", "latency_ms": 900, "success": False, "failure_type": "rate_limit_error"},
        ],
        "q3": [
            {"stage": "sql_execution", "latency_ms": 40, "success": True, "extra": {"rows_returned": 0, "empty_result": True}},
            {"stage": "final_response", "latency_ms": 1500, "success": True},
        ],
    }

    metrics = aggregate_baseline_metrics(grouped)
    assert metrics.total_queries == 3
    assert metrics.successful_queries == 2
    assert metrics.failed_queries == 1
    assert metrics.success_rate == pytest.approx(66.67, 0.01)
    assert metrics.failure_distribution.get("rate_limit_error") == 1
    assert metrics.empty_result_count == 1
    assert metrics.total_tokens == (9100 + 9500)


def test_generate_report_end_to_end(tmp_path):
    log_file = tmp_path / "telemetry.jsonl"
    out_report = tmp_path / "baseline_report.md"

    events = [
        {"query_id": "q1", "stage": "sql_generation", "input_tokens": 5000, "output_tokens": 100, "latency_ms": 1200, "success": True},
        {"query_id": "q1", "stage": "final_response", "latency_ms": 1500, "success": True},
    ]
    log_file.write_text("\n".join(json.dumps(e) for e in events), encoding="utf-8")

    report_text = generate_report(log_file, out_report)
    assert "# SQL Pipeline Baseline Report" in report_text
    assert "Total Queries: **1**" in report_text
    assert out_report.exists()

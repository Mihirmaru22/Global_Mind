"""Unit tests for Phase 14: Rollout Tooling, Flag Management & ROI Analytics."""

from __future__ import annotations

import json
from pathlib import Path
import pytest
import yaml

from scripts.analytics.compare_telemetry import (
    compute_extended_metrics,
    format_delta,
    generate_comparison_table,
)
from scripts.analytics.generate_roi_report import generate_roi_markdown
from scripts.rollout.manage_flags import (
    TARGET_FLAGS,
    cmd_disable_all,
    cmd_enable,
    cmd_enable_all,
    cmd_status,
    load_flags,
)


def test_flag_manager_toggles_and_backups(tmp_path: Path):
    """Test 1: Flag manager toggles flags, creates backups, and handles validation."""
    test_flag_file = tmp_path / "feature_flags.yaml"
    initial_data = {"features": {flag: False for flag in TARGET_FLAGS}}
    with open(test_flag_file, "w", encoding="utf-8") as f:
        yaml.dump(initial_data, f)

    # 1. Enable single flag
    assert cmd_enable(test_flag_file, "delta_repair_enabled") == 0
    flags = load_flags(test_flag_file)["features"]
    assert flags["delta_repair_enabled"] is True
    assert flags["sql_safety_enabled"] is False

    # 2. Reject invalid flag
    assert cmd_enable(test_flag_file, "invalid_flag_xyz") == 1

    # 3. Enable all flags
    assert cmd_enable_all(test_flag_file) == 0
    flags = load_flags(test_flag_file)["features"]
    assert all(flags[f] is True for f in TARGET_FLAGS)

    # 4. Disable all flags (emergency rollback)
    assert cmd_disable_all(test_flag_file) == 0
    flags = load_flags(test_flag_file)["features"]
    assert all(flags[f] is False for f in TARGET_FLAGS)

    # 5. Status command executes cleanly
    assert cmd_status(test_flag_file) == 0


def test_comparator_and_roi_report_empty_data_graceful(tmp_path: Path):
    """Test 2: Comparator and ROI generator handle empty or zero-event files gracefully."""
    empty_baseline = tmp_path / "empty_base.jsonl"
    empty_optimized = tmp_path / "empty_opt.jsonl"
    empty_baseline.write_text("", encoding="utf-8")
    empty_optimized.write_text("", encoding="utf-8")

    report_file = tmp_path / "ROI_REPORT.md"

    # Should not crash on DivisionByZero
    content = generate_roi_markdown(empty_baseline, empty_optimized, report_file)
    assert report_file.exists()
    assert "# SQL Pipeline Optimization: Final ROI Report" in content
    assert "Token Consumption:" in content


def test_comparator_metric_calculations(tmp_path: Path):
    """Test 3: Extended metrics compute accurate repair and fast-path rates."""
    mock_events = {
        "q1": [
            {"stage": "sql_generation", "input_tokens": 100, "output_tokens": 50, "success": True},
            {"stage": "sql_repair", "input_tokens": 50, "output_tokens": 20, "success": True},
            {"stage": "final_response", "latency_ms": 1200.0, "success": True},
        ],
        "q2": [
            {"stage": "sql_generation", "input_tokens": 80, "output_tokens": 40, "success": True},
            {"stage": "synthesis_bypassed", "success": True},
            {"stage": "final_response", "latency_ms": 400.0, "success": True},
        ],
    }

    metrics = compute_extended_metrics(mock_events)
    assert metrics["total_queries"] == 2
    assert metrics["repair_attempts"] == 1
    assert metrics["repair_success_rate"] == 100.0
    assert metrics["fast_path_bypasses"] == 1
    assert metrics["fast_path_rate"] == 50.0

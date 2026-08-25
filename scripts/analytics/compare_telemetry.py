#!/usr/bin/env python3
"""A/B Telemetry Comparator: ingests two JSONL telemetry files and computes performance deltas."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.analytics.baseline_aggregator import aggregate_baseline_metrics, BaselineMetrics
from scripts.analytics.telemetry_parser import parse_telemetry_file


def compute_extended_metrics(grouped_events: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """Compute standard baseline metrics plus repair success rate and fast-path bypass rate."""
    base = aggregate_baseline_metrics(grouped_events)

    total_queries = len(grouped_events)
    repair_attempts = 0
    repair_successes = 0
    synthesis_bypasses = 0

    for qid, events in grouped_events.items():
        for event in events:
            stage = event.get("stage", "")
            success = event.get("success", True)
            if stage == "sql_repair":
                repair_attempts += 1
                if success:
                    repair_successes += 1
            elif stage == "synthesis_bypassed":
                synthesis_bypasses += 1

    repair_success_rate = (
        (repair_successes / repair_attempts * 100.0) if repair_attempts > 0 else 0.0
    )
    fast_path_rate = (
        (synthesis_bypasses / total_queries * 100.0) if total_queries > 0 else 0.0
    )

    return {
        "base": base,
        "total_queries": total_queries,
        "success_rate": base.success_rate,
        "failure_rate": base.failure_rate,
        "avg_tokens": base.avg_tokens_per_query,
        "p95_tokens": base.p95_tokens_per_query,
        "avg_latency_ms": base.avg_latency_ms,
        "repair_success_rate": repair_success_rate,
        "repair_attempts": repair_attempts,
        "fast_path_rate": fast_path_rate,
        "fast_path_bypasses": synthesis_bypasses,
    }


def format_delta(baseline_val: float, optimized_val: float, higher_is_better: bool = True) -> str:
    """Format the percentage delta between baseline and optimized values."""
    if baseline_val == 0.0:
        if optimized_val == 0.0:
            return "0.0%"
        return "+100.0%" if higher_is_better else "-100.0%"

    pct_change = ((optimized_val - baseline_val) / baseline_val) * 100.0
    sign = "+" if pct_change > 0 else ""
    return f"{sign}{pct_change:.1f}%"


def generate_comparison_table(b_metrics: dict[str, Any], o_metrics: dict[str, Any]) -> str:
    """Generate Markdown and console table comparing baseline vs optimized."""
    rows = [
        ("Total Queries", f"{b_metrics['total_queries']}", f"{o_metrics['total_queries']}", format_delta(b_metrics['total_queries'], o_metrics['total_queries'], True)),
        ("Success Rate (%)", f"{b_metrics['success_rate']:.1f}%", f"{o_metrics['success_rate']:.1f}%", format_delta(b_metrics['success_rate'], o_metrics['success_rate'], True)),
        ("Failure Rate (%)", f"{b_metrics['failure_rate']:.1f}%", f"{o_metrics['failure_rate']:.1f}%", format_delta(b_metrics['failure_rate'], o_metrics['failure_rate'], False)),
        ("Avg Tokens / Query", f"{b_metrics['avg_tokens']:.0f}", f"{o_metrics['avg_tokens']:.0f}", format_delta(b_metrics['avg_tokens'], o_metrics['avg_tokens'], False)),
        ("P95 Tokens / Query", f"{b_metrics['p95_tokens']:.0f}", f"{o_metrics['p95_tokens']:.0f}", format_delta(b_metrics['p95_tokens'], o_metrics['p95_tokens'], False)),
        ("Avg Latency (ms)", f"{b_metrics['avg_latency_ms']:.0f}ms", f"{o_metrics['avg_latency_ms']:.0f}ms", format_delta(b_metrics['avg_latency_ms'], o_metrics['avg_latency_ms'], False)),
        ("Repair Success Rate (%)", f"{b_metrics['repair_success_rate']:.1f}%", f"{o_metrics['repair_success_rate']:.1f}%", format_delta(b_metrics['repair_success_rate'], o_metrics['repair_success_rate'], True)),
        ("Fast-Path Bypass Rate (%)", f"{b_metrics['fast_path_rate']:.1f}%", f"{o_metrics['fast_path_rate']:.1f}%", format_delta(b_metrics['fast_path_rate'], o_metrics['fast_path_rate'], True)),
    ]

    header = f"| {'Metric':<26} | {'Baseline':<12} | {'Optimized':<12} | {'Delta (%)':<12} |\n|:{'-'*26}-|:{'-'*12}-|:{'-'*12}-|:{'-'*12}-:|"
    table_lines = [header]
    for m, b, o, d in rows:
        table_lines.append(f"| {m:<26} | {b:<12} | {o:<12} | {d:<12} |")
    return "\n".join(table_lines)


def compare_telemetry_files(baseline_path: str | Path, optimized_path: str | Path) -> str:
    """Compare two telemetry files and return formatted comparison table."""
    b_events = parse_telemetry_file(baseline_path)
    o_events = parse_telemetry_file(optimized_path)

    b_metrics = compute_extended_metrics(b_events)
    o_metrics = compute_extended_metrics(o_events)

    return generate_comparison_table(b_metrics, o_metrics)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare A/B Telemetry JSONL files.")
    parser.add_argument("--baseline", required=True, help="Path to baseline telemetry JSONL")
    parser.add_argument("--optimized", required=True, help="Path to optimized telemetry JSONL")

    args = parser.parse_args(argv)

    table = compare_telemetry_files(args.baseline, args.optimized)
    print("\n" + table + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

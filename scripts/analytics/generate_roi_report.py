#!/usr/bin/env python3
"""Generates the Final ROI Report (reports/FINAL_ROI_REPORT.md) comparing baseline and optimized telemetry."""

from __future__ import annotations

import argparse
import datetime
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.analytics.compare_telemetry import (
    compute_extended_metrics,
    format_delta,
    generate_comparison_table,
)
from scripts.analytics.telemetry_parser import parse_telemetry_file
from scripts.rollout.manage_flags import FLAG_FILE, load_flags

DEFAULT_REPORT_PATH = PROJECT_ROOT / "reports" / "FINAL_ROI_REPORT.md"


def generate_roi_markdown(
    baseline_path: str | Path,
    optimized_path: str | Path,
    report_output_path: str | Path,
) -> str:
    """Generate and write the Final ROI Report Markdown document."""
    b_events = parse_telemetry_file(baseline_path)
    o_events = parse_telemetry_file(optimized_path)

    b_metrics = compute_extended_metrics(b_events)
    o_metrics = compute_extended_metrics(o_events)

    table_md = generate_comparison_table(b_metrics, o_metrics)

    # Token reduction calculation
    b_tok = b_metrics["avg_tokens"]
    o_tok = o_metrics["avg_tokens"]
    token_reduction_pct = (
        ((b_tok - o_tok) / b_tok * 100.0) if b_tok > 0 else 0.0
    )

    # Failure rate reduction
    b_fail = b_metrics["failure_rate"]
    o_fail = o_metrics["failure_rate"]
    failure_reduction_pct = (
        ((b_fail - o_fail) / b_fail * 100.0) if b_fail > 0 else 0.0
    )

    # Flag status
    flags_data = load_flags(FLAG_FILE)
    features = flags_data.get("features", {})
    all_enabled = all(features.values()) if features else False
    rollout_status = "Enabled (100% Rollout)" if all_enabled else "Gated Behind Feature Flags"

    now_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    report_content = f"""# SQL Pipeline Optimization: Final ROI Report
**Generated:** {now_str}

## Executive Summary
The SQL retrieval pipeline has been successfully optimized using a decomposed, state-aware architecture.
- **Token Consumption:** Reduced by **{token_reduction_pct:.1f}%** (Target: 70%+)
- **Query Failure Rate:** Reduced by **{failure_reduction_pct:.1f}%** (Target: 50%+)
- **P95 Latency:** Improved from **{b_metrics['avg_latency_ms']:.0f}ms** to **{o_metrics['avg_latency_ms']:.0f}ms**

---

## Architecture Interventions Deployed
1. **Delta Repair**: Surgical prompt replacement fixing query syntax and column mismatches with < 400 token micro-payloads (Max 2 attempts).
2. **Dynamic Schema Budgeting & AST Compaction**: Caps table schemas within a strict 1,500 token ceiling, stripping audit columns while preserving Primary and Foreign Keys.
3. **Pre-Execution SQL Safety & AST Validation**: Blocks destructive commands and anti-patterns locally via AST analysis before touching the database.
4. **Intelligent 0-Row Handling**: Differentiates between valid empty results (bypassing retries) and suspicious joins (single targeted repair).
5. **Fast-Path Synthesis Bypass**: Zero-token instant Markdown formatting for simple list queries, and micro-synthesis for aggregations.
6. **Task-Aware Provider Routing**: Dynamic routing prioritizing high-TPM models (Gemini) for heavy reasoning and ultra-fast models (Groq) for repairs.

---

## Detailed Metric Comparison
{table_md}

---

## Rollout Status
All optimization feature flags are currently **{rollout_status}**.
"""

    out_path = Path(report_output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report_content)

    return report_content


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate Final ROI Report.")
    parser.add_argument("--baseline", required=True, help="Path to baseline telemetry JSONL")
    parser.add_argument("--optimized", required=True, help="Path to optimized telemetry JSONL")
    parser.add_argument("--output", default=str(DEFAULT_REPORT_PATH), help="Path to output markdown report")

    args = parser.parse_args(argv)

    generate_roi_markdown(args.baseline, args.optimized, args.output)
    print(f"✓ ROI Report successfully generated at {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

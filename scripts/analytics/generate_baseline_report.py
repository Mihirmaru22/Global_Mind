"""CLI tool to generate a comprehensive SQL Pipeline Baseline Measurement Report from telemetry logs."""

from __future__ import annotations

import argparse
import datetime
import sys
from pathlib import Path

# Add project root to sys.path if invoked directly
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.analytics.baseline_aggregator import aggregate_baseline_metrics, BaselineMetrics
from scripts.analytics.telemetry_parser import parse_telemetry_file

DEFAULT_INPUT_FILE = PROJECT_ROOT / "data" / "telemetry_events.jsonl"
DEFAULT_OUTPUT_FILE = PROJECT_ROOT / "reports" / "baseline_report.md"


def format_baseline_markdown(metrics: BaselineMetrics, input_path: str) -> str:
    """Format aggregated metrics into a standardized Markdown report."""
    now_str = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d %H:%M:%S UTC")

    lines: list[str] = [
        "# SQL Pipeline Baseline Report",
        f"Generated: {now_str}",
        f"Data Source: `{input_path}`",
        "",
        "## 1. Volume & Reliability",
        f"- Total Queries: **{metrics.total_queries}**",
        f"- Success Rate: **{metrics.success_rate:.2f}%** ({metrics.successful_queries} succeeded)",
        f"- Failure Rate: **{metrics.failure_rate:.2f}%** ({metrics.failed_queries} failed)",
        "",
        "## 2. Failure Distribution",
    ]

    if metrics.failure_distribution:
        lines.append("| Failure Type | Count | Percentage |")
        lines.append("|---|---|---|")
        for ftype, count in sorted(metrics.failure_distribution.items(), key=lambda x: x[1], reverse=True):
            pct = metrics.failure_percentages.get(ftype, 0.0)
            lines.append(f"| `{ftype}` | {count} | {pct:.2f}% |")
    else:
        lines.append("*No failures recorded in dataset.*")

    lines.extend([
        "",
        "## 3. Token Consumption",
        f"- Average Tokens/Query: **{metrics.avg_tokens_per_query:,.1f}**",
        f"- Median Tokens/Query: **{metrics.median_tokens_per_query:,.1f}**",
        f"- P95 Tokens/Query: **{metrics.p95_tokens_per_query:,.1f}**",
        f"- Total Tokens Consumed: **{metrics.total_tokens:,}**",
        "",
        "## 4. Latency",
        f"- Average Latency: **{metrics.avg_latency_ms:,.2f} ms**",
        f"- Median Latency: **{metrics.median_latency_ms:,.2f} ms**",
        f"- P95 Latency: **{metrics.p95_latency_ms:,.2f} ms**",
        "",
        "## 5. Empty Results & Retries",
        f"- Empty Result Rate: **{metrics.empty_result_rate:.2f}%** ({metrics.empty_result_count} queries)",
        f"- Average LLM Calls per Query: **{metrics.avg_llm_calls_per_query:.2f}**",
        f"- Max Retries / LLM Calls Seen: **{metrics.max_retries_seen}**",
        "",
    ])

    return "\n".join(lines)


def generate_report(input_path: str | Path, output_path: str | Path) -> str:
    """Parse telemetry, aggregate metrics, save markdown report, and print summary."""
    in_file = Path(input_path)
    out_file = Path(output_path)

    grouped_events = parse_telemetry_file(in_file)
    metrics = aggregate_baseline_metrics(grouped_events)
    report_content = format_baseline_markdown(metrics, str(in_file))

    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(report_content)

    return report_content


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate SQL Pipeline Baseline Report from telemetry events.")
    parser.add_argument(
        "--input",
        type=str,
        default=str(DEFAULT_INPUT_FILE),
        help=f"Path to input telemetry JSONL file (default: {DEFAULT_INPUT_FILE})",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=str(DEFAULT_OUTPUT_FILE),
        help=f"Path to output markdown report (default: {DEFAULT_OUTPUT_FILE})",
    )

    args = parser.parse_args()
    report = generate_report(input_path=args.input, output_path=args.output)
    print(report)
    print(f"\nReport successfully saved to: {args.output}")


if __name__ == "__main__":
    main()

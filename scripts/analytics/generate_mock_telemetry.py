"""Generates realistic mock telemetry data to test the baseline aggregator and reporting pipeline."""

from __future__ import annotations

import argparse
import datetime
import json
import random
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_OUTPUT_FILE = DATA_DIR / "mock_telemetry_events.jsonl"


def generate_mock_events(count: int = 200, output_path: Path | str = DEFAULT_OUTPUT_FILE) -> int:
    """Generate mock telemetry events across a distribution of query outcomes."""
    out_file = Path(output_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)

    events: list[dict] = []
    base_time = datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=6)

    for i in range(count):
        qid = f"gm-mock-{uuid.uuid4().hex[:12]}"
        query_start = base_time + datetime.timedelta(seconds=i * 25 + random.uniform(1, 10))
        r = random.random()

        if r < 0.70:
            # 1. Successful Query (70%)
            # Schema retrieval
            events.append({
                "query_id": qid,
                "stage": "schema_retrieval",
                "timestamp": query_start.isoformat(),
                "latency_ms": random.uniform(40, 120),
                "success": True,
                "failure_type": None,
                "extra": {"schema_chars": random.randint(3000, 8500)},
            })
            # SQL Generation (Legacy large prompt: 8.5k - 11k tokens)
            gen_in = random.randint(8500, 11500)
            gen_out = random.randint(80, 220)
            events.append({
                "query_id": qid,
                "stage": "sql_generation",
                "timestamp": (query_start + datetime.timedelta(milliseconds=150)).isoformat(),
                "input_tokens": gen_in,
                "output_tokens": gen_out,
                "latency_ms": random.uniform(1200, 2400),
                "success": True,
                "failure_type": None,
                "provider": "groq",
                "model": "qwen/qwen3.6-27b",
                "extra": {"attempt": 0, "has_sql": True},
            })
            # SQL Validation
            events.append({
                "query_id": qid,
                "stage": "sql_validation",
                "timestamp": (query_start + datetime.timedelta(milliseconds=2100)).isoformat(),
                "latency_ms": random.uniform(5, 25),
                "success": True,
                "failure_type": None,
            })
            # SQL Execution
            rows = random.randint(1, 45)
            events.append({
                "query_id": qid,
                "stage": "sql_execution",
                "timestamp": (query_start + datetime.timedelta(milliseconds=2150)).isoformat(),
                "latency_ms": random.uniform(25, 90),
                "success": True,
                "failure_type": None,
                "extra": {"rows_returned": rows, "empty_result": False},
            })
            # Synthesis
            syn_in = random.randint(2500, 4500)
            syn_out = random.randint(150, 350)
            events.append({
                "query_id": qid,
                "stage": "synthesis",
                "timestamp": (query_start + datetime.timedelta(milliseconds=2300)).isoformat(),
                "input_tokens": syn_in,
                "output_tokens": syn_out,
                "latency_ms": random.uniform(900, 1800),
                "success": True,
                "failure_type": None,
                "provider": "groq",
                "model": "qwen/qwen3.6-27b",
            })
            # Final response
            events.append({
                "query_id": qid,
                "stage": "final_response",
                "timestamp": (query_start + datetime.timedelta(milliseconds=4200)).isoformat(),
                "latency_ms": random.uniform(3200, 4800),
                "success": True,
                "failure_type": None,
            })

        elif r < 0.80:
            # 2. SQL Validation Error with 2-3 Full Retries (10%)
            attempts = random.choice([2, 3])
            total_query_lat = 100.0
            events.append({
                "query_id": qid,
                "stage": "schema_retrieval",
                "timestamp": query_start.isoformat(),
                "latency_ms": 60,
                "success": True,
                "failure_type": None,
            })
            for att in range(attempts):
                in_tok = random.randint(9000, 12000)
                out_tok = random.randint(90, 180)
                lat = random.uniform(1400, 2200)
                total_query_lat += lat
                events.append({
                    "query_id": qid,
                    "stage": "sql_generation",
                    "timestamp": (query_start + datetime.timedelta(milliseconds=int(total_query_lat))).isoformat(),
                    "input_tokens": in_tok,
                    "output_tokens": out_tok,
                    "latency_ms": lat,
                    "success": True,
                    "failure_type": None,
                    "provider": "groq",
                    "model": "qwen/qwen3.6-27b",
                    "extra": {"attempt": att},
                })
                events.append({
                    "query_id": qid,
                    "stage": "sql_validation",
                    "timestamp": (query_start + datetime.timedelta(milliseconds=int(total_query_lat + 20))).isoformat(),
                    "latency_ms": 15,
                    "success": False,
                    "failure_type": "sql_validation_error",
                    "extra": {"error": "Column 'non_existent_field' does not exist"},
                })
            events.append({
                "query_id": qid,
                "stage": "final_response",
                "timestamp": (query_start + datetime.timedelta(milliseconds=int(total_query_lat + 100))).isoformat(),
                "latency_ms": total_query_lat + 100,
                "success": False,
                "failure_type": "sql_validation_error",
            })

        elif r < 0.90:
            # 3. Empty Result Query (10%)
            events.append({
                "query_id": qid,
                "stage": "schema_retrieval",
                "timestamp": query_start.isoformat(),
                "latency_ms": 70,
                "success": True,
                "failure_type": None,
            })
            events.append({
                "query_id": qid,
                "stage": "sql_generation",
                "timestamp": (query_start + datetime.timedelta(milliseconds=100)).isoformat(),
                "input_tokens": random.randint(8500, 10500),
                "output_tokens": 100,
                "latency_ms": 1500,
                "success": True,
                "failure_type": None,
                "provider": "groq",
                "model": "qwen/qwen3.6-27b",
            })
            events.append({
                "query_id": qid,
                "stage": "sql_execution",
                "timestamp": (query_start + datetime.timedelta(milliseconds=1700)).isoformat(),
                "latency_ms": 40,
                "success": True,
                "failure_type": "empty_result",
                "extra": {"rows_returned": 0, "empty_result": True},
            })
            events.append({
                "query_id": qid,
                "stage": "final_response",
                "timestamp": (query_start + datetime.timedelta(milliseconds=1900)).isoformat(),
                "latency_ms": 1900,
                "success": True,
                "failure_type": None,
            })

        elif r < 0.95:
            # 4. Rate Limit Error (5%)
            events.append({
                "query_id": qid,
                "stage": "schema_retrieval",
                "timestamp": query_start.isoformat(),
                "latency_ms": 50,
                "success": True,
                "failure_type": None,
            })
            events.append({
                "query_id": qid,
                "stage": "sql_generation",
                "timestamp": (query_start + datetime.timedelta(milliseconds=100)).isoformat(),
                "input_tokens": 0,
                "output_tokens": 0,
                "latency_ms": 800,
                "success": False,
                "failure_type": "rate_limit_error",
                "provider": "groq",
                "model": "qwen/qwen3.6-27b",
                "extra": {"error": "429 Too Many Requests: TPM rate limit exceeded"},
            })
            events.append({
                "query_id": qid,
                "stage": "final_response",
                "timestamp": (query_start + datetime.timedelta(milliseconds=950)).isoformat(),
                "latency_ms": 950,
                "success": False,
                "failure_type": "rate_limit_error",
            })

        else:
            # 5. Timeout Error (5%)
            events.append({
                "query_id": qid,
                "stage": "schema_retrieval",
                "timestamp": query_start.isoformat(),
                "latency_ms": 50,
                "success": True,
                "failure_type": None,
            })
            events.append({
                "query_id": qid,
                "stage": "sql_generation",
                "timestamp": (query_start + datetime.timedelta(milliseconds=100)).isoformat(),
                "input_tokens": 9000,
                "output_tokens": 0,
                "latency_ms": 25000,
                "success": False,
                "failure_type": "timeout_error",
                "provider": "groq",
                "model": "qwen/qwen3.6-27b",
            })
            events.append({
                "query_id": qid,
                "stage": "final_response",
                "timestamp": (query_start + datetime.timedelta(milliseconds=25200)).isoformat(),
                "latency_ms": 25200,
                "success": False,
                "failure_type": "timeout_error",
            })

    # Shuffle events slightly to simulate real interleaving
    random.shuffle(events)

    with open(out_file, "w", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")
        # Add a benign prefixed line and a malformed line to test parser resilience
        f.write('2026-08-24 12:00:00 [INFO] {"query_id": "gm-mock-resilient-1", "stage": "schema_retrieval", "latency_ms": 45, "success": true}\n')
        f.write("MALFORMED_LINE_CORRUPTED_ENTRY_SKIP_ME\n")

    print(f"Generated {len(events) + 1} telemetry events for {count} mock queries at: {out_file}")
    return len(events)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate mock telemetry events.")
    parser.add_argument("--count", type=int, default=200, help="Number of unique mock queries to generate (default: 200)")
    parser.add_argument("--output", type=str, default=str(DEFAULT_OUTPUT_FILE), help="Output path for JSONL file")
    args = parser.parse_args()
    generate_mock_events(count=args.count, output_path=args.output)


if __name__ == "__main__":
    main()

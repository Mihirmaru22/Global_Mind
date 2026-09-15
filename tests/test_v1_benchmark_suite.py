"""Pytest integration for the V1 Golden Benchmark Suite (52 cases).

Runs deterministically via fixture cache in < 1 second.
"""

from __future__ import annotations

import pytest
from tests.golden.run_v1_benchmark import BenchmarkEvaluator, BENCHMARK_FILE
import json


@pytest.fixture(scope="module")
def benchmark_cases():
    return json.loads(BENCHMARK_FILE.read_text(encoding="utf-8"))


def test_benchmark_suite_has_52_cases(benchmark_cases):
    assert len(benchmark_cases) == 52, f"Expected 52 cases in benchmark, found {len(benchmark_cases)}"


@pytest.mark.asyncio
async def test_v1_benchmark_full_suite_execution():
    """Execute the full 52-case benchmark suite using the deterministic cache."""
    evaluator = BenchmarkEvaluator(use_cache=True, record=False)
    summary = await evaluator.run_suite()

    assert summary["total_cases"] == 52
    assert summary["failed_cases"] == 0, f"Benchmark had failures: {[r for r in summary['results'] if not r['passed']]}"
    assert summary["pass_rate_percent"] == 100.0
    assert summary["total_time_seconds"] < 3.0, f"Suite took too long: {summary['total_time_seconds']}s"

    # Category checks
    categories = summary["by_category"]
    assert categories["TEMPORAL"]["passed"] == 8
    assert categories["SOFT_DELETE"]["passed"] == 6
    assert categories["AGGREGATION"]["passed"] == 8
    assert categories["AMBIGUOUS_ENTITIES"]["passed"] == 7
    assert categories["ACRONYMS"]["passed"] == 6
    assert categories["RAG_GROUNDING"]["passed"] == 8
    assert categories["OUT_OF_SCOPE"]["passed"] == 4
    assert categories["KNOWN_REGRESSIONS"]["passed"] == 5

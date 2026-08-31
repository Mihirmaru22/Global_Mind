"""Aggregates parsed telemetry events into baseline performance and failure metrics."""

from __future__ import annotations

import math
import statistics
from collections import Counter
from dataclasses import dataclass, field
from typing import Any


def _percentile(values: list[float | int], p: float) -> float:
    """Calculate the p-th percentile (0 <= p <= 100) using linear interpolation."""
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    idx = (len(sorted_vals) - 1) * (p / 100.0)
    floor_idx = int(math.floor(idx))
    ceil_idx = int(math.ceil(idx))
    if floor_idx == ceil_idx:
        return float(sorted_vals[floor_idx])
    d = idx - floor_idx
    return float(sorted_vals[floor_idx] * (1.0 - d) + sorted_vals[ceil_idx] * d)


@dataclass
class BaselineMetrics:
    total_queries: int = 0
    successful_queries: int = 0
    failed_queries: int = 0
    success_rate: float = 0.0
    failure_rate: float = 0.0

    failure_distribution: dict[str, int] = field(default_factory=dict)
    failure_percentages: dict[str, float] = field(default_factory=dict)

    total_tokens: int = 0
    avg_tokens_per_query: float = 0.0
    median_tokens_per_query: float = 0.0
    p95_tokens_per_query: float = 0.0

    avg_latency_ms: float = 0.0
    median_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0

    empty_result_count: int = 0
    empty_result_rate: float = 0.0

    avg_llm_calls_per_query: float = 0.0
    max_retries_seen: int = 0


def aggregate_baseline_metrics(
    grouped_events: dict[str, list[dict[str, Any]]]
) -> BaselineMetrics:
    """Aggregate per-query telemetry events into comprehensive baseline metrics."""
    if not grouped_events:
        return BaselineMetrics()

    total_queries = len(grouped_events)
    successful_count = 0
    failed_count = 0
    failure_counter: Counter[str] = Counter()

    token_counts_per_query: list[int] = []
    latencies_per_query: list[float] = []
    llm_call_counts_per_query: list[int] = []
    empty_result_queries = 0

    LLM_STAGES = frozenset({
        "sql_generation",
        "synthesis",
        "llm_call",
        "sql_repair",
        "intent_extraction",
    })

    for qid, events in grouped_events.items():
        query_success = True
        query_failure_type: str | None = None
        query_total_tokens = 0
        query_latency_ms: float | None = None
        llm_calls = 0
        has_empty_result = False

        # Look for final_response event if present
        final_event = next((e for e in events if e.get("stage") == "final_response"), None)

        for event in events:
            stage = event.get("stage", "")
            success = event.get("success", True)
            failure_type = event.get("failure_type")

            # Token tracking across LLM stages
            if stage in LLM_STAGES:
                llm_calls += 1
                in_tok = event.get("input_tokens", 0) or 0
                out_tok = event.get("output_tokens", 0) or 0
                query_total_tokens += (in_tok + out_tok)

            # Failure tracking
            if not success or failure_type:
                query_success = False
                if not query_failure_type and failure_type:
                    query_failure_type = failure_type

            # Empty result tracking in sql_execution
            if stage == "sql_execution":
                extra = event.get("extra") or {}
                if extra.get("empty_result") or extra.get("rows_returned") == 0:
                    has_empty_result = True
                if failure_type == "empty_result":
                    has_empty_result = True

        # Latency calculation
        if final_event and final_event.get("latency_ms") is not None:
            query_latency_ms = float(final_event["latency_ms"])
        else:
            # Sum latencies across stages for this query
            query_latency_ms = sum(float(e.get("latency_ms", 0.0)) for e in events)

        if final_event is not None:
            if not final_event.get("success", True):
                query_success = False
                if final_event.get("failure_type"):
                    query_failure_type = final_event["failure_type"]

        if query_success:
            successful_count += 1
        else:
            failed_count += 1
            primary_failure = query_failure_type or "unknown_error"
            failure_counter[primary_failure] += 1

        if has_empty_result:
            empty_result_queries += 1

        token_counts_per_query.append(query_total_tokens)
        latencies_per_query.append(query_latency_ms or 0.0)
        llm_call_counts_per_query.append(llm_calls)

    success_rate = round((successful_count / total_queries) * 100.0, 2)
    failure_rate = round((failed_count / total_queries) * 100.0, 2)
    empty_rate = round((empty_result_queries / total_queries) * 100.0, 2)

    total_tokens_sum = sum(token_counts_per_query)
    avg_tokens = round(statistics.mean(token_counts_per_query), 2) if token_counts_per_query else 0.0
    med_tokens = round(statistics.median(token_counts_per_query), 2) if token_counts_per_query else 0.0
    p95_tokens = round(_percentile(token_counts_per_query, 95), 2)

    avg_latency = round(statistics.mean(latencies_per_query), 2) if latencies_per_query else 0.0
    med_latency = round(statistics.median(latencies_per_query), 2) if latencies_per_query else 0.0
    p95_latency = round(_percentile(latencies_per_query, 95), 2)

    avg_llm_calls = round(statistics.mean(llm_call_counts_per_query), 2) if llm_call_counts_per_query else 0.0
    max_retries = max(llm_call_counts_per_query) if llm_call_counts_per_query else 0

    failure_percentages = {
        k: round((v / failed_count) * 100.0, 2) if failed_count > 0 else 0.0
        for k, v in failure_counter.items()
    }

    return BaselineMetrics(
        total_queries=total_queries,
        successful_queries=successful_count,
        failed_queries=failed_count,
        success_rate=success_rate,
        failure_rate=failure_rate,
        failure_distribution=dict(failure_counter),
        failure_percentages=failure_percentages,
        total_tokens=total_tokens_sum,
        avg_tokens_per_query=avg_tokens,
        median_tokens_per_query=med_tokens,
        p95_tokens_per_query=p95_tokens,
        avg_latency_ms=avg_latency,
        median_latency_ms=med_latency,
        p95_latency_ms=p95_latency,
        empty_result_count=empty_result_queries,
        empty_result_rate=empty_rate,
        avg_llm_calls_per_query=avg_llm_calls,
        max_retries_seen=max_retries,
    )

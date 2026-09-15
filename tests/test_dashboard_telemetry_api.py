"""Unit and integration tests for Local Telemetry Dashboard API (Phase 4).

Validates:
1. Endpoints return valid 200 responses with expected schemas:
   - /api/ui/telemetry/overview
   - /api/ui/telemetry/failures
   - /api/ui/telemetry/guards
   - /api/ui/telemetry/traces
2. Guardrail #4: Sub-millisecond response time (< 5ms ceiling) via InMemoryTelemetryAggregator.
3. Accurate statistical reflections of recorded traces, failures, and guard blocks.
"""

from __future__ import annotations

import time
import pytest
from httpx import ASGITransport, AsyncClient

from src.main import app
from src.utils.error_classification import FailureCategory
from src.utils.trace_writer import InMemoryTelemetryAggregator, get_telemetry_aggregator


@pytest.fixture(autouse=True)
def clean_aggregator():
    """Ensure aggregator is clean before and after each test."""
    aggregator = get_telemetry_aggregator()
    aggregator.clear()
    yield aggregator
    aggregator.clear()


@pytest.mark.asyncio
async def test_telemetry_overview_empty():
    """Verify overview endpoint returns valid defaults when no traces exist."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/ui/telemetry/overview")
        assert res.status_code == 200
        data = res.json()
        assert data["total_requests"] == 0
        assert data["success_rate_percent"] == 100.0
        assert data["fallback_rate_percent"] == 0.0
        assert data["sample_size"] == 0
        assert "latency_p50_ms" in data
        assert "latency_p95_ms" in data


@pytest.mark.asyncio
async def test_telemetry_populated_metrics():
    """Verify aggregator aggregates traces, retries, and guard stats accurately."""
    aggregator = get_telemetry_aggregator()

    # Record 1 SUCCESS trace
    aggregator.record_trace({
        "trace_id": "tr-1",
        "status": "SUCCESS",
        "total_latency_ms": 120.0,
        "retry_count": 0,
        "spans": [
            {
                "name": "generation",
                "status": "SUCCESS",
                "guard_results": [
                    {"guard_name": "rag_citation", "passed": True, "mode": "ENFORCED"}
                ]
            }
        ]
    })

    # Record 1 FALLBACK trace with citation mismatch
    aggregator.record_trace({
        "trace_id": "tr-2",
        "status": "FALLBACK",
        "failure_category": FailureCategory.CITATION_MISMATCH.value,
        "total_latency_ms": 250.0,
        "retry_count": 1,
        "retry_improved": True,
        "spans": [
            {
                "name": "generation",
                "status": "FALLBACK",
                "guard_results": [
                    {"guard_name": "rag_citation", "passed": False, "mode": "ENFORCED"}
                ]
            }
        ]
    })

    # Record 1 FAILED trace with temporal filter
    aggregator.record_trace({
        "trace_id": "tr-3",
        "status": "FAILED",
        "failure_category": FailureCategory.MISSING_TEMPORAL_FILTER.value,
        "total_latency_ms": 400.0,
        "retry_count": 0,
        "spans": [
            {
                "name": "sql_execution",
                "status": "ERROR",
                "failure_category": FailureCategory.MISSING_TEMPORAL_FILTER.value,
                "guard_results": [
                    {"guard_name": "sql_temporal", "passed": False, "mode": "SHADOW"}
                ]
            }
        ]
    })

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Overview
        res_overview = await client.get("/api/ui/telemetry/overview")
        assert res_overview.status_code == 200
        overview = res_overview.json()
        assert overview["total_requests"] == 3
        assert overview["sample_size"] == 3
        assert overview["status_breakdown"] == {"SUCCESS": 1, "FALLBACK": 1, "FAILED": 1}
        assert overview["success_rate_percent"] == 33.3
        assert overview["fallback_rate_percent"] == 33.3
        assert overview["retries_total"] == 1
        assert overview["retries_improved"] == 1
        assert overview["retry_recovery_rate_percent"] == 100.0

        # 2. Failures
        res_failures = await client.get("/api/ui/telemetry/failures")
        assert res_failures.status_code == 200
        failures = res_failures.json()
        assert failures["total_failures"] == 2
        assert failures["by_category"][FailureCategory.CITATION_MISMATCH.value] == 1
        assert failures["by_category"][FailureCategory.MISSING_TEMPORAL_FILTER.value] == 1
        assert failures["by_stage"]["sql_execution"] == 1

        # 3. Guards
        res_guards = await client.get("/api/ui/telemetry/guards")
        assert res_guards.status_code == 200
        guards = res_guards.json()
        assert "rag_citation" in guards
        assert guards["rag_citation"]["checks"] == 2
        assert guards["rag_citation"]["enforced_blocks"] == 1
        assert guards["rag_citation"]["shadow_blocks"] == 0
        assert guards["rag_citation"]["block_rate_percent"] == 50.0

        assert "sql_temporal" in guards
        assert guards["sql_temporal"]["checks"] == 1
        assert guards["sql_temporal"]["shadow_blocks"] == 1
        assert guards["sql_temporal"]["enforced_blocks"] == 0

        # 4. Traces list & filtering
        res_traces = await client.get("/api/ui/telemetry/traces?limit=10")
        assert res_traces.status_code == 200
        traces_payload = res_traces.json()
        assert traces_payload["count"] == 3
        assert len(traces_payload["traces"]) == 3

        # Filter by status=FALLBACK
        res_fallback = await client.get("/api/ui/telemetry/traces?status=FALLBACK")
        assert res_fallback.status_code == 200
        fallback_traces = res_fallback.json()
        assert fallback_traces["count"] == 1
        assert fallback_traces["traces"][0]["trace_id"] == "tr-2"


@pytest.mark.asyncio
async def test_telemetry_latency_under_5ms_guardrail_4():
    """Guardrail #4: Verify endpoints query in-memory aggregator in < 5ms under load."""
    aggregator = get_telemetry_aggregator()
    for i in range(100):
        aggregator.record_trace({
            "trace_id": f"trace-{i}",
            "status": "SUCCESS" if i % 2 == 0 else "FALLBACK",
            "total_latency_ms": 50.0 + i,
            "spans": [],
        })

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        endpoints = [
            "/api/ui/telemetry/overview",
            "/api/ui/telemetry/failures",
            "/api/ui/telemetry/guards",
            "/api/ui/telemetry/traces?limit=20",
        ]

        for ep in endpoints:
            latencies_ms = []
            for _ in range(20):
                t0 = time.perf_counter()
                res = await client.get(ep)
                lat_ms = (time.perf_counter() - t0) * 1000.0
                assert res.status_code == 200
                latencies_ms.append(lat_ms)

            mean_latency = sum(latencies_ms) / len(latencies_ms)
            p95_latency = sorted(latencies_ms)[int(len(latencies_ms) * 0.95)]
            # Must remain well below 5.0ms (typically < 1.0ms)
            assert mean_latency < 5.0, f"{ep} mean latency {mean_latency:.2f}ms exceeded 5.0ms ceiling"
            assert p95_latency < 10.0, f"{ep} p95 latency {p95_latency:.2f}ms exceeded tolerance"

"""Comprehensive Integration Audit Test Suite for Phases 12 through 14.

Validates:
1. Fast Path & Phase 11 Harmony (0 LLM calls for lists, bypassed on empty).
2. Task-Aware Routing & Circuit Breaker Fallback (skips tripped provider without latency, logs fell_back).
3. Rollout CLI Backup & Toggle Safety (backups created, flags toggled safely).
4. A/B Comparator Math & Edge Cases (-80% token delta, zero-division resilience).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch
import pytest
import yaml

from scripts.analytics.compare_telemetry import (
    compare_telemetry_files,
    compute_extended_metrics,
    format_delta,
)
from scripts.analytics.generate_roi_report import generate_roi_markdown
from scripts.analytics.telemetry_parser import parse_telemetry_file
from scripts.rollout.manage_flags import (
    TARGET_FLAGS,
    cmd_disable_all,
    cmd_enable_all,
    load_flags,
)
from src.core.provider_client import (
    DEFAULT_TASK_ROUTING,
    ProviderOption,
    ProviderRouter,
    TaskRoute,
)
from src.stages.s12_s13_s14_retrieval import Generator
from src.utils.circuit_breaker import get_shared_circuit_breaker
from src.utils.query_classifier import classify_query_intent, LIST_QUERY
from src.models.schemas import Chunk, ChunkType, RetrievedChunk


@pytest.mark.asyncio
async def test_1_fast_path_and_phase_11_harmony():
    """Test 1: Fast Path bypasses synthesis LLM for list queries and yields to Phase 11 on empty results."""
    mock_router = AsyncMock(spec=ProviderRouter)
    mock_router.chat = AsyncMock(return_value="LLM response")
    mock_router.usage = AsyncMock(model_copy=lambda: {})
    mock_router.last_used = "groq"

    generator = Generator(router=mock_router)

    # Case A: Successful SQL table chunk with list query intent
    list_query = "Show me the last 10 orders"
    assert classify_query_intent(list_query) == LIST_QUERY

    sql_table = "| order_id | customer_id | amount |\n|---|---|---|\n| 101 | 1 | 150.00 |\n| 102 | 2 | 200.00 |"
    table_chunk = RetrievedChunk(
        chunk=Chunk(
            document_id="doc_1",
            chunk_id="sql_result_1",
            chunk_type=ChunkType.SQL_RESULT,
            content=f"SQL Direct Result Table:\n{sql_table}",
        ),
        score=1.0,
    )

    with patch("src.stages.s12_s13_s14_retrieval.is_feature_enabled", return_value=True):
        res = await generator.generate(list_query, [table_chunk])

    # Assert: Fast Path returned table directly with 0 LLM synthesis calls
    assert mock_router.chat.call_count == 0
    assert "Here are the records matching your request:" in res.answer
    assert sql_table in res.answer
    assert res.model_used == "fast_path/list"

    # Case B: Empty result (0 matching records) from Phase 11
    empty_content = "SQL Direct Result Table:\n0 matching records found."
    empty_chunk = RetrievedChunk(
        chunk=Chunk(
            document_id="doc_1",
            chunk_id="sql_result_2",
            chunk_type=ChunkType.SQL_RESULT,
            content=empty_content,
        ),
        score=1.0,
    )

    with patch("src.stages.s12_s13_s14_retrieval.is_feature_enabled", return_value=True):
        empty_res = await generator.generate(list_query, [empty_chunk])

    # Assert: Fast Path was bypassed, respecting Phase 11 empty result handling
    assert empty_res.model_used != "fast_path/list"
    assert mock_router.chat.call_count == 1


@pytest.mark.asyncio
async def test_2_task_aware_routing_and_circuit_breaker_fallback():
    """Test 2: Task-aware routing prioritizes Gemini for reasoning, falls back to Groq when Gemini is circuit-broken."""
    cb = get_shared_circuit_breaker()
    cb.reset_all()

    # Configure reasoning to prefer Gemini -> Groq
    routes = {
        "reasoning": TaskRoute(
            options=[
                ProviderOption("gemini", "gemini-2.0-flash", 1),
                ProviderOption("groq", "llama-3.3-70b-versatile", 2),
            ],
        ),
    }

    mock_gemini = AsyncMock()
    mock_gemini.is_available = True
    mock_gemini.chat = AsyncMock(return_value="gemini sql")

    mock_groq = AsyncMock()
    mock_groq.is_available = True
    mock_groq.chat = AsyncMock(return_value="SELECT * FROM sales")

    providers = {"gemini": mock_gemini, "groq": mock_groq}
    router = ProviderRouter(routes=routes)
    router._providers = providers

    # Trip Gemini circuit breaker with 3 consecutive 429 errors
    cb.record_failure("gemini", Exception("429 Rate limit reached"))
    cb.record_failure("gemini", Exception("429 Rate limit reached"))
    cb.record_failure("gemini", Exception("429 Rate limit reached"))
    assert cb.is_open("gemini") is True

    telemetry_logs = []

    def mock_log_telemetry(*args, **kwargs):
        telemetry_logs.append((args, kwargs))

    # Patch client calls and feature flags
    with patch("src.core.provider_client.log_telemetry", side_effect=mock_log_telemetry), \
         patch("src.utils.feature_flags.is_feature_enabled", return_value=True):

        res = await router.chat(
            task="reasoning",
            messages=[{"role": "user", "content": "Fetch total sales"}],
        )

        assert res == "SELECT * FROM sales"

        # Assert: Gemini was skipped locally (0 network calls to Gemini); routed to Groq
        assert mock_gemini.chat.call_count == 0
        assert mock_groq.chat.call_count == 1

        # Assert: Telemetry logs fell_back=True, task_hint='reasoning', preferred='gemini'
        assert len(telemetry_logs) >= 1
        last_kwargs = telemetry_logs[-1][1]
        assert last_kwargs["extra"]["task_hint"] == "reasoning"
        assert last_kwargs["extra"]["preferred_provider"] == "gemini"
        assert last_kwargs["extra"]["actual_provider_used"] == "groq"
        assert last_kwargs["extra"]["fell_back"] is True


def test_3_rollout_cli_backup_and_toggle_safety(tmp_path: Path):
    """Test 3: Flag manager creates timestamped backups and safely toggles all flags."""
    test_config = tmp_path / "feature_flags.yaml"
    initial_data = {"features": {flag: False for flag in TARGET_FLAGS}}
    with open(test_config, "w", encoding="utf-8") as f:
        yaml.dump(initial_data, f)

    backup_dir = tmp_path / "backups"

    # 1. Enable all flags
    assert cmd_enable_all(test_config) == 0

    # Assert: Backup was created
    backups = list(backup_dir.glob("feature_flags.yaml.bak.*"))
    assert len(backups) >= 1

    # Assert: All flags are now True
    flags = load_flags(test_config)["features"]
    assert all(flags[f] is True for f in TARGET_FLAGS)

    # 2. Disable all flags (emergency rollback)
    assert cmd_disable_all(test_config) == 0

    # Assert: All flags reverted to False
    flags_after = load_flags(test_config)["features"]
    assert all(flags_after[f] is False for f in TARGET_FLAGS)


def test_4_ab_comparator_math_and_edge_cases(tmp_path: Path):
    """Test 4: Comparator calculates exact -80% delta and handles 0 repair events gracefully."""
    base_file = tmp_path / "baseline.jsonl"
    opt_file = tmp_path / "optimized.jsonl"

    # Baseline: 100 queries, 10,000 avg tokens (1,000,000 total), 20% failure rate
    base_events = []
    for i in range(100):
        qid = f"base_q_{i}"
        is_fail = (i < 20)
        base_events.append({
            "query_id": qid,
            "stage": "sql_generation",
            "input_tokens": 8000,
            "output_tokens": 2000,
            "success": not is_fail,
            "failure_type": "sql_execution_error" if is_fail else None,
        })
        base_events.append({
            "query_id": qid,
            "stage": "final_response",
            "latency_ms": 5000.0,
            "success": not is_fail,
        })

    # Optimized: 100 queries, 2,000 avg tokens (200,000 total), 5% failure rate, 0 repair events
    opt_events = []
    for i in range(100):
        qid = f"opt_q_{i}"
        is_fail = (i < 5)
        opt_events.append({
            "query_id": qid,
            "stage": "sql_generation",
            "input_tokens": 1600,
            "output_tokens": 400,
            "success": not is_fail,
            "failure_type": "sql_execution_error" if is_fail else None,
        })
        opt_events.append({
            "query_id": qid,
            "stage": "final_response",
            "latency_ms": 1500.0,
            "success": not is_fail,
        })

    with open(base_file, "w", encoding="utf-8") as f:
        for e in base_events:
            f.write(json.dumps(e) + "\n")

    with open(opt_file, "w", encoding="utf-8") as f:
        for e in opt_events:
            f.write(json.dumps(e) + "\n")

    b_parsed = parse_telemetry_file(base_file)
    o_parsed = parse_telemetry_file(opt_file)

    b_metrics = compute_extended_metrics(b_parsed)
    o_metrics = compute_extended_metrics(o_parsed)

    # 1. Assert: Token delta calculates to exactly -80.0%
    token_delta = format_delta(b_metrics["avg_tokens"], o_metrics["avg_tokens"], False)
    assert token_delta == "-80.0%"

    # 2. Assert: 0 repair events handles division gracefully (returns 0.0%)
    assert o_metrics["repair_attempts"] == 0
    assert o_metrics["repair_success_rate"] == 0.0

    # 3. Assert: Report generation executes cleanly
    report_file = tmp_path / "FINAL_REPORT.md"
    report_content = generate_roi_markdown(base_file, opt_file, report_file)
    assert report_file.exists()
    assert "-80.0%" in report_content

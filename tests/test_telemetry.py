"""Unit tests for Phase 1 Minimal Telemetry."""

import asyncio
import json
import pytest

from src.utils.error_classification import classify_error
from src.utils.feature_flags import is_feature_enabled
from src.utils.telemetry import (
    ALLOWED_STAGES,
    capture_telemetry,
    get_or_create_query_id,
    log_telemetry,
    timed_stage,
)


def test_query_id_generation():
    # 1. Standalone generation
    qid1 = get_or_create_query_id()
    assert qid1.startswith("gm-q-")

    # 2. Context dict generation & reuse
    ctx = {}
    qid2 = get_or_create_query_id(ctx)
    assert ctx["query_id"] == qid2
    qid3 = get_or_create_query_id(ctx)
    assert qid3 == qid2


def test_error_classification():
    assert classify_error("HTTP 429 Too Many Requests: Rate limit exceeded") == "rate_limit_error"
    assert classify_error("Connection timed out after 25s") == "timeout_error"
    assert classify_error("Permission denied: access denied for user") == "permission_error"
    assert classify_error("Column validation failed: Column 'bad_col' does not exist") == "sql_validation_error"
    assert classify_error("OperationalError: no such table: missing_tbl") == "db_execution_error"
    assert classify_error("SyntaxError: unexpected token at line 1") == "sql_generation_error"
    assert classify_error("Schema RAG search failed: embedding error") == "schema_retrieval_error"
    assert classify_error("Random unknown error occurred") == "unknown_error"


def test_log_telemetry_safe_execution(caplog):
    import logging
    with caplog.at_level(logging.INFO, logger="telemetry"):
        log_telemetry(
            query_id="test-q-123",
            stage="sql_generation",
            input_tokens=1500,
            output_tokens=120,
            latency_ms=350.5,
            success=True,
            provider="groq",
            model="qwen/qwen3.6-27b",
        )

    assert len(caplog.records) >= 1
    log_line = caplog.records[-1].message
    data = json.loads(log_line)
    assert data["query_id"] == "test-q-123"
    assert data["stage"] == "sql_generation"
    assert data["input_tokens"] == 1500
    assert data["output_tokens"] == 120
    assert data["latency_ms"] == 350.5
    assert data["success"] is True
    assert data["provider"] == "groq"
    assert data["model"] == "qwen/qwen3.6-27b"
    assert isinstance(data["feature_flags"], dict)
    assert data["feature_flags"]["delta_repair_enabled"] is False


def test_timed_stage_context_manager():
    with timed_stage("schema_retrieval", query_id="test-timed-1") as info:
        assert info["stage"] == "schema_retrieval"
        assert info["query_id"] == "test-timed-1"
        info["input_tokens"] = 500

    assert info["latency_ms"] >= 0
    assert info["success"] is True


def test_timed_stage_exception_handling():
    with pytest.raises(ValueError, match="test error"):
        with timed_stage("sql_validation", query_id="test-err-1") as info:
            raise ValueError("test error")

    assert info["success"] is False
    assert info["failure_type"] == "unknown_error"


@pytest.mark.asyncio
async def test_capture_telemetry_decorator():
    @capture_telemetry("intent_extraction")
    async def sample_stage(x: int, query_id: str | None = None) -> int:
        await asyncio.sleep(0.01)
        return x * 2

    res = await sample_stage(21, query_id="dec-q-1")
    assert res == 42


def test_feature_flags_all_default_false():
    flags = [
        "delta_repair_enabled",
        "token_budget_enabled",
        "schema_compaction_enabled",
        "sql_safety_enabled",
        "zero_row_handling_enabled",
        "fast_path_enabled",
    ]
    for flag in flags:
        assert is_feature_enabled(flag) is False

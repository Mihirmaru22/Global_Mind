"""Standalone script to verify Phase 1 Minimal Telemetry implementation."""

import asyncio
from src.utils.error_classification import classify_error
from src.utils.feature_flags import is_feature_enabled
from src.utils.telemetry import (
    capture_telemetry,
    get_or_create_query_id,
    log_telemetry,
    timed_stage,
)


def verify() -> None:
    print("=== Verifying Phase 1 Minimal Telemetry ===")

    # 1. query_id generation
    qid = get_or_create_query_id()
    assert qid.startswith("gm-q-")
    print(f"✅ query_id generation: {qid}")

    # 2. log_telemetry safe execution
    log_telemetry(
        query_id=qid,
        stage="sql_generation",
        input_tokens=1200,
        output_tokens=150,
        latency_ms=240.1,
        success=True,
        provider="groq",
        model="qwen/qwen3.6-27b",
    )
    print("✅ log_telemetry executed without errors")

    # 3. Timing helper
    with timed_stage("schema_retrieval", query_id=qid) as info:
        info["input_tokens"] = 300
    assert info["latency_ms"] >= 0
    print(f"✅ timed_stage measured latency: {info['latency_ms']} ms")

    # 4. Error classification
    err_type = classify_error("HTTP 429: Rate limit exceeded")
    assert err_type == "rate_limit_error"
    print(f"✅ classify_error mapped to: {err_type}")

    # 5. Feature flags
    assert is_feature_enabled("delta_repair_enabled") is False
    print("✅ Feature flags default to False")

    # 6. Async decorator
    @capture_telemetry("sql_execution")
    async def sample_exec(query_id=None):
        await asyncio.sleep(0.01)
        return "OK"

    res = asyncio.run(sample_exec(query_id=qid))
    assert res == "OK"
    print("✅ @capture_telemetry async decorator verified")

    print("\n🎉 Phase 1 Minimal Telemetry Verification Passed Successfully!")


if __name__ == "__main__":
    verify()

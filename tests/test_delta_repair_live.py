"""Live LLM Integration Test for Delta Repair against Golden Test Cases."""

from __future__ import annotations

import json
import os
from pathlib import Path
import pytest

from src.core.provider_client import ProviderRouter
from src.stages.sql_repair import attempt_delta_repair
from src.utils.golden_models import GoldenCase

PROJECT_ROOT = Path(__file__).resolve().parent.parent
GOLDEN_CASES_FILE = PROJECT_ROOT / "tests" / "golden" / "sql_repair" / "cases.json"

HAS_API_KEY = bool(
    os.getenv("OPENROUTER_API_KEY")
    or os.getenv("GEMINI_API_KEY")
    or os.getenv("ANTHROPIC_API_KEY")
    or os.getenv("DEEPSEEK_API_KEY")
)


@pytest.mark.skipif(not HAS_API_KEY, reason="Live LLM test requires active LLM API key environment variables")
@pytest.mark.asyncio
async def test_delta_repair_live_on_golden_cases():
    """Evaluate live LLM Delta Repair against the first 3 Golden Test Cases."""
    assert GOLDEN_CASES_FILE.exists()

    with open(GOLDEN_CASES_FILE, "r", encoding="utf-8") as f:
        cases_data = json.load(f)

    test_cases = [GoldenCase(**c) for c in cases_data[:3]]
    router = ProviderRouter()

    for case in test_cases:
        repaired_sql = await attempt_delta_repair(
            router=router,
            failed_sql=case.failed_sql,
            error_message=case.error_message,
            error_type=case.error_type,
            schema_context=case.schema_context,
            user_intent=case.user_question,
            attempt_number=1,
            query_id=f"live_test_{case.case_id}",
        )

        assert repaired_sql is not None, f"Live Delta Repair returned None for case {case.case_id}"
        assert len(repaired_sql.strip()) > 0

        # Assert repaired SQL does not contain forbidden substrings
        for forbidden in case.must_not_contain:
            assert forbidden.lower() not in repaired_sql.lower(), (
                f"Repaired SQL for {case.case_id} contained forbidden pattern '{forbidden}': {repaired_sql}"
            )

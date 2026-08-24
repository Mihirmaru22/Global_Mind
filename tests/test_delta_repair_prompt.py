"""Unit and Golden Case dry-run tests for Delta Repair Prompt Assembly."""

import json
from pathlib import Path
import pytest

from src.prompts.delta_repair import (
    DELTA_REPAIR_SYSTEM_PROMPT,
    MAX_TOTAL_REPAIR_TOKENS,
    build_delta_repair_payload,
    count_tokens,
    format_compact_schema,
)
from src.utils.golden_models import GoldenCase

PROJECT_ROOT = Path(__file__).resolve().parent.parent
GOLDEN_CASES_FILE = PROJECT_ROOT / "tests" / "golden" / "sql_repair" / "cases.json"


def test_system_prompt_token_budget():
    """Verify that the Delta Repair system prompt is ultra-compact (< 100 tokens)."""
    tokens = count_tokens(DELTA_REPAIR_SYSTEM_PROMPT)
    assert tokens < 100, f"System prompt must be < 100 tokens, got {tokens}"
    assert "Rules:" in DELTA_REPAIR_SYSTEM_PROMPT
    assert "SELECT *" in DELTA_REPAIR_SYSTEM_PROMPT
    assert "CROSS JOIN" in DELTA_REPAIR_SYSTEM_PROMPT


def test_format_compact_schema():
    """Verify that schema formatting is compact and token efficient."""
    schema = {
        "orders": ["id", "order_number", "total_amount"],
        "customers": ["id", "name", "email"],
    }
    formatted = format_compact_schema(schema)
    assert "- Table 'orders': id, order_number, total_amount" in formatted
    assert "- Table 'customers': id, name, email" in formatted
    assert count_tokens(formatted) < 40


def test_delta_repair_payload_idempotency():
    """Verify that assembling the payload twice yields the exact same structure and token count."""
    failed_sql = "SELECT id, rev FROM sales"
    error = 'column "rev" does not exist'
    schema = {"sales": ["id", "revenue"]}

    payload1 = build_delta_repair_payload(failed_sql, error, "column_not_found", schema)
    payload2 = build_delta_repair_payload(failed_sql, error, "column_not_found", schema)

    assert payload1 == payload2
    assert count_tokens(payload1[0]["content"]) + count_tokens(payload1[1]["content"]) == \
           count_tokens(payload2[0]["content"]) + count_tokens(payload2[1]["content"])


def test_budget_enforcement_with_oversized_schema():
    """Verify that a pathologically large schema context is gracefully truncated to stay under 500 tokens."""
    giant_schema = {
        f"table_{i}": [f"column_{j}_{i}" for j in range(25)]
        for i in range(40)
    }
    failed_sql = "SELECT * FROM table_0 JOIN table_1 ON table_0.id = table_1.id"
    error = "OperationalError: query failed"

    payload = build_delta_repair_payload(failed_sql, error, "db_error", giant_schema)
    total_tokens = count_tokens(payload[0]["content"]) + count_tokens(payload[1]["content"])

    assert total_tokens <= MAX_TOTAL_REPAIR_TOKENS, f"Oversized schema exceeded budget: {total_tokens} tokens"
    assert len(payload) == 2


def test_all_19_golden_cases_dry_run():
    """Dry-run prompt assembly across all 19 Golden Test Cases to verify structure and token limits."""
    assert GOLDEN_CASES_FILE.exists(), f"Cases file not found at {GOLDEN_CASES_FILE}"

    with open(GOLDEN_CASES_FILE, "r", encoding="utf-8") as f:
        raw_cases = json.load(f)

    cases = [GoldenCase(**c) for c in raw_cases]
    assert len(cases) == 19, f"Expected 19 golden cases, found {len(cases)}"

    print("\n" + "=" * 75)
    print("      DELTA REPAIR PROMPT PAYLOAD DRY-RUN ACROSS GOLDEN SET")
    print("=" * 75)
    print(f"{'Case ID':<10} | {'Error Type':<20} | {'Tokens':<8} | {'Budget (<500)':<14} | Status")
    print("-" * 75)

    token_counts: list[int] = []

    for case in cases:
        payload = build_delta_repair_payload(
            failed_sql=case.failed_sql,
            error_message=case.error_message,
            error_type=case.error_type,
            schema_context=case.schema_context,
            user_intent=case.user_question,
        )

        # 1. Structure Assertions
        assert isinstance(payload, list)
        assert len(payload) == 2
        assert payload[0]["role"] == "system"
        assert payload[1]["role"] == "user"

        sys_content = payload[0]["content"]
        user_content = payload[1]["content"]

        # 2. Content Assertions
        assert case.failed_sql in user_content or case.failed_sql.strip() in user_content
        assert case.error_type in user_content
        assert "Provide only the corrected SQL statement." in user_content

        # 3. Token Budget Assertions
        sys_tokens = count_tokens(sys_content)
        user_tokens = count_tokens(user_content)
        total_tokens = sys_tokens + user_tokens
        token_counts.append(total_tokens)

        assert sys_tokens < 100, f"System prompt for {case.case_id} exceeded 100 tokens: {sys_tokens}"
        assert total_tokens < MAX_TOTAL_REPAIR_TOKENS, f"Case {case.case_id} exceeded budget: {total_tokens} tokens"

        print(f"{case.case_id:<10} | {case.error_type:<20} | {total_tokens:<8} | {'PASS':<14} | ✓ VALID")

    avg_tokens = sum(token_counts) / len(token_counts)
    max_tokens = max(token_counts)
    min_tokens = min(token_counts)

    print("=" * 75)
    print(f"Summary: 19/19 Assembled Successfully | Min: {min_tokens} | Avg: {avg_tokens:.1f} | Max: {max_tokens} tokens")
    print("=" * 75 + "\n")

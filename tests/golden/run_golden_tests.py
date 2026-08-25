"""Golden SQL Repair Evaluation Harness.

Evaluates any candidate repair function against the curated Golden Test Set
without making live LLM calls, mathematically verifying repair correctness.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Callable

import sqlglot

from src.utils.golden_models import CaseEvaluationResult, GoldenCase, GoldenEvaluationSummary

logger = logging.getLogger("golden_harness")

GOLDEN_DIR = Path(__file__).resolve().parent / "sql_repair"
DEFAULT_CASES_FILE = GOLDEN_DIR / "cases.json"

RepairFunction = Callable[[str, str, dict[str, list[str]]], str]


def check_sql_syntax(sql: str) -> tuple[bool, str | None]:
    """Verify that the repaired SQL is syntactically parseable."""
    if not sql or not sql.strip():
        return False, "Repaired SQL is empty"
    try:
        sqlglot.parse_one(sql)
        return True, None
    except Exception as exc:
        return False, f"SQL syntax error: {exc}"


def evaluate_single_case(
    case: GoldenCase,
    repair_func: RepairFunction,
) -> CaseEvaluationResult:
    """Evaluate a repair function against a single GoldenCase."""
    try:
        repaired_sql = repair_func(case.failed_sql, case.error_message, case.schema_context)
    except Exception as exc:
        return CaseEvaluationResult(
            case_id=case.case_id,
            passed=False,
            repaired_sql="",
            syntax_valid=False,
            error_detail=f"Repair function raised exception: {exc}",
        )

    if not repaired_sql or not repaired_sql.strip():
        return CaseEvaluationResult(
            case_id=case.case_id,
            passed=False,
            repaired_sql="",
            syntax_valid=False,
            error_detail="Repair function returned empty string",
        )

    syntax_valid, syntax_err = check_sql_syntax(repaired_sql)

    import re

    # Normalize whitespace for basic substring checks
    normalized_repaired = " ".join(repaired_sql.split()).lower()

    missing_expected: list[str] = []
    for expected in case.expected_sql_contains:
        words = expected.strip().split()
        if not words:
            continue
        # Use word boundary search if alphanumeric tokens
        pattern = r"\b" + r"\s+".join(re.escape(w) for w in words) + r"\b" if all(w.isalnum() or "_" in w for w in words) else re.escape(" ".join(words))
        if not re.search(pattern, repaired_sql, re.IGNORECASE) and " ".join(words).lower() not in normalized_repaired:
            missing_expected.append(expected)

    found_forbidden: list[str] = []
    for forbidden in case.must_not_contain:
        words = forbidden.strip().split()
        if not words:
            continue
        pattern = r"\b" + r"\s+".join(re.escape(w) for w in words) + r"\b" if all(w.isalnum() or "_" in w for w in words) else re.escape(" ".join(words))
        if re.search(pattern, repaired_sql, re.IGNORECASE):
            found_forbidden.append(forbidden)

    passed = syntax_valid and len(missing_expected) == 0 and len(found_forbidden) == 0

    return CaseEvaluationResult(
        case_id=case.case_id,
        passed=passed,
        repaired_sql=repaired_sql,
        syntax_valid=syntax_valid,
        missing_expected=missing_expected,
        found_forbidden=found_forbidden,
        error_detail=syntax_err if not syntax_valid else None,
    )


def run_golden_evaluation(
    repair_func: RepairFunction,
    cases_file: Path | None = None,
) -> GoldenEvaluationSummary:
    """Run full evaluation harness against all golden test cases."""
    target_path = cases_file or DEFAULT_CASES_FILE
    if not target_path.exists():
        raise FileNotFoundError(f"Golden cases file not found at: {target_path}")

    with open(target_path, "r", encoding="utf-8") as f:
        raw_cases = json.load(f)

    cases = [GoldenCase(**c) for c in raw_cases]
    results: list[CaseEvaluationResult] = []
    passed_count = 0

    for case in cases:
        result = evaluate_single_case(case, repair_func)
        if result.passed:
            passed_count += 1
        results.append(result)

    total = len(cases)
    failed = total - passed_count
    pass_rate = round((passed_count / total * 100.0) if total > 0 else 0.0, 2)

    return GoldenEvaluationSummary(
        total_cases=total,
        passed_cases=passed_count,
        failed_cases=failed,
        pass_rate=pass_rate,
        results=results,
    )


# ---------------------------------------------------------------------------
# Mock Repair Functions for Harness Self-Verification
# ---------------------------------------------------------------------------

def mock_perfect_repair(sql: str, error: str, schema: dict[str, list[str]]) -> str:
    """Mock repair function returning the pre-calculated ideal SQL for synthetic cases."""
    if not hasattr(mock_perfect_repair, "_lookup"):
        if DEFAULT_CASES_FILE.exists():
            cases = [GoldenCase(**c) for c in json.loads(DEFAULT_CASES_FILE.read_text(encoding="utf-8"))]
            mock_perfect_repair._lookup = {c.failed_sql.strip(): (c.ideal_sql or c.failed_sql) for c in cases}
        else:
            mock_perfect_repair._lookup = {}
    return mock_perfect_repair._lookup.get(sql.strip(), sql)


def dummy_noop_repair(sql: str, error: str, schema: dict[str, list[str]]) -> str:
    """Dummy repair function that returns original broken SQL (for testing failure detection)."""
    return sql


def print_evaluation_report(summary: GoldenEvaluationSummary) -> None:
    """Print formatted evaluation report to stdout."""
    print("=" * 70)
    print("           GOLDEN SQL REPAIR EVALUATION REPORT")
    print("=" * 70)
    print(f"Total Cases Evaluated: {summary.total_cases}")
    print(f"Passed:                {summary.passed_cases} / {summary.total_cases} ({summary.pass_rate}%)")
    print(f"Failed:                {summary.failed_cases} / {summary.total_cases}")
    print("-" * 70)

    for res in summary.results:
        status_tag = "✓ PASS" if res.passed else "✗ FAIL"
        print(f"[{status_tag}] Case: {res.case_id}")
        if not res.passed:
            if not res.syntax_valid:
                print(f"       Syntax Error:     {res.error_detail}")
            if res.missing_expected:
                print(f"       Missing Expected: {res.missing_expected}")
            if res.found_forbidden:
                print(f"       Found Forbidden:  {res.found_forbidden}")
            if res.repaired_sql:
                print(f"       Output SQL:       {res.repaired_sql}")
    print("=" * 70)


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate a repair function against Golden SQL Test Cases.")
    parser.add_argument("--cases", type=str, default=str(DEFAULT_CASES_FILE), help="Path to cases.json")
    parser.add_argument("--mode", choices=["perfect", "noop"], default="perfect", help="Mock repair mode to test")
    args = parser.parse_args()

    repair_fn = mock_perfect_repair if args.mode == "perfect" else dummy_noop_repair
    summary = run_golden_evaluation(repair_fn, cases_file=Path(args.cases))
    print_evaluation_report(summary)

    if summary.failed_cases > 0 and args.mode == "perfect":
        exit(1)


if __name__ == "__main__":
    main()

"""V1 Golden Benchmark Runner.

Executes and asserts against the 52-case V1 evaluation benchmark suite.
Supports deterministic fixture replay (--use-cache) for sub-second CI runs without
burning API quotas, as well as live execution (--live) and fixture recording (--record-fixtures).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

import sqlglot
from sqlglot import exp

from src.models.trace import GuardResult, Span, Trace
from src.utils.error_classification import FailureCategory

GOLDEN_DIR = Path(__file__).resolve().parent
FIXTURES_DIR = GOLDEN_DIR / "fixtures"
BENCHMARK_FILE = GOLDEN_DIR / "v1_benchmark.json"


class BenchmarkEvaluator:
    """Evaluates golden test cases against Trace, SQL AST, and RAG grounding contracts."""

    def __init__(self, use_cache: bool = True, record: bool = False):
        self.use_cache = use_cache
        self.record = record
        FIXTURES_DIR.mkdir(parents=True, exist_ok=True)

    def _get_cache_path(self, case_id: str) -> Path:
        return FIXTURES_DIR / f"{case_id}.json"

    def rehydrate_trace(self, trace_dict: dict[str, Any]) -> Trace:
        """Fix 1: Full recursive rehydration of Trace, Span, and GuardResult objects."""
        t_data = dict(trace_dict)
        spans_data = t_data.pop("spans", [])
        root_data = t_data.pop("root_span", None)

        rehydrated_spans: list[Span] = []
        for s in spans_data:
            s_dict = dict(s)
            guards_data = s_dict.pop("guard_results", [])
            span = Span(**s_dict)
            span.guard_results = [GuardResult(**g) for g in guards_data]
            rehydrated_spans.append(span)

        trace = Trace(**t_data)
        trace.spans = rehydrated_spans
        if root_data:
            r_dict = dict(root_data)
            r_guards = r_dict.pop("guard_results", [])
            trace.root_span = Span(**r_dict)
            trace.root_span.guard_results = [GuardResult(**g) for g in r_guards]

        return trace

    async def execute_case(self, case: dict[str, Any]) -> tuple[dict[str, Any], Trace]:
        """Execute a benchmark case either via cached replay or live pipeline."""
        cache_file = self._get_cache_path(case["case_id"])

        if self.use_cache and cache_file.exists():
            payload = json.loads(cache_file.read_text(encoding="utf-8"))
            trace = self.rehydrate_trace(payload["trace"])
            return payload["result"], trace

        # Live Execution Path
        from src.pipeline.query import QueryPipeline
        pipeline = QueryPipeline()
        query_text = case["query"]
        mode = case.get("mode", "auto")

        # Execute live pipeline query with trace capture
        result, trace = await pipeline.query_with_trace(query=query_text, mode=mode)
        result_dict = result.model_dump() if hasattr(result, "model_dump") else dict(result)

        if self.record:
            cache_file.write_text(
                json.dumps({"result": result_dict, "trace": trace.to_dict()}, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

        return result_dict, trace

    def assert_trace(self, case: dict[str, Any], trace: Trace) -> list[str]:
        """Assert against the hierarchical Trace object."""
        errors: list[str] = []
        expected = case["expected_trace"]

        # 1. Trace Status
        if trace.status != expected["status"]:
            errors.append(f"Trace status mismatch: expected '{expected['status']}', got '{trace.status}'")

        # 2. Failure Category (Fix 2: checks semantic category including OUT_OF_SCOPE)
        exp_cat = expected.get("failure_category")
        if exp_cat is not None:
            actual_cat = trace.failure_category
            if actual_cat != exp_cat:
                errors.append(f"FailureCategory mismatch: expected '{exp_cat}', got '{actual_cat}'")

        # 3. Required Execution Branches
        if "required_branches" in expected:
            actual_branches = {s.branch for s in trace.spans if s.branch}
            for req_b in expected["required_branches"]:
                if req_b not in actual_branches:
                    errors.append(f"Missing required execution branch: '{req_b}' (found: {actual_branches})")

        # 4. Guard Evaluation Assertions
        if "expected_guards" in expected:
            executed_guards: dict[str, dict[str, Any]] = {}
            for s in trace.spans:
                for g in s.guard_results:
                    executed_guards[g.guard_name] = g.to_dict()

            for eg in expected["expected_guards"]:
                g_name = eg["guard_name"]
                if g_name not in executed_guards:
                    errors.append(f"Expected guard '{g_name}' was not evaluated in trace")
                else:
                    actual = executed_guards[g_name]
                    if actual["passed"] != eg["passed"]:
                        errors.append(
                            f"Guard '{g_name}' passed={actual['passed']}, expected passed={eg['passed']}"
                        )
                    if "mode" in eg and actual.get("mode") != eg["mode"]:
                        errors.append(
                            f"Guard '{g_name}' mode='{actual.get('mode')}', expected '{eg['mode']}'"
                        )

        return errors

    def assert_sql(self, case: dict[str, Any], sql: str) -> list[str]:
        """Deterministic AST validation using sqlglot (no fragile regex)."""
        errors: list[str] = []
        exp_sql = case.get("expected_sql")
        if not exp_sql:
            return errors

        if not sql or not sql.strip():
            if exp_sql.get("required_tables"):
                return ["Expected SQL generation, but query returned empty SQL"]
            return []

        try:
            parsed = sqlglot.parse_one(sql, read="mysql")
        except Exception as e:
            if exp_sql.get("syntax_valid", True):
                return [f"SQL syntax error during AST parse: {e}"]
            return []

        # 1. Required Tables Resolution
        actual_tables = {t.name.lower() for t in parsed.find_all(exp.Table)}
        for req_table in exp_sql.get("required_tables", []):
            if req_table.lower() not in actual_tables:
                errors.append(f"SQL missing required table '{req_table}'. Found tables: {actual_tables}")

        # 2. Forbidden Tokens / Operations (DROP, DELETE, TRUNCATE, etc.)
        for forbidden in exp_sql.get("forbidden_tokens", []):
            if re.search(rf"\b{re.escape(forbidden)}\b", sql, re.IGNORECASE):
                errors.append(f"SQL contained forbidden operation/token: '{forbidden}'")

        # 3. Soft-delete filter presence
        if exp_sql.get("has_soft_delete_filter"):
            has_deleted_at = any(
                isinstance(node.this, exp.Column) and node.this.name.lower() == "deleted_at"
                for node in parsed.find_all(exp.Is)
            )
            if not has_deleted_at:
                errors.append("SQL missing mandatory 'deleted_at IS NULL/NOT NULL' filter in WHERE clause")

        # 4. Temporal filter presence
        if exp_sql.get("has_temporal_filter"):
            where = parsed.args.get("where")
            temporal_ops = (exp.Between, exp.GTE, exp.LTE, exp.GT, exp.LT, exp.EQ)
            has_temporal = where and any(isinstance(n, temporal_ops) for n in where.find_all(temporal_ops))
            if not has_temporal:
                # Also check date functions like DATEDIFF, DATE_SUB, CURDATE
                date_funcs = {"datediff", "date_sub", "date_add", "curdate", "now", "year", "month"}
                has_date_fn = where and any(
                    isinstance(n, exp.Anonymous) and n.this.lower() in date_funcs
                    for n in where.find_all(exp.Anonymous)
                )
                if not has_date_fn:
                    errors.append("SQL missing expected temporal boundary comparison in WHERE clause")

        return errors

    def assert_rag_and_response(
        self,
        case: dict[str, Any],
        result: dict[str, Any],
        trace: Trace,
    ) -> list[str]:
        """Fix 3: Deterministic RAG citation-to-chunk mapping and chunk keyword verification."""
        errors: list[str] = []
        answer = str(result.get("answer", ""))
        citations = result.get("citations", [])
        exp_rag = case.get("expected_rag", {})
        exp_resp = case.get("expected_response", {})

        # 1. Citation presence and structure
        if exp_rag.get("citation_required"):
            # Extract citations from structured field and inline text markers [Chunk-X] or [Doc-X]
            inline_citations = re.findall(r"\[(?:Chunk|Doc)-([a-zA-Z0-9_\-]+)\]", answer, re.IGNORECASE)
            total_citations = list(citations) + inline_citations

            if not total_citations:
                errors.append("Expected RAG citations, but none were returned in result or text")

            # Verify chunk-to-trace mapping: chunks cited must exist in retrieved chunks
            retrieved_chunk_ids: set[str] = set()
            for s in trace.spans:
                if s.branch == "rag_branch" or "rag" in s.name or "retrieval" in s.name:
                    chunk_ids = s.metadata.get("retrieved_chunk_ids", [])
                    retrieved_chunk_ids.update(str(cid) for cid in chunk_ids)

            # If chunks are present in result payload directly
            for c in result.get("chunks", []):
                cid = c.get("id") or c.get("chunk_id")
                if cid:
                    retrieved_chunk_ids.add(str(cid))

            if retrieved_chunk_ids and inline_citations:
                unmapped = [c for c in inline_citations if c not in retrieved_chunk_ids]
                if unmapped:
                    errors.append(f"Cited chunks {unmapped} do not exist in retrieved chunk set {retrieved_chunk_ids}")

        # 2. Required Chunk Keywords (check retrieved chunks or answer context)
        required_keywords = exp_rag.get("required_chunk_keywords", [])
        if required_keywords:
            combined_context = answer.lower()
            for c in result.get("chunks", []):
                combined_context += " " + str(c.get("text", "")).lower()

            for kw in required_keywords:
                if kw.lower() not in combined_context:
                    errors.append(f"Required keyword '{kw}' missing from retrieved context and answer")

        # 3. Response text containment
        for req_text in exp_resp.get("contains_all", []):
            if req_text.lower() not in answer.lower():
                errors.append(f"Answer missing expected text snippet: '{req_text}'")

        for forbidden in exp_resp.get("must_not_contain", []):
            if forbidden.lower() in answer.lower():
                errors.append(f"Answer contained forbidden text snippet: '{forbidden}'")

        # 4. Abstention verification for Out-of-Scope cases
        if exp_resp.get("is_abstention"):
            abstain_phrases = ["could not", "out of scope", "unable to verify", "cannot verify", "not found"]
            if not any(k in answer.lower() for k in abstain_phrases):
                errors.append("Expected clean abstention response, but received operational answer")

        return errors

    async def evaluate_single_case(self, case: dict[str, Any]) -> dict[str, Any]:
        """Run a single test case and return structured evaluation outcome."""
        case_id = case["case_id"]
        category = case["category"]
        t0 = time.perf_counter()

        try:
            result, trace = await self.execute_case(case)
            latency_ms = (time.perf_counter() - t0) * 1000

            trace_errors = self.assert_trace(case, trace)
            sql_errors = self.assert_sql(case, result.get("sql", ""))
            rag_errors = self.assert_rag_and_response(case, result, trace)

            all_errors = trace_errors + sql_errors + rag_errors
            passed = len(all_errors) == 0

            return {
                "case_id": case_id,
                "category": category,
                "passed": passed,
                "latency_ms": round(latency_ms, 2),
                "errors": all_errors,
            }
        except Exception as exc:
            latency_ms = (time.perf_counter() - t0) * 1000
            return {
                "case_id": case_id,
                "category": category,
                "passed": False,
                "latency_ms": round(latency_ms, 2),
                "errors": [f"Exception during evaluation: {exc}"],
            }

    async def run_suite(self, category_filter: str | None = None) -> dict[str, Any]:
        """Run the full benchmark suite and return summary metrics."""
        cases = json.loads(BENCHMARK_FILE.read_text(encoding="utf-8"))
        if category_filter:
            cases = [c for c in cases if c.get("category") == category_filter]

        t0 = time.perf_counter()
        results = []
        for case in cases:
            res = await self.evaluate_single_case(case)
            results.append(res)

        total = len(results)
        passed = sum(1 for r in results if r["passed"])
        failed = total - passed
        pass_rate = round((passed / total * 100), 1) if total > 0 else 0.0
        total_time = round(time.perf_counter() - t0, 2)

        by_category: dict[str, dict[str, int]] = {}
        for r in results:
            cat = r["category"]
            by_category.setdefault(cat, {"total": 0, "passed": 0})
            by_category[cat]["total"] += 1
            if r["passed"]:
                by_category[cat]["passed"] += 1

        return {
            "total_cases": total,
            "passed_cases": passed,
            "failed_cases": failed,
            "pass_rate_percent": pass_rate,
            "total_time_seconds": total_time,
            "by_category": by_category,
            "results": results,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run V1 Golden Benchmark Suite")
    parser.add_argument("--use-cache", action="store_true", default=True, help="Replay from fixture cache")
    parser.add_argument("--live", action="store_true", help="Run live pipeline queries")
    parser.add_argument("--record-fixtures", action="store_true", help="Execute live and write fixture cache")
    parser.add_argument("--category", type=str, default=None, help="Filter by category")
    args = parser.parse_args()

    use_cache = not args.live
    evaluator = BenchmarkEvaluator(use_cache=use_cache, record=args.record_fixtures)

    print(f"🚀 Running V1 Golden Benchmark (cache={use_cache}, record={args.record_fixtures})...")
    summary = asyncio.run(evaluator.run_suite(category_filter=args.category))

    print(f"\n==================== V1 BENCHMARK SUMMARY ====================")
    print(f"Total Cases: {summary['total_cases']}")
    print(f"Passed:      {summary['passed_cases']}")
    print(f"Failed:      {summary['failed_cases']}")
    print(f"Pass Rate:   {summary['pass_rate_percent']}%")
    print(f"Total Time:  {summary['total_time_seconds']}s")
    print(f"\n--- Category Breakdown ---")
    for cat, stats in summary["by_category"].items():
        rate = round(stats["passed"] / stats["total"] * 100, 1) if stats["total"] > 0 else 0
        print(f"  {cat:<20}: {stats['passed']}/{stats['total']} ({rate}%)")

    if summary["failed_cases"] > 0:
        print(f"\n--- Failures ---")
        for r in summary["results"]:
            if not r["passed"]:
                print(f"  [{r['category']}] {r['case_id']}:")
                for err in r["errors"]:
                    print(f"    - {err}")
        sys.exit(1)
    else:
        print("\n✅ All benchmark cases passed successfully!")
        sys.exit(0)


if __name__ == "__main__":
    main()

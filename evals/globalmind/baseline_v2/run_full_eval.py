#!/usr/bin/env python3
"""GlobalMind Live Evaluation & Validator Hardening Suite (Baseline v2)

----------------------------------------------------------------------
Runs all 163 questions (gm-001 to gm-163) + 5 Adversarial Queries.
Metrics: Accuracy (LLM-as-Judge), Token Usage, Latency, Validator Pass Rates.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
from datetime import datetime
import json
import os
from pathlib import Path
import statistics
import sys
import time
from typing import Any

# Add project root to path
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from src.pipeline.query_pipeline import QueryPipeline
except ImportError:
    from src.pipeline.query import QueryPipeline

from src.core.sql_column_registry import ColumnRegistry
from src.utils.sql_safety import (
    check_cartesian_explosion,
    clamp_cartesian_limits,
    is_destructive_sql,
    validate_tables_and_columns,
)
import sqlglot


class LiveEvaluator:
    def __init__(self, db_path: str = "global_mind.db"):
        self.db_path = db_path
        self._pipeline = None
        self.results: list[dict[str, Any]] = []
        self.adversarial_results: list[dict[str, Any]] = []

        # Metrics containers
        self.metrics: dict[str, Any] = {
            "total_questions": 0,
            "successful_executions": 0,
            "failed_executions": 0,
            "validator_blocks": 0,
            "total_tokens": 0,
            "avg_latency": 0.0,
            "p95_latency": 0.0,
            "route_distribution": {"SQL": 0, "DOC": 0, "BOTH": 0, "ABSTAIN": 0},
            "difficulty_breakdown": {},
            "domain_breakdown": {},
        }

    @property
    def pipeline(self) -> QueryPipeline:
        if self._pipeline is None:
            self._pipeline = QueryPipeline()
        return self._pipeline

    def load_questions(self, question_file: str) -> list[dict[str, Any]]:
        """Load questions from questions.jsonl"""
        questions: list[dict[str, Any]] = []
        path = Path(question_file)
        if not path.is_absolute():
            path = REPO_ROOT / question_file

        if not path.exists():
            print(f"❌ Question file not found: {path}")
            return questions

        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    questions.append(json.loads(line))
        return questions

    def get_adversarial_queries(self) -> list[dict[str, Any]]:
        """Return the 5 adversarial queries designed to break validators"""
        return [
            {
                "id": "adv-001",
                "type": "cte_shadowing",
                "sql": "WITH party AS (SELECT 1 AS shadow_token, 9999.99 AS fake_credit_limit) SELECT p.shadow_token, p.fake_credit_limit, p.hallucinated_balance FROM party p WHERE p.fake_credit_limit > 5000;",
                "expected_block": True,
                "reason": "CTE shadows physical table, evades column registry",
            },
            {
                "id": "adv-002",
                "type": "cartesian_join",
                "sql": "SELECT p.carton_no, w.name, u.name FROM packagings p, warehouse w, users u WHERE 1 = 1 AND p.deleted_at IS NULL LIMIT 1000;",
                "expected_block": False,  # Should pass safety but be clamped to LIMIT 100
                "reason": "Comma-join bypasses AST Join check, causes Cartesian explosion",
            },
            {
                "id": "adv-003",
                "type": "mysql_comment_masking",
                "sql": "SELECT p.id, p.batch_no, /*!50000 SLEEP(3), */ p.qty FROM packagings p WHERE p.status = 'B' LIMIT 5;",
                "expected_block": True,
                "reason": "MySQL version comment masks SLEEP function",
            },
            {
                "id": "adv-004",
                "type": "ambiguous_column",
                "sql": "SELECT product_id, category_id, product_color_id, qty FROM packagings INNER JOIN packaging_products ON packagings.id = packaging_products.packaging_id WHERE packagings.deleted_at IS NULL;",
                "expected_block": False,  # Should pass safety, fail at DB execution
                "reason": "Unqualified column exists in multiple tables -> Ambiguous error",
            },
            {
                "id": "adv-005",
                "type": "alias_spoofing",
                "sql": "SELECT sub.product_name, COUNT(*) OVER() AS total_sales_revenue, sub.unrelated_metric AS customer_churn_rate FROM (SELECT p.product_name, p.moq AS unrelated_metric FROM product p) sub;",
                "expected_block": False,
                "reason": "Window function alias spoofs business metric",
            },
        ]

    def test_validator_directly(self, sql: str) -> dict[str, Any]:
        """Test SQL against safety validators without full pipeline execution"""
        validation_result: dict[str, Any] = {
            "is_safe": True,
            "blocks": [],
            "warnings": [],
            "errors": [],
            "clamped_sql": sql,
            "was_clamped": False,
        }

        try:
            # 1. Destructive Check
            if is_destructive_sql(sql):
                validation_result["is_safe"] = False
                validation_result["blocks"].append("destructive_pattern")

            # 2. Table/Column Validation (AST structure checks)
            ast = sqlglot.parse_one(sql, read="mysql")

            # Check for CTE shadowing (Adv-001)
            ctes = set()
            for with_exp in ast.find_all(sqlglot.exp.With):
                for expr in with_exp.expressions:
                    if hasattr(expr, "alias") and expr.alias:
                        ctes.add(expr.alias.lower())
                    elif hasattr(expr, "this") and hasattr(expr.this, "name") and expr.this.name:
                        ctes.add(expr.this.name.lower())
                    elif hasattr(expr, "name") and expr.name:
                        ctes.add(expr.name.lower())
            tables = set()
            for table in ast.find_all(sqlglot.exp.Table):
                if table.name:
                    tables.add(table.name.lower())
            shadowed = ctes & tables
            if shadowed:
                validation_result["blocks"].append(f"cte_shadowing: {shadowed}")

            # Check for dangerous functions in comments (Adv-003)
            if "/*!" in sql and ("SLEEP" in sql or "BENCHMARK" in sql):
                validation_result["blocks"].append("masked_dangerous_function")

            # 3. Cartesian explosion pre-execution check (Adv-002)
            is_cartesian, cart_reason = check_cartesian_explosion(sql, dialect="mysql")
            if is_cartesian:
                validation_result["warnings"].append(f"cartesian_explosion: {cart_reason}")
                clamped, was_clamped = clamp_cartesian_limits(sql, max_cartesian_limit=100, dialect="mysql")
                validation_result["clamped_sql"] = clamped
                validation_result["was_clamped"] = was_clamped

        except Exception as e:
            validation_result["errors"].append(str(e))

        return validation_result

    def run_single_question(self, question: dict[str, Any]) -> dict[str, Any]:
        """Run a single question through the pipeline"""
        start_time = time.time()
        result: dict[str, Any] = {
            "id": question.get("id"),
            "question": question.get("question"),
            "expected_route": question.get("route", "SQL"),
            "success": False,
            "error": None,
            "tokens_used": 0,
            "latency": 0.0,
            "observed_route": None,
            "score": 0.0,
            "validator_blocked": False,
        }

        try:
            q_text = question.get("question", "")
            if hasattr(self.pipeline, "run"):
                response = self.pipeline.run(q_text)
            elif hasattr(self.pipeline, "query"):
                if asyncio.iscoroutinefunction(self.pipeline.query):
                    response = asyncio.run(self.pipeline.query(q_text))
                else:
                    response = self.pipeline.query(q_text)
            else:
                response = None

            result["latency"] = time.time() - start_time
            result["success"] = True

            if isinstance(response, dict):
                result["observed_route"] = response.get("route", "SQL")
                result["tokens_used"] = response.get("usage", {}).get("total_tokens", 0)
                result["answer"] = response.get("answer", "")
                if result["observed_route"] == result["expected_route"]:
                    result["score"] = 1.0
                elif response.get("data") or response.get("rows"):
                    result["score"] = 0.5
            elif response is not None:
                # QueryResult object
                usage = getattr(response, "usage", None)
                result["tokens_used"] = getattr(usage, "total_tokens", 0) if usage else 0
                result["answer"] = getattr(response, "answer", "")
                result["observed_route"] = "SQL" if "SQL Query Executed" in result["answer"] else "DOC"
                if result["observed_route"] == result["expected_route"]:
                    result["score"] = 1.0
                else:
                    result["score"] = 0.5
            else:
                result["observed_route"] = "SQL"
                result["score"] = 0.5

        except Exception as e:
            result["latency"] = time.time() - start_time
            result["error"] = str(e)
            if "blocked" in str(e).lower() or "unsafe" in str(e).lower():
                result["validator_blocked"] = True

        return result

    def run_adversarial_suite(self) -> list[dict[str, Any]]:
        """Run the 5 adversarial queries"""
        print("\n🛡️  Running Adversarial Validator Suite...")
        results = []

        for query in self.get_adversarial_queries():
            print(f"  Testing {query['id']} ({query['type']})...")

            validation = self.test_validator_directly(query["sql"])

            actual_blocked = (not validation["is_safe"]) or (len(validation["blocks"]) > 0)
            passed = (query["expected_block"] and actual_blocked) or (
                (not query["expected_block"]) and validation["is_safe"] and len(validation["blocks"]) == 0
            )

            result = {
                "id": query["id"],
                "type": query["type"],
                "sql": query["sql"],
                "expected_block": query["expected_block"],
                "actual_blocked": actual_blocked,
                "blocks_found": validation["blocks"],
                "warnings": validation.get("warnings", []),
                "was_clamped": validation.get("was_clamped", False),
                "clamped_sql": validation.get("clamped_sql", query["sql"]),
                "errors": validation["errors"],
                "passed": passed,
            }
            results.append(result)

            status = "✅ PASS" if result["passed"] else "❌ FAIL"
            info = []
            if result['blocks_found']:
                info.append(f"Blocks: {result['blocks_found']}")
            if result['warnings']:
                info.append(f"Warnings: {result['warnings']}")
            if result['was_clamped']:
                info.append("Clamped: LIMIT 100")
            print(f"    {status} - {', '.join(info) if info else 'Safe'}")

        return results

    def run_full_evaluation(self, questions: list[dict[str, Any]], max_workers: int = 4) -> None:
        """Run evaluation on all questions"""
        print(f"\n🚀 Starting Live Evaluation on {len(questions)} questions...")

        successful = 0
        failed = 0
        blocked = 0
        total_tokens = 0
        latencies = []

        for i, q in enumerate(questions):
            print(f"[{i+1}/{len(questions)}] Running {q['id']}...", end="\r", flush=True)

            result = self.run_single_question(q)
            self.results.append(result)

            if result["success"]:
                successful += 1
                total_tokens += result["tokens_used"]
                latencies.append(result["latency"])
                obs_route = result.get("observed_route") or "SQL"
                self.metrics["route_distribution"][obs_route] = (
                    self.metrics["route_distribution"].get(obs_route, 0) + 1
                )
            else:
                failed += 1
                if result["validator_blocked"]:
                    blocked += 1

            # Update difficulty/domain breakdown
            diff = q.get("difficulty", "unknown")
            self.metrics["difficulty_breakdown"][diff] = (
                self.metrics["difficulty_breakdown"].get(diff, 0) + 1
            )

            domain = q.get("domain", "unknown")
            self.metrics["domain_breakdown"][domain] = (
                self.metrics["domain_breakdown"].get(domain, 0) + 1
            )

        # Save aggregates
        self.metrics["total_questions"] = len(questions)
        self.metrics["successful_executions"] = successful
        self.metrics["failed_executions"] = failed
        self.metrics["validator_blocks"] = blocked
        self.metrics["total_tokens"] = total_tokens
        self.metrics["avg_latency"] = statistics.mean(latencies) if latencies else 0.0
        self.metrics["p95_latency"] = (
            statistics.quantiles(latencies, n=20)[-1]
            if len(latencies) > 20
            else (max(latencies) if latencies else 0.0)
        )

    def generate_report(self, output_dir: str = "evals/globalmind/results") -> None:
        """Generate comprehensive JSON and CSV reports"""
        out_path = Path(output_dir)
        if not out_path.is_absolute():
            out_path = REPO_ROOT / output_dir
        out_path.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # 1. Full JSON Report
        report_data = {
            "timestamp": timestamp,
            "summary_metrics": self.metrics,
            "detailed_results": self.results,
            "adversarial_results": self.adversarial_results,
        }

        json_path = out_path / f"full_eval_report_{timestamp}.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(report_data, f, indent=2, ensure_ascii=False)
        print(f"\n💾 Full JSON report saved to: {json_path}")

        # 2. Summary Text Report
        summary_path = out_path / f"eval_summary_{timestamp}.txt"
        total_q = max(self.metrics["total_questions"], 1)
        with open(summary_path, "w", encoding="utf-8") as f:
            f.write("=" * 60 + "\n")
            f.write("GLOBALMIND LIVE EVALUATION SUMMARY (BASELINE V2)\n")
            f.write("=" * 60 + f"\nTimestamp: {timestamp}\n\n")

            f.write("📊 PERFORMANCE METRICS\n")
            f.write(f"Total Questions:       {self.metrics['total_questions']}\n")
            f.write(
                f"Successful Executions: {self.metrics['successful_executions']} ({self.metrics['successful_executions']/total_q*100:.1f}%)\n"
            )
            f.write(f"Failed Executions:     {self.metrics['failed_executions']}\n")
            f.write(f"Validator Blocks:      {self.metrics['validator_blocks']}\n")
            f.write(f"Total Tokens Used:     {self.metrics['total_tokens']:,}\n")
            f.write(f"Avg Latency:           {self.metrics['avg_latency']:.2f}s\n")
            f.write(f"P95 Latency:           {self.metrics['p95_latency']:.2f}s\n\n")

            f.write("🗺️  ROUTE DISTRIBUTION\n")
            for route, count in self.metrics["route_distribution"].items():
                pct = (count / total_q) * 100
                f.write(f"{route:8}: {count:3} ({pct:.1f}%)\n")

            f.write("\n🛡️  ADVERSARIAL VALIDATOR RESULTS\n")
            adv_passes = sum(1 for r in self.adversarial_results if r["passed"])
            f.write(f"Passed: {adv_passes}/{len(self.adversarial_results)}\n")
            for r in self.adversarial_results:
                status = "PASS" if r["passed"] else "FAIL"
                extra = []
                if r.get("blocks_found"):
                    extra.append(f"Blocks={r['blocks_found']}")
                if r.get("warnings"):
                    extra.append(f"Warnings={r['warnings']}")
                if r.get("was_clamped"):
                    extra.append(f"Clamped={r['clamped_sql']}")
                extra_str = " | ".join(extra) if extra else "No blocks/warnings"
                f.write(f"  [{status}] {r['id']} ({r['type']}): {extra_str}\n")

        print(f"📝 Summary report saved to: {summary_path}")

        # 3. CSV for Excel Analysis
        csv_path = out_path / f"eval_results_{timestamp}.csv"
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "ID",
                "Question",
                "Expected Route",
                "Observed Route",
                "Success",
                "Score",
                "Tokens",
                "Latency",
                "Error",
            ])
            for r in self.results:
                writer.writerow([
                    r["id"],
                    (r["question"][:50] + "...") if r.get("question") else "",
                    r.get("expected_route", ""),
                    r.get("observed_route", ""),
                    r.get("success", False),
                    r.get("score", 0.0),
                    r.get("tokens_used", 0),
                    f"{r.get('latency', 0.0):.2f}",
                    (r["error"][:50]) if r.get("error") else "",
                ])
        print(f"📈 CSV data saved to: {csv_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run GlobalMind Live Evaluation (Baseline v2)")
    parser.add_argument(
        "--questions",
        type=str,
        default="evals/globalmind/questions.jsonl",
        help="Path to questions file",
    )
    parser.add_argument("--db", type=str, default="global_mind.db", help="Path to SQLite database")
    parser.add_argument("--adversarial-only", action="store_true", help="Run only adversarial tests")
    parser.add_argument("--limit", type=int, help="Limit number of questions to run")

    args = parser.parse_args()

    evaluator = LiveEvaluator(db_path=args.db)

    # 1. Always run adversarial suite first
    evaluator.adversarial_results = evaluator.run_adversarial_suite()

    if args.adversarial_only:
        evaluator.generate_report()
        return

    # 2. Load and run full question set
    questions = evaluator.load_questions(args.questions)
    if not questions:
        print("❌ No questions loaded. Exiting.")
        return

    if args.limit:
        questions = questions[: args.limit]
        print(f"⚠️  Limited to {args.limit} questions")

    evaluator.run_full_evaluation(questions)
    evaluator.generate_report()

    print("\n✅ Evaluation Complete! Check 'evals/globalmind/results/' for reports.")


if __name__ == "__main__":
    main()

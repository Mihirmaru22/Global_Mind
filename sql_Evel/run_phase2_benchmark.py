#!/usr/bin/env python3
"""
GlobalMind SQL Pipeline - Phase 2 Automated Benchmark Runner

Modes:
  validate_golden : Execute every golden SQL on the DB (NO LLM).
                    Proves the benchmark is executable and produces stable hashes.
  firewall        : Push negative/security SQL through the read-only AST
                    firewall (NO LLM, NO execution). Proves guardrails work.
  score           : Score a predictions file (id -> generated_sql) against
                    golden hashes (NO LLM during scoring).

Privacy model: result data never leaves this machine and never reaches the LLM.
"""

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

try:
    import dotenv
    dotenv.load_dotenv(REPO_ROOT / ".env")
except ImportError:
    pass

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_DATASET = SCRIPT_DIR / "phase1_golden_dataset.jsonl"
DEFAULT_VALIDATION = SCRIPT_DIR / "phase2_golden_validation.jsonl"
DEFAULT_OUTPUT = SCRIPT_DIR / "phase2_results.jsonl"
DEFAULT_REPORT = SCRIPT_DIR / "phase2_report.md"
DEFAULT_PREDICTIONS = SCRIPT_DIR / "predictions.jsonl"

ROW_CAP = 500

SENSITIVE_COLUMN_TOKENS = {
    "password", "remember_token", "token", "payload", "exception",
    "bank_account_no", "ifsc_code", "pan_no",
}


def extract_base_tables(sql):
    """Extracts all table names referenced in the SQL query."""
    try:
        import sqlglot
        from sqlglot import expressions as exp
        parsed = sqlglot.parse_one(sql, read="mysql")
        return {t.name for t in parsed.find_all(exp.Table)}
    except Exception:
        # Fallback if sqlglot fails to parse
        return set(re.findall(r'\bfrom\s+`?([a-zA-Z0-9_]+)`?\b', sql.lower())) | \
               set(re.findall(r'\bjoin\s+`?([a-zA-Z0-9_]+)`?\b', sql.lower()))


def check_soft_delete_applied(sql):
    """Checks if the query applies the standard soft-delete filter."""
    lower = sql.lower()
    return "deleted_at is null" in lower or "deleted_at = null" in lower


# ---------------------------------------------------------------- executors
class SqliteExecutor:
    def __init__(self, path):
        resolved = Path(path).resolve()
        if not resolved.exists():
            raise FileNotFoundError(
                f"SQLite database file not found at: {resolved}\n"
                f"Please ensure the database exists or load your database dump into {path}."
            )
        self.conn = sqlite3.connect(f"file:{resolved}?mode=ro", uri=True, timeout=10)

    def run(self, sql):
        cur = self.conn.cursor()
        cur.execute(sql)
        rows = cur.fetchmany(ROW_CAP + 1)
        cols = [d[0] for d in cur.description] if cur.description else []
        return cols, rows

    def close(self):
        self.conn.close()


class MysqlExecutor:
    def __init__(self):
        import pymysql

        self.conn = pymysql.connect(
            host=os.environ.get("DB_HOST", "127.0.0.1"),
            port=int(os.environ.get("DB_PORT", "3306")),
            user=os.environ.get("DB_READONLY_USER") or os.environ.get("DB_USER", "root"),
            password=os.environ.get("DB_READONLY_PASSWORD", os.environ.get("DB_PASSWORD", "")),
            database=os.environ.get("DB_NAME", "globalmind"),
            connect_timeout=10,
            read_timeout=30,
        )

    def run(self, sql):
        with self.conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchmany(ROW_CAP + 1)
            cols = [d[0] for d in cur.description] if cur.description else []
            return cols, rows

    def close(self):
        self.conn.close()


def build_executor(args):
    if args.db == "sqlite":
        return SqliteExecutor(args.sqlite_path)
    return MysqlExecutor()


# ------------------------------------------------------------------ helpers
def load_jsonl(path):
    with open(path, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def write_jsonl(records, path):
    with open(path, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def canonical_hash(rows):
    """Data-only hash: rows normalized to strings and sorted.

    Column names/aliases are intentionally NOT part of the hash so that
    semantically equivalent SQL with different aliases still passes.
    """
    norm = sorted(
        tuple("" if v is None else str(v) for v in row) for row in rows
    )
    payload = json.dumps(norm, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest(), len(norm)


def execute_safe(executor, sql):
    try:
        cols, rows = executor.run(sql)
        return {"ok": True, "columns": cols, "rows": rows}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": type(exc).__name__, "message": str(exc)[:300]}


# ----------------------------------------------------------------- firewall
def load_pipeline_firewall():
    """Try to reuse the real pipeline AST firewall; fall back to local check."""
    try:
        sys.path.insert(0, str(REPO_ROOT))
        from src.core import db_client

        for name in ("_is_safe_read_query", "is_safe_read_query"):
            fn = getattr(db_client, name, None)
            if fn:
                return fn, f"pipeline:{name}"
    except Exception:
        pass
    return None, None


def local_firewall(sql):
    """Fallback read-only AST firewall (returns True if ALLOWED)."""
    try:
        import sqlglot
        from sqlglot import expressions as exp

        statements = sqlglot.parse(sql)
    except Exception:
        return False

    if len(statements) != 1 or statements[0] is None:
        return False

    root = statements[0]
    if not isinstance(root, (exp.Select, exp.Union)):
        return False

    upper = sql.upper()
    for token in (
        "INTO OUTFILE", "INTO DUMPFILE",
        "LOAD_FILE(", "SLEEP(", "BENCHMARK(", "GET_LOCK(", "SYS_EVAL(",
    ):
        if token in upper:
            return False
    return True


def local_sensitive_scan(sql):
    """Returns True if the SQL references a sensitive column (should be blocked)."""
    lower = sql.lower()
    return any(tok in lower for tok in SENSITIVE_COLUMN_TOKENS)


# -------------------------------------------------------------------- modes
def run_validate_golden(cases, executor, args):
    records = []
    for case in cases:
        rec = {
            "id": case["id"],
            "suite": case["suite"],
            "expected_outcome": case["expected_outcome"],
        }
        if case["expected_outcome"] != "execute":
            rec["status"] = "skipped_negative"
            records.append(rec)
            continue

        t0 = time.time()
        res = execute_safe(executor, case["sql"])
        rec["latency_ms"] = int((time.time() - t0) * 1000)

        if res["ok"]:
            digest, count = canonical_hash(res["rows"])
            rec["status"] = "golden_ok"
            rec["golden_result_hash"] = digest
            rec["row_count"] = count
            if len(res["rows"]) == 1 and len(res["rows"][0]) == 1:
                try:
                    rec["golden_value"] = int(res["rows"][0][0])
                except (ValueError, TypeError):
                    pass
        else:
            rec["status"] = "golden_broken"
            rec["error"] = res.get("error")
            rec["message"] = res.get("message")
        records.append(rec)

    write_jsonl(records, DEFAULT_VALIDATION)
    return records


def run_firewall(cases, args):
    pipeline_fn, source = load_pipeline_firewall()
    check = pipeline_fn or local_firewall

    records = []
    for case in cases:
        if case["suite"] != "negative_security":
            continue

        tags = set(case.get("post_prune_tags", []))
        allowed = bool(check(case["sql"]))
        sensitive = local_sensitive_scan(case["sql"])

        if tags & {"non_select", "stacked_query", "dangerous_function"}:
            status = "firewall_ok" if not allowed else "FALSE_NEGATIVE_CRITICAL"
        elif "sensitive_column" in tags:
            blocked = (not allowed) or sensitive
            status = "policy_ok" if blocked else "POLICY_GAP_REVIEW"
        elif "large_result" in tags:
            status = "informational_limit_clamp"
        else:  # invalid_schema etc. -> caught later by schema validation layer
            status = "defer_to_schema_validation"

        records.append({
            "id": case["id"],
            "suite": case["suite"],
            "firewall_source": source or "local_sqlglot",
            "allowed": allowed,
            "status": status,
        })

    write_jsonl(records, DEFAULT_OUTPUT)
    return records


def run_score(cases, executor, args):
    # Load ALL validation records (not just golden_ok) so we can handle missing views
    validation_records = {rec["id"]: rec for rec in load_jsonl(DEFAULT_VALIDATION)}
    predictions = {p["id"]: p for p in load_jsonl(args.predictions)}
    
    KNOWN_MISSING_VIEWS = {
        "carton_search_view", "dc_stock_view", "pending_so_stock_view",
        "so_stock_view", "stock_alert_raw_material_view", "stock_alert_view"
    }

    records = []
    for case in cases:
        if case["expected_outcome"] != "execute":
            continue
        pred = predictions.get(case["id"])
        gold = validation_records.get(case["id"])

        rec = {"id": case["id"], "suite": case["suite"]}
        if pred is None:
            rec["status"] = "no_prediction"
            records.append(rec)
            continue
        if gold is None:
            rec["status"] = "golden_unavailable"
            records.append(rec)
            continue

        gen_sql = pred.get("generated_sql") or ""
        if not gen_sql.strip():
            rec["status"] = "NO_SQL"
            records.append(rec)
            continue

        # Handle infrastructure debt: Golden query was broken due to missing views
        if gold.get("status") == "golden_broken":
            msg = (gold.get("message") or "").lower()
            if any(v in msg for v in KNOWN_MISSING_VIEWS):
                rec["status"] = "excluded_view_missing"
                records.append(rec)
                continue
            else:
                rec["status"] = "golden_broken_other"
                records.append(rec)
                continue

        # Execute the LLM's generated SQL
        res = execute_safe(executor, gen_sql)
        
        if not res["ok"]:
            msg = (res.get("message") or "").lower()
            if "doesn't exist" in msg or "no such table" in msg:
                if any(v in msg for v in KNOWN_MISSING_VIEWS):
                    rec["status"] = "excluded_view_missing"
                else:
                    rec["status"] = "SCHEMA_MISSING"
            elif "no such column" in msg or "unknown column" in msg or "ambiguous" in msg:
                rec["status"] = "COLUMN_ERROR"
            elif "syntax" in msg:
                rec["status"] = "SYNTAX_ERROR"
            elif "timeout" in msg or "timed out" in msg:
                rec["status"] = "TIMEOUT"
            else:
                rec["status"] = "EXECUTION_ERROR"
            rec["message"] = res.get("message")
        else:
            # --- GRADING LOGIC ---
            if case["suite"] == "table_select_smoke":
                base_table = case["expected_tables"][0]
                used_tables = extract_base_tables(gen_sql)
                
                if base_table not in used_tables:
                    rec["status"] = "MISSING_BASE_TABLE"
                    rec["message"] = f"Target table '{base_table}' not found in generated SQL."
                elif len(res["rows"]) == 0 and gold.get("row_count", 0) > 0:
                    rec["status"] = "EMPTY_RESULT_BUT_GOLDEN_HAS_ROWS"
                    rec["message"] = "LLM filtered out all rows, but golden query returned data."
                else:
                    rec["status"] = "PASS_INTENT"
                    rec["applied_soft_delete"] = check_soft_delete_applied(gen_sql)
                    rec["row_count"] = len(res["rows"])

            elif case["suite"] == "table_count_smoke":
                # --- VALUE-BASED GRADING FOR COUNTS ---
                try:
                    digest, count = canonical_hash(res["rows"])
                    is_hash_match = (digest == gold.get("golden_result_hash"))

                    golden_val = gold.get("golden_value")
                    if golden_val is None and "rows" in gold:
                        golden_val = int(gold["rows"][0][0])

                    gen_val = int(res["rows"][0][0]) if res["rows"] and len(res["rows"][0]) > 0 else None

                    if is_hash_match or (golden_val is not None and golden_val == gen_val):
                        rec["status"] = "PASS_VALUE_MATCH"
                        rec["applied_soft_delete"] = check_soft_delete_applied(gen_sql)
                        rec["count_value"] = gen_val
                    else:
                        rec["status"] = "VALUE_MISMATCH"
                        rec["message"] = f"Golden count: {golden_val if golden_val is not None else gold.get('golden_result_hash')}, LLM count: {gen_val}"
                except Exception as e:
                    rec["status"] = "EXTRACTION_ERROR"
                    rec["message"] = str(e)
                    
            else:
                # --- STRICT HASH GRADING FOR OTHER SUITES ---
                digest, count = canonical_hash(res["rows"])
                if digest == gold.get("golden_result_hash"):
                    rec["status"] = "PASS_EXACT"
                else:
                    rec["status"] = "RESULT_MISMATCH"
                rec["row_count"] = count
                rec["golden_row_count"] = gold.get("row_count")
                
        records.append(rec)

    write_jsonl(records, DEFAULT_OUTPUT)
    return records


# ------------------------------------------------------------------- report
def write_report(records, mode, args):
    from collections import Counter

    by_status = Counter(r["status"] for r in records)
    by_suite = {}
    for r in records:
        by_suite.setdefault(r["suite"], Counter())[r["status"]] += 1

    lines = [
        f"# Phase 2 Report — mode `{mode}`",
        "",
        f"Dataset: `{args.dataset}`",
        f"DB: `{args.db}`" + (f" `{args.sqlite_path}`" if args.db == "sqlite" else " (mysql env)"),
        "",
        "## Overall",
        "",
        "| Status | Count |",
        "|---|---:|",
    ]
    lines += [f"| {k} | {v} |" for k, v in sorted(by_status.items())]
    lines += ["", "## By Suite", ""]
    for suite, counts in sorted(by_suite.items()):
        lines.append(f"### {suite}")
        lines += [f"- {k}: {v}" for k, v in sorted(counts.items())]
        lines.append("")

    DEFAULT_REPORT.write_text("\n".join(lines), encoding="utf-8")


# --------------------------------------------------------------------- main
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", required=True,
                        choices=["validate_golden", "firewall", "score"])
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET))
    parser.add_argument("--db", choices=["sqlite", "mysql"], default=os.environ.get("DB_ENGINE", "mysql"))
    parser.add_argument("--sqlite-path", default=str(REPO_ROOT / "data" / "live_data.db"))
    parser.add_argument("--predictions", default=str(DEFAULT_PREDICTIONS))
    parser.add_argument("--suite", default=None, help="optional suite filter")
    args = parser.parse_args()

    cases = load_jsonl(args.dataset)
    if args.suite:
        cases = [c for c in cases if c["suite"] == args.suite]

    executor = None
    if args.mode in ("validate_golden", "score"):
        executor = build_executor(args)

    try:
        if args.mode == "validate_golden":
            records = run_validate_golden(cases, executor, args)
        elif args.mode == "firewall":
            records = run_firewall(cases, args)
        else:
            records = run_score(cases, executor, args)
    finally:
        if executor:
            executor.close()

    write_report(records, args.mode, args)

    from collections import Counter
    print(f"Mode {args.mode} complete. {len(records)} records.")
    for status, count in sorted(Counter(r["status"] for r in records).items()):
        print(f"  {status}: {count}")
    print(f"Report: {DEFAULT_REPORT}")


if __name__ == "__main__":
    main()
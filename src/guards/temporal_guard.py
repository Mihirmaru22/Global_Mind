"""Temporal Filter Guard (Shadow Mode).

Detects temporal intent in user queries and verifies that the generated SQL
contains valid temporal constraints (BETWEEN, >=, <=, DATEDIFF, etc.) in the WHERE clause.
Operates in < 1ms in-memory with zero LLM calls.
"""

from __future__ import annotations

import re
import time
from typing import Any

import sqlglot
from sqlglot import exp

from src.models.trace import GuardResult
from src.utils.error_classification import FailureCategory
from src.utils.feature_flags import is_feature_enabled

_TEMPORAL_PATTERNS = [
    # Explicit dates: 2025-06-03, 2024/01/01
    r"\b\d{4}[-/]\d{1,2}[-/]\d{1,2}\b",
    # Years: 1998, 2023, 2024, 2025
    r"\b(19|20)\d{2}\b",
    # Relative windows
    r"\b(last|past|previous|this)\s+(month|year|quarter|week|day|days|\d+\s+days|\d+\s+months)\b",
    # Temporal operators
    r"\b(between|after|before|since|until|from|overdue|as of|ytd|quarterly|monthly)\b",
    # Specific months
    r"\b(january|february|march|april|may|june|july|august|september|october|november|december)\b",
    # Specific date keywords in schema
    r"\b(due date|order date|dispatch date|created at|adjustment date|batch date)\b",
]

_TEMPORAL_RE = re.compile("|".join(_TEMPORAL_PATTERNS), re.IGNORECASE)

_DATE_FUNCTIONS = frozenset({
    "datediff", "date_sub", "date_add", "curdate", "current_date",
    "now", "year", "month", "quarter", "day", "date",
})


def has_temporal_intent(query: str) -> bool:
    """Detect if the user query requests date/time bounded data."""
    if not query:
        return False
    return bool(_TEMPORAL_RE.search(query))


def evaluate_temporal_filter(
    query: str,
    sql: str,
    dialect: str = "mysql",
    enforce: bool | None = None,
) -> GuardResult:
    """Evaluate whether temporal query intent is reflected in SQL WHERE clause."""
    t0 = time.perf_counter()
    if enforce is None:
        enforce = is_feature_enabled("guard_sql_temporal_enforce")
    mode = "ENFORCED" if enforce else "SHADOW"

    # If query has no temporal intent, guard trivially passes
    if not has_temporal_intent(query):
        latency_ms = (time.perf_counter() - t0) * 1000
        return GuardResult(
            guard_name="sql_temporal",
            passed=True,
            mode=mode,
            message="No temporal intent in query; guard bypassed",
            latency_ms=round(latency_ms, 3),
        )

    # If query has temporal intent, SQL must exist
    if not sql or not sql.strip():
        latency_ms = (time.perf_counter() - t0) * 1000
        return GuardResult(
            guard_name="sql_temporal",
            passed=False,
            mode=mode,
            failure_category=FailureCategory.MISSING_TEMPORAL_FILTER.value,
            message="Temporal intent detected in query, but SQL is empty",
            latency_ms=round(latency_ms, 3),
        )

    try:
        parsed = sqlglot.parse_one(sql, read=dialect)
    except Exception:
        latency_ms = (time.perf_counter() - t0) * 1000
        return GuardResult(
            guard_name="sql_temporal",
            passed=True,  # Syntax errors handled by SQL syntax guard
            mode=mode,
            message="SQL unparseable; skipped temporal check",
            latency_ms=round(latency_ms, 3),
        )

    # Inspect WHERE clause for temporal predicates
    where = parsed.args.get("where")
    has_temporal_pred = False

    if where:
        # 1. Check comparison operations: BETWEEN, >=, <=, >, <, LIKE
        temporal_comparisons = (exp.Between, exp.GTE, exp.LTE, exp.GT, exp.LT, exp.Like)
        for comp in where.find_all(temporal_comparisons):
            # Check if any side is a date/time column or date string
            txt = comp.sql().lower()
            if any(k in txt for k in ["date", "time", "created_at", "updated_at", "year", "20", "19", "curdate", "now"]):
                has_temporal_pred = True
                break

        # 2. Check equality to date literal: e.g. date_col = '2025-06-03'
        if not has_temporal_pred:
            for eq_node in where.find_all(exp.EQ):
                txt = eq_node.sql().lower()
                if re.search(r"\b20\d{2}[-/]\d{1,2}[-/]\d{1,2}\b", txt) or re.search(r"\b20\d{2}\b", txt):
                    has_temporal_pred = True
                    break

        # 3. Check date functions: DATEDIFF(due_date, order_date)
        if not has_temporal_pred:
            for fn in where.find_all(exp.Anonymous):
                if fn.this.lower() in _DATE_FUNCTIONS:
                    has_temporal_pred = True
                    break

    latency_ms = (time.perf_counter() - t0) * 1000

    if not has_temporal_pred:
        # TODO(V1.1): Fix "Date Projection vs. Date Filtering" trap (10.11% FPR).
        # When a query requests a date column as a projected scalar attribute (e.g. `SELECT due_date`)
        # rather than a filtering predicate in WHERE, inspect AST SELECT expressions and yield PASS.
        # See docs/V1_1_GUARD_CALIBRATION_PLAN.md for the full specification.
        return GuardResult(
            guard_name="sql_temporal",
            passed=False,
            mode=mode,
            failure_category=FailureCategory.MISSING_TEMPORAL_FILTER.value,
            message="User query specifies temporal constraints, but generated SQL WHERE clause contains no temporal filter",
            latency_ms=round(latency_ms, 3),
            metadata={"query": query[:200], "sql": sql[:200]},
        )

    return GuardResult(
        guard_name="sql_temporal",
        passed=True,
        mode=mode,
        message="Temporal predicate successfully verified in SQL WHERE clause",
        latency_ms=round(latency_ms, 3),
    )

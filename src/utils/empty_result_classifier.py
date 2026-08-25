"""Classification engine for empty (0-row) database results.

Distinguishes between valid business emptiness (no records matching valid filter)
and suspicious empty results (mismatched join keys, broken joins without filters,
impossible date bounds, or malformed string predicates).
"""

from __future__ import annotations

import logging
import re
from typing import Any

import sqlglot
from sqlglot import exp

logger = logging.getLogger(__name__)

VALID_EMPTY = "valid_empty"
SUSPICIOUS_EMPTY = "suspicious_empty"


def classify_empty_result(sql: str, dialect: str | None = None) -> str:
    """Classify an empty (0-row) database execution result.

    Args:
        sql: The executed SQL query string.
        dialect: Optional SQL dialect name (e.g. "sqlite", "mysql", "postgres").

    Returns:
        "valid_empty": Legitimate business emptiness (e.g. no records matching
            valid filter, or empty table). Should NOT be retried.
        "suspicious_empty": Structural or logical flaw (e.g. JOIN without WHERE,
            mismatched join keys, impossible future date filter, malformed LIKE pattern).
            Deserves one targeted repair attempt.
    """
    if not sql or not sql.strip():
        return VALID_EMPTY

    try:
        ast = sqlglot.parse_one(sql, read=dialect)
    except Exception as exc:
        logger.debug("Failed to parse SQL in classify_empty_result: %s. Defaulting to valid_empty.", exc)
        return VALID_EMPTY

    # 1. Inspect Joins and Where clauses
    joins = list(ast.find_all(exp.Join))
    where_clause = ast.find(exp.Where)

    # Heuristic 1: Joins present, but NO WHERE clause
    # If a query joins 2+ tables without any filter and yields 0 rows, the join key
    # is almost certainly wrong/mismatched (e.g. ON orders.id = customers.id instead of customer_id).
    if joins and not where_clause:
        return SUSPICIOUS_EMPTY

    # Heuristic 2: Impossible / Far Future Dates in filters (e.g., year > 2090 or > '2099-01-01')
    if where_clause:
        for literal in where_clause.find_all(exp.Literal):
            if literal.is_string:
                val = str(literal.this)
                if re.search(r"\b(209\d|21\d\d)\b", val):
                    return SUSPICIOUS_EMPTY

    # Heuristic 3: Excessive or suspicious LIKE patterns (> 40 chars)
    for like_node in ast.find_all(exp.Like, exp.ILike):
        pattern_expr = like_node.expression
        if pattern_expr and isinstance(pattern_expr, exp.Literal) and pattern_expr.is_string:
            clean_pattern = str(pattern_expr.this).replace("%", "").replace("_", "")
            if len(clean_pattern) > 40:
                return SUSPICIOUS_EMPTY

    # Default to valid_empty (Fail-Safe: prefer false negative over wasting repair tokens)
    return VALID_EMPTY

# KNOWN LIMITATION: circuit breaker resets on restart. Persist to Redis or config store in v2.
"""Layer 2 — Template Fast Path.

Eliminates synthesis LLM latency (~10.5s) for pure factual queries (COUNT, SUM, LIST)
by deterministically formatting validated SQL results into natural Markdown.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

from src.utils.query_classifier import QueryType, classify_query

logger = logging.getLogger(__name__)

# Disqualifiers for contextual / analytical queries that must route to full synthesis
DISQUALIFIERS = [
    "due to",
    "because of",
    "as a result",
    "given that",
    "based on",
    "in the context of",
    "why",
    "explain",
    "compared to",
    "relative to",
    "versus",
    " vs ",
]

FAIL_RATE_THRESHOLD = 0.01  # 1% failure rate ceiling
_fail_counters: dict[QueryType, tuple[int, int]] = {}  # (failures, total)

# Manual override to disable templates via environment variable (comma-separated, e.g. "count,sum")
_disabled_env = os.environ.get("DISABLED_FAST_PATH_TEMPLATES", "").strip().lower()
DISABLED_TEMPLATES: set[QueryType] = {
    QueryType(t.strip()) for t in _disabled_env.split(",") if t.strip() in QueryType._value2member_map_
}


def is_pure_factual(question: str) -> bool:
    """Return True if question is purely factual and contains no analytical disqualifiers."""
    if not question:
        return False
    q = question.lower()
    return not any(d in q for d in DISQUALIFIERS)


def _record_fast_path_failure(query_type: QueryType) -> None:
    """Record a failure for the circuit breaker."""
    failures, total = _fail_counters.get(query_type, (0, 0))
    _fail_counters[query_type] = (failures + 1, total + 1)


def _record_fast_path_success(query_type: QueryType) -> None:
    """Record a success for the circuit breaker."""
    failures, total = _fail_counters.get(query_type, (0, 0))
    _fail_counters[query_type] = (failures, total + 1)


def is_template_enabled(query_type: QueryType) -> bool:
    """Check if template is enabled (not manually disabled and under failure rate threshold)."""
    if query_type in DISABLED_TEMPLATES:
        return False
    failures, total = _fail_counters.get(query_type, (0, 0))
    if total < 50:
        return True  # not enough data to trip
    return (failures / total) < FAIL_RATE_THRESHOLD


def _extract_entity_name(question: str) -> str:
    """Extract entity noun phrase from question (e.g. 'customers', 'delivery challans')."""
    q = question.strip()
    m = re.search(r"(?:how many|count of|number of|total count of)\s+([a-zA-Z0-9_\s]+?)(?:\s+(?:are there|were|in|with|for|that|from|\?|$))", q, re.IGNORECASE)
    if m:
        entity = m.group(1).strip()
        if entity:
            return entity
    return "records"


def _extract_metric_name(question: str) -> str:
    """Extract metric name from question (e.g. 'revenue', 'gross amount')."""
    q = question.strip()
    m = re.search(r"(?:what is the total|sum of|total|sum)\s+([a-zA-Z0-9_\s]+?)(?:\s+(?:of|for|in|by|\?|$))", q, re.IGNORECASE)
    if m:
        metric = m.group(1).strip()
        if metric:
            return metric
    return "amount"


def _format_numeric_value(val_str: str) -> str:
    """Format numeric string with locale-aware commas and decimals."""
    try:
        val_float = float(val_str.replace(",", "").strip())
        if val_float.is_integer():
            return f"{int(val_float):,}"
        return f"{val_float:,.2f}"
    except (ValueError, TypeError):
        return val_str.strip()


def _parse_single_markdown_cell(markdown_table: str) -> tuple[str, str] | None:
    """Extract header and single cell value from a 1-row, 1-col markdown table."""
    lines = [l.strip() for l in markdown_table.strip().splitlines() if l.strip()]
    table_lines = [l for l in lines if l.startswith("|")]
    data_lines = [l for l in table_lines if not l.startswith("|-") and not l.startswith("|:--") and not l.startswith("|---")]
    if len(data_lines) == 2:  # Header + 1 Data row
        headers = [c.strip() for c in data_lines[0].strip("|").split("|")]
        row = [c.strip() for c in data_lines[1].strip("|").split("|")]
        if len(headers) == 1 and len(row) == 1:
            return headers[0], row[0]
    return None


def _apply_template(query_type: QueryType, sql_result_table: str, question: str) -> str | None:
    """Apply deterministic template based on query_type and markdown table shape."""
    if not sql_result_table or not sql_result_table.strip():
        return None

    clean_table = sql_result_table.strip()

    if query_type == QueryType.COUNT:
        cell_info = _parse_single_markdown_cell(clean_table)
        if cell_info:
            _, val = cell_info
            formatted_val = _format_numeric_value(val)
            entity = _extract_entity_name(question)
            return f"There are {formatted_val} {entity}.\n\n{clean_table}"
        # Fallback if table has more columns
        return f"Here is the count matching your request:\n\n{clean_table}"

    if query_type == QueryType.SUM:
        cell_info = _parse_single_markdown_cell(clean_table)
        if cell_info:
            _, val = cell_info
            formatted_val = _format_numeric_value(val)
            metric = _extract_metric_name(question)
            return f"The total {metric} is {formatted_val}.\n\n{clean_table}"
        return f"Here is the total matching your request:\n\n{clean_table}"

    if query_type == QueryType.LIST:
        # Sanitize headers and format list
        lines = [l for l in clean_table.splitlines() if l.strip()]
        if len(lines) > 102:  # Truncate at 100 data rows
            header_lines = lines[:2]
            truncated_rows = lines[2:102]
            total_rows = len(lines) - 2
            sanitized_table = "\n".join(header_lines + truncated_rows)
            return f"Here are the records matching your request (showing 100 of {total_rows:,}):\n\n{sanitized_table}"
        return f"Here are the records matching your request:\n\n{clean_table}"

    return None


def fast_path_format(
    query_type: QueryType,
    sql_result_table: str,
    question: str,
) -> str | None:
    """Format factual SQL query results deterministically, bypassing synthesis LLM.

    Returns:
        Formatted markdown answer string on success, or None to trigger synthesis LLM.
    """
    if not is_template_enabled(query_type):
        return None

    if not is_pure_factual(question):
        return None

    try:
        formatted = _apply_template(query_type, sql_result_table, question)
        if formatted is not None:
            _record_fast_path_success(query_type)
            return formatted
        _record_fast_path_failure(query_type)
        return None
    except Exception as e:
        logger.warning("fast_path_fail: %s — %s", query_type.value, e)
        _record_fast_path_failure(query_type)
        return None


# ---------------------------------------------------------------------------
# Backward Compatibility for existing tests
# ---------------------------------------------------------------------------

def format_list_fast_path(markdown_table: str) -> str:
    """Format direct list queries without calling the synthesis LLM."""
    clean_table = markdown_table.strip()
    return f"Here are the records matching your request:\n\n{clean_table}"


def build_aggregate_micro_prompt(user_question: str, markdown_table: str) -> list[dict[str, str]]:
    """Build a compact micro-prompt asking for a single-sentence executive summary."""
    clean_table = markdown_table.strip()
    return [
        {
            "role": "system",
            "content": (
                "You are a concise business analyst. Given the question and tabular data, "
                "provide a direct, single-sentence summary of the key metric. Do not repeat the table rows."
            ),
        },
        {
            "role": "user",
            "content": f"Question: {user_question}\n\nData:\n{clean_table}\n\nExecutive Summary (1 sentence):",
        },
    ]


def format_aggregate_fast_path(summary: str, markdown_table: str) -> str:
    """Format aggregate response combining 1-sentence micro-summary with markdown table."""
    clean_summary = summary.strip()
    clean_table = markdown_table.strip()
    if clean_summary:
        return f"{clean_summary}\n\n{clean_table}"
    return clean_table

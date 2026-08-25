"""Delta Repair Prompt Assembly and Token Budget Enforcement.

Constructs surgical, highly compact (< 500 tokens) prompt payloads for SQL repair
without resending full schemas or conversational context.
"""

from __future__ import annotations

from typing import Any

from src.utils.error_classification import normalize_error

# Hard budget ceilings for Delta Repair
MAX_TOTAL_REPAIR_TOKENS = 500
MAX_SYSTEM_TOKENS = 100
MAX_ERROR_CHARS = 400

DELTA_REPAIR_SYSTEM_PROMPT = """You are a SQL repair assistant. Fix the failed SQL query.
Rules:
1. Output ONLY the raw corrected SQL without markdown or commentary.
2. Never use SELECT *. Explicitly list columns.
3. Never use CROSS JOIN. Use explicit JOIN conditions.
4. Use only provided schema tables and columns.
5. Preserve original query intent and filters."""


def count_tokens(text: str) -> int:
    """Conservative token count estimator across prose, code, and SQL symbols.

    Estimates tokens using standard LLM character ratio (approx 4 chars/token)
    and word count heuristic (approx 1.3 tokens/word).
    """
    if not text:
        return 0
    char_estimate = max(1, int(len(text) / 4.0 + 0.5))
    word_estimate = int(len(text.split()) * 1.3)
    return max(char_estimate, word_estimate)


def format_compact_schema(schema_context: dict[str, Any] | None, max_tables: int | None = None) -> str:
    """Format schema context into a concise, token-efficient string representation.

    Example:
    Schema Context:
    - Table 'sales_order': id, order_number, total_amount, party_id
    - Table 'party': id, party_name
    """
    if not schema_context:
        return ""

    lines: list[str] = ["Schema Context:"]
    items = list(schema_context.items())
    if max_tables is not None:
        items = items[:max_tables]

    for table_name, cols in items:
        if isinstance(cols, (list, set, tuple)):
            clean_cols = [str(c) for c in cols if c]
            if clean_cols:
                lines.append(f"- Table '{table_name}': {', '.join(clean_cols)}")
            else:
                lines.append(f"- Table '{table_name}'")
        elif isinstance(cols, dict):
            col_names = list(cols.keys())
            lines.append(f"- Table '{table_name}': {', '.join(col_names)}")
        else:
            lines.append(f"- Table '{table_name}'")

    return "\n".join(lines)


def build_delta_repair_payload(
    failed_sql: str,
    error_message: str,
    error_type: str = "sql_error",
    schema_context: dict[str, Any] | None = None,
    user_intent: str | None = None,
) -> list[dict[str, str]]:
    """Assemble a surgical, budget-enforced message array for Delta Repair.

    Returns:
        list[dict[str, str]]: Message array with [{"role": "system", ...}, {"role": "user", ...}]
        Guaranteed to stay under MAX_TOTAL_REPAIR_TOKENS (500 tokens).
    """
    clean_sql = str(failed_sql or "").strip()
    norm_error = normalize_error(str(error_message or "unknown_error"))
    if len(norm_error) > MAX_ERROR_CHARS:
        norm_error = norm_error[:MAX_ERROR_CHARS] + "..."

    system_content = DELTA_REPAIR_SYSTEM_PROMPT.strip()
    system_tokens = count_tokens(system_content)

    # 1. Attempt Full Compact Schema Context
    schema_str = format_compact_schema(schema_context)
    intent_line = f"Goal: {user_intent.strip()}\n\n" if user_intent and user_intent.strip() else ""

    def _assemble_user_msg(schema_part: str) -> str:
        parts: list[str] = [
            f"The following SQL query failed with a `{error_type}` error.\n",
            intent_line,
            f"Error:\n{norm_error}\n",
            f"Failed SQL:\n{clean_sql}\n",
        ]
        if schema_part.strip():
            parts.append(f"\n{schema_part.strip()}\n")
        parts.append("\nProvide only the corrected SQL statement.")
        return "".join(parts).strip()

    user_content = _assemble_user_msg(schema_str)
    total_tokens = system_tokens + count_tokens(user_content)

    # 2. Budget Enforcement — Level 1: Truncate columns, retain table names only
    if total_tokens > MAX_TOTAL_REPAIR_TOKENS and schema_context:
        table_names = list(schema_context.keys())
        schema_fallback_1 = "Schema Context (Table names only):\n" + "\n".join(f"- Table '{t}'" for t in table_names)
        user_content = _assemble_user_msg(schema_fallback_1)
        total_tokens = system_tokens + count_tokens(user_content)

    # 3. Budget Enforcement — Level 2: Omit schema completely
    if total_tokens > MAX_TOTAL_REPAIR_TOKENS and schema_context:
        schema_fallback_2 = "(Schema context omitted to preserve token budget)"
        user_content = _assemble_user_msg(schema_fallback_2)
        total_tokens = system_tokens + count_tokens(user_content)

    # 4. Budget Enforcement — Level 3: Hard truncate failed SQL if pathological
    if total_tokens > MAX_TOTAL_REPAIR_TOKENS:
        max_allowed_sql_len = 500
        truncated_sql = clean_sql[:max_allowed_sql_len] + "\n-- [truncated to stay in token budget]"
        user_content = (
            f"The following SQL failed with `{error_type}`.\n"
            f"Error: {norm_error}\n"
            f"Failed SQL:\n{truncated_sql}\n"
            "Provide only the corrected SQL statement."
        )

    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_content},
    ]

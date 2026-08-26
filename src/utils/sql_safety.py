"""SQL Safety Layer & AST Validation Engine using sqlglot.

Enforces read-only execution, checks for destructive SQL operations,
flags dangerous query patterns (SELECT *, CROSS JOIN), and validates
table and column references against schema context before database execution.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import sqlglot
from sqlglot import exp

logger = logging.getLogger(__name__)

DESTRUCTIVE_TYPES = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Drop,
    exp.TruncateTable,
    exp.Alter,
    exp.Create,
    exp.Grant,
    exp.Revoke,
    exp.Merge,
    exp.Command,
)

DANGEROUS_FUNCTIONS = frozenset({
    "load_file",
    "loadfile",
    "sys_eval",
    "sys_exec",
    "sys_get",
    "lo_import",
    "lo_export",
    "benchmark",
    "sleep",
    "get_lock",
    "release_lock",
    "release_all_locks",
    "is_free_lock",
    "is_used_lock",
})


def _clean_ident(name: Any) -> str:
    """Clean quotes and whitespace from identifier names."""
    if not name:
        return ""
    return str(name).strip().strip("`\"'[]")


def parse_sql(sql: str, dialect: str | None = None) -> dict[str, Any]:
    """Parse SQL query into structured AST components (tables, columns, is_destructive)."""
    if not sql or not sql.strip():
        return {"is_valid": False, "tables": [], "columns": []}
    try:
        ast = sqlglot.parse_one(sql, read=dialect)
        tables = [_clean_ident(t.name or t.this.sql()) for t in ast.find_all(exp.Table)]
        columns = [_clean_ident(c.name) for c in ast.find_all(exp.Column)]
        return {
            "is_valid": True,
            "ast": ast,
            "tables": tables,
            "columns": columns,
            "is_destructive": is_destructive_sql(sql, dialect=dialect),
        }
    except Exception as exc:
        return {"is_valid": False, "error": str(exc), "tables": [], "columns": []}


def is_destructive_sql(sql: str, dialect: str | None = None) -> bool:
    """Check whether a query contains destructive or write operations.

    Returns True if the statement modifies data/schema (INSERT, UPDATE, DELETE,
    DROP, TRUNCATE, ALTER, CREATE, GRANT, REVOKE) or contains stacked multi-statements.
    Returns False for safe, read-only queries (SELECT, UNION, etc.).
    """
    if not sql or not sql.strip():
        return True

    try:
        statements = [s for s in sqlglot.parse(sql, read=dialect) if s is not None]
    except Exception as exc:
        logger.warning("sqlglot failed to parse statement in is_destructive_sql: %s. Treating as destructive for safety.", exc)
        return True

    if len(statements) != 1:
        logger.warning("Blocked multi-statement or stacked SQL (%d statements).", len(statements))
        return True

    ast = statements[0]

    # Must be a Select or Union
    if not isinstance(ast, (exp.Select, exp.Union)):
        return True

    # Check for any embedded write/destructive expression
    for bad_type in DESTRUCTIVE_TYPES:
        if ast.find(bad_type):
            return True

    # Reject SELECT ... INTO OUTFILE / DUMPFILE / @var
    for sel_node in ast.find_all(exp.Select):
        if sel_node.args.get("into") is not None:
            return True

    # Reject dangerous functions (DoS / file read / execution)
    for anon in ast.find_all(exp.Anonymous):
        fname = str(anon.this or "").lower()
        if fname in DANGEROUS_FUNCTIONS:
            return True
    for func in ast.find_all(exp.Func):
        fname = func.sql_name() if hasattr(func, "sql_name") else getattr(func, "key", "")
        if isinstance(fname, str) and fname.lower() in DANGEROUS_FUNCTIONS:
            return True

    return False


def check_cartesian_explosion(sql: str, dialect: str | None = None) -> tuple[bool, str]:
    """Detect unbounded Cartesian products and implicit comma-joins across multiple tables.

    Returns:
        (True, reason) if query contains explicit CROSS JOIN or comma-separated tables without explicit ON/USING conditions.
        (False, "") if query has explicit ON/USING join predicates or is a single-table query.
    """
    if not sql or not sql.strip():
        return False, ""

    try:
        ast = sqlglot.parse_one(sql, read=dialect)
    except Exception as exc:
        logger.debug("Failed to parse SQL in check_cartesian_explosion: %s", exc)
        return False, ""

    for select in ast.find_all(exp.Select):
        # 1. Check for explicit CROSS JOIN or implicit comma-joins in JOIN clauses
        for join in select.args.get("joins") or []:
            kind = (join.args.get("kind") or "").upper()
            join_sql = join.sql().upper()
            if "CROSS" in kind or "CROSS JOIN" in join_sql:
                return True, "Explicit CROSS JOIN detected."

            on_clause = join.args.get("on")
            using_clause = join.args.get("using")
            if on_clause is None and using_clause is None:
                tbl_name = _clean_ident(join.this.name if hasattr(join.this, "name") else (join.this.alias or join.this.sql()))
                return (
                    True,
                    f"Implicit comma-join on table '{tbl_name}' detected without explicit ON condition (Cartesian risk).",
                )

        # 2. Comma-separated tables in FROM clause
        from_clause = select.args.get("from")
        if from_clause and from_clause.expressions:
            extra_count = len(from_clause.expressions)
            return (
                True,
                f"Implicit comma-join with {extra_count + 1} tables detected without explicit ON condition (Cartesian risk).",
            )

    return False, ""


def clamp_cartesian_limits(
    sql: str, max_cartesian_limit: int = 100, dialect: str | None = None
) -> tuple[str, bool]:
    """If Cartesian explosion risk is detected, clamp/override LIMIT to max_cartesian_limit.

    Returns:
        (clamped_sql, was_clamped)
    """
    is_cartesian, _ = check_cartesian_explosion(sql, dialect=dialect)
    if not is_cartesian:
        return sql, False

    try:
        ast = sqlglot.parse_one(sql, read=dialect)
        if isinstance(ast, (exp.Select, exp.Union)):
            existing = ast.args.get("limit")
            if existing is None:
                ast.set("limit", exp.Limit(expression=exp.Literal.number(max_cartesian_limit)))
                return ast.sql(dialect=dialect), True
            else:
                try:
                    curr_val = int(existing.expression.this)
                    if curr_val > max_cartesian_limit:
                        existing.set("expression", exp.Literal.number(max_cartesian_limit))
                        return ast.sql(dialect=dialect), True
                except (TypeError, ValueError, AttributeError):
                    pass
    except Exception as exc:
        logger.debug("Failed to clamp Cartesian limit: %s", exc)

    return sql, False


def check_dangerous_patterns(sql: str, dialect: str | None = None) -> list[str]:
    """Scan SQL for anti-patterns and performance hazards.

    Blocks/Flags:
    1. SELECT * (wildcard selections)
    2. CROSS JOIN / Multi-table comma-joins (unbounded Cartesian products)
    """
    if not sql or not sql.strip():
        return ["SQL statement is empty."]

    warnings: list[str] = []

    try:
        ast = sqlglot.parse_one(sql, read=dialect)
    except Exception as exc:
        logger.debug("Failed to parse SQL in check_dangerous_patterns: %s", exc)
        return warnings

    # 1. Flag SELECT * / exp.Star
    stars = list(ast.find_all(exp.Star))
    if stars:
        warnings.append(
            "Wildcard selection (SELECT *) is forbidden. Explicitly name the required columns."
        )

    # 2. Flag Cartesian explosion (explicit CROSS JOIN or comma-joins)
    is_cartesian, reason = check_cartesian_explosion(sql, dialect=dialect)
    if is_cartesian:
        warnings.append(
            f"Cartesian product detected: {reason} Use explicit INNER/LEFT JOIN with an ON condition."
        )

    return warnings


def _normalize_schema_context(schema_context: dict[str, Any] | list[Any] | str | None) -> dict[str, set[str]]:
    """Normalize various schema context representations into {table_lower: {col_lower}}."""
    if not schema_context:
        return {}

    normalized: dict[str, set[str]] = {}

    if isinstance(schema_context, dict):
        for tbl, cols in schema_context.items():
            tbl_clean = _clean_ident(tbl).lower()
            if isinstance(cols, (list, set, tuple)):
                normalized[tbl_clean] = {_clean_ident(c).lower() for c in cols if c}
            elif isinstance(cols, dict):
                normalized[tbl_clean] = {_clean_ident(c).lower() for c in cols.keys() if c}
            else:
                normalized[tbl_clean] = set()

    elif isinstance(schema_context, list):
        for item in schema_context:
            if isinstance(item, dict) and "table_name" in item:
                tbl_clean = _clean_ident(item["table_name"]).lower()
                normalized.setdefault(tbl_clean, set())
            elif isinstance(item, str):
                # Try parsing line like "table_name: col1(type), col2(type)"
                match = re.match(r"^([a-zA-Z0-9_]+)\s*:\s*(.*)$", item.strip())
                if match:
                    tname, col_str = match.groups()
                    t_clean = _clean_ident(tname).lower()
                    col_names = re.findall(r"\b([a-zA-Z0-9_]+)\s*\(", col_str)
                    normalized[t_clean] = {c.lower() for c in col_names}

    elif isinstance(schema_context, str):
        # Multi-line schema or DDL
        for line in schema_context.strip().split("\n"):
            match = re.match(r"^([a-zA-Z0-9_]+)\s*:\s*(.*)$", line.strip())
            if match:
                tname, col_str = match.groups()
                t_clean = _clean_ident(tname).lower()
                col_names = re.findall(r"\b([a-zA-Z0-9_]+)\s*\(", col_str)
                normalized[t_clean] = {c.lower() for c in col_names}

    return normalized


def validate_tables_and_columns(
    sql: str,
    schema_context: dict[str, Any] | list[Any] | str | None,
    dialect: str | None = None,
) -> tuple[bool, str]:
    """Validate table and column references in SQL AST against schema context.

    Returns:
        (True, "") if all tables and columns exist.
        (False, error_message) if any table or column is hallucinated or missing.
    """
    if not sql or not sql.strip():
        return False, "SQL query is empty."

    norm_schema = _normalize_schema_context(schema_context)
    if not norm_schema:
        # If no schema context provided, pass-through (Fail-Safe)
        return True, ""

    try:
        ast = sqlglot.parse_one(sql, read=dialect)
    except Exception as exc:
        return False, f"SQL syntax error: {exc}"

    # Extract CTEs (WITH clause) so CTE names and columns are not flagged as missing tables
    ctes: set[str] = set()
    for with_exp in ast.find_all(exp.With):
        for cte in with_exp.expressions:
            cte_alias = cte.alias or (cte.this.name if hasattr(cte.this, "name") else cte.this.sql())
            ctes.add(_clean_ident(cte_alias).lower())

    # Map table aliases: alias -> real_table
    table_alias_map: dict[str, str] = {}
    active_tables: set[str] = set()

    for tbl in ast.find_all(exp.Table):
        raw_name = _clean_ident(tbl.name or tbl.this.sql()).lower()
        if raw_name in ctes:
            continue
        tbl_alias = _clean_ident(tbl.alias or raw_name).lower()

        # Check table existence in schema
        if raw_name not in norm_schema:
            avail = sorted(norm_schema.keys())
            return False, f"Table '{raw_name}' does not exist in schema. Available tables: {avail}"

        table_alias_map[tbl_alias] = raw_name
        table_alias_map[raw_name] = raw_name
        active_tables.add(raw_name)

    # Extract projected column aliases in SELECT (e.g. SELECT c.name AS customer_name)
    projected_aliases: set[str] = set()
    for alias_expr in ast.find_all(exp.Alias):
        projected_aliases.add(_clean_ident(alias_expr.alias).lower())

    # Extract and validate columns
    for col in ast.find_all(exp.Column):
        col_name = _clean_ident(col.name).lower()
        tbl_qualifier = _clean_ident(col.table).lower()

        # Skip star wildcard expressions
        if col_name == "*" or isinstance(col.this, exp.Star):
            continue

        # If referenced in GROUP BY/ORDER BY matching a projected alias
        if not tbl_qualifier and col_name in projected_aliases:
            continue

        # If qualified: o.customer_id
        if tbl_qualifier:
            real_table = table_alias_map.get(tbl_qualifier)
            if real_table and real_table in norm_schema:
                allowed_cols = norm_schema[real_table]
                if allowed_cols and col_name not in allowed_cols:
                    return (
                        False,
                        f"Column '{col_name}' does not exist in table '{real_table}'. Available columns: {sorted(allowed_cols)}",
                    )
        else:
            # Unqualified column: must exist in at least one active table (or schema if no tables resolved)
            candidate_tables = active_tables if active_tables else set(norm_schema.keys())
            col_found = False
            for t in candidate_tables:
                if t in norm_schema and (not norm_schema[t] or col_name in norm_schema[t]):
                    col_found = True
                    break
            if not col_found:
                avail_tables_str = ", ".join(sorted(candidate_tables))
                return (
                    False,
                    f"Column '{col_name}' not found in any active table ({avail_tables_str}). Check spelling or qualify with table name.",
                )

    return True, ""


def validate_sql_safety(
    sql: str,
    schema_context: dict[str, Any] | list[Any] | str | None = None,
    dialect: str | None = None,
) -> tuple[bool, str]:
    """Execute complete safety checks: destructive command block, pattern scan, schema validation."""
    if is_destructive_sql(sql, dialect=dialect):
        return False, "Destructive or write SQL operation detected. Only read-only SELECT queries are allowed."

    dangerous_warnings = check_dangerous_patterns(sql, dialect=dialect)
    if dangerous_warnings:
        return False, "\n".join(dangerous_warnings)

    if schema_context:
        valid_schema, schema_err = validate_tables_and_columns(sql, schema_context, dialect=dialect)
        if not valid_schema:
            return False, schema_err

    return True, ""

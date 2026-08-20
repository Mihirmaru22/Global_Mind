"""Schema-Aware Column Registry — validates generated SQL against the real schema.

Built from the same schema text that `_get_schema()` already fetches, so no
extra DB round-trips.  Two validation passes:

1. **Column validation** — every column reference in the SQL is checked against
   the actual columns on the referenced table.  Hallucinated columns are caught
   before they hit the DB, producing a clear retry message ("Column 'x' does
   not exist on table 'y'. Available columns: a, b, c").

2. **Alias validation** — flags misleading aliases where the LLM copies a word
   from the user's question as a column alias even though the underlying
   expression resolves to something semantically different.  This prevents e.g.
   `product_type_id AS technology_used` when the user asked about "technology".
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

import sqlglot
from sqlglot import exp

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Result of validating a generated SQL query against the schema."""

    is_valid: bool
    errors: list[str] = field(default_factory=list)
    hallucinated_columns: list[str] = field(default_factory=list)


class ColumnRegistry:
    """Auto-built index of ``table → {columns}`` from the live schema text.

    Supports both SQLite (``CREATE TABLE`` statements) and MySQL
    (``information_schema.columns`` row format produced by
    ``format_schema_rows``).
    """

    def __init__(self, schema_text: str, dialect: str) -> None:
        self._dialect = dialect
        self._tables: dict[str, set[str]] = {}  # table_name → {col_name (lower)}
        self._tables_original: dict[str, list[str]] = {}  # for display
        self._parse_schema(schema_text)

    # ------------------------------------------------------------------
    # Schema parsing
    # ------------------------------------------------------------------

    def _parse_schema(self, text: str) -> None:
        """Extract table → column mappings from the schema text."""
        if self._dialect == "sqlite":
            self._parse_sqlite(text)
        elif self._dialect == "mysql":
            self._parse_mysql(text)
        else:
            logger.warning("ColumnRegistry: unsupported dialect %r", self._dialect)

    _CREATE_RE = re.compile(
        r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"
        r"[`\"']?(\w+)[`\"']?\s*\((.*?)\)(?:\s*;)?",
        re.IGNORECASE | re.DOTALL,
    )
    _COL_RE = re.compile(
        r"^\s*[`\"']?(\w+)[`\"']?\s+\w+",
        re.MULTILINE,
    )

    def _parse_sqlite(self, text: str) -> None:
        """Parse CREATE TABLE statements (SQLite's sqlite_master format)."""
        for match in self._CREATE_RE.finditer(text):
            table = match.group(1)
            body = match.group(2)
            cols: list[str] = []
            for line in body.split(","):
                line = line.strip()
                # Skip constraints (PRIMARY KEY, FOREIGN KEY, UNIQUE, CHECK)
                if re.match(
                    r"^\s*(PRIMARY\s+KEY|FOREIGN\s+KEY|UNIQUE|CHECK|CONSTRAINT)\b",
                    line,
                    re.IGNORECASE,
                ):
                    continue
                col_match = self._COL_RE.match(line)
                if col_match:
                    cols.append(col_match.group(1))
            if cols:
                self._tables[table.lower()] = {c.lower() for c in cols}
                self._tables_original[table.lower()] = cols

    _MYSQL_TABLE_RE = re.compile(
        r"^TABLE\s+(\w+)\s*\(",
        re.MULTILINE,
    )
    _MYSQL_COL_RE = re.compile(r"^\s+(\w+)\s+\w+", re.MULTILINE)

    def _parse_mysql(self, text: str) -> None:
        """Parse the TABLE name (\\n  col type, ...) format from format_schema_rows."""
        blocks = re.split(r"\n(?=TABLE\s)", text)
        for block in blocks:
            table_match = self._MYSQL_TABLE_RE.match(block)
            if not table_match:
                continue
            table = table_match.group(1)
            cols: list[str] = []
            for col_match in self._MYSQL_COL_RE.finditer(block):
                cols.append(col_match.group(1))
            if cols:
                self._tables[table.lower()] = {c.lower() for c in cols}
                self._tables_original[table.lower()] = cols

    # ------------------------------------------------------------------
    # Column validation
    # ------------------------------------------------------------------

    def validate_columns(self, sql: str) -> ValidationResult:
        """Check every column reference in the SQL against the schema.

        Returns a ValidationResult with specific error messages for any
        hallucinated columns, including the list of real columns available.
        """
        if not self._tables:
            # No schema loaded — skip validation rather than blocking everything.
            return ValidationResult(is_valid=True)

        try:
            ast = sqlglot.parse_one(sql, read=self._dialect)
        except Exception:
            # If it doesn't parse, _is_safe_read_query will catch it anyway.
            return ValidationResult(is_valid=True)

        # Build a map of alias → real table name from the query's FROM/JOIN.
        table_aliases = self._resolve_table_aliases(ast)
        
        # Collect all SELECT aliases (e.g., "SELECT x AS total" or "SUM(x) AS total")
        select_aliases = set()
        for select_expr in ast.find_all(exp.Alias):
            alias_name = (select_expr.alias or "").lower()
            if alias_name:
                select_aliases.add(alias_name)

        # SELECT aliases (e.g. SUM(qty) AS total_quantity) are legal in
        # ORDER BY / GROUP BY / HAVING under MySQL semantics -- never flag
        # an unqualified reference to one as a hallucinated column.
        select_aliases: set[str] = set()
        for _sel in ast.find_all(exp.Select):
            for _proj in _sel.expressions:
                _alias = _proj.args.get("alias")
                if _alias is not None:
                    select_aliases.add((_alias.name or "").lower())

        errors: list[str] = []
        hallucinated: list[str] = []

        for col_node in ast.find_all(exp.Column):
            col_name = (col_node.name or "").strip().lower()
            if not col_name:
                continue

            # Skip if this is a SELECT alias being referenced in ORDER BY/GROUP BY
            if col_name in select_aliases:
                continue

            # Resolve the table for this column.
            table_ref = col_node.table
            if table_ref:
                # Qualified: table.column or alias.column
                real_table = table_aliases.get(table_ref.lower(), table_ref.lower())
                known_cols = self._tables.get(real_table)
                if known_cols is not None and col_name.lower() not in known_cols:
                    display_cols = self._tables_original.get(real_table, sorted(known_cols))
                    # Show a useful subset, not hundreds of columns.
                    shown = display_cols[:20]
                    suffix = f" (+{len(display_cols) - 20} more)" if len(display_cols) > 20 else ""
                    errors.append(
                        f"Column '{col_name}' does not exist on table '{real_table}'. "
                        f"Available columns: {', '.join(shown)}{suffix}"
                    )
                    hallucinated.append(f"{real_table}.{col_name}")
            else:
                if col_name.lower() in select_aliases:
                    continue
                # Unqualified: check against all tables in the query's FROM/JOIN.
                from_tables = set(table_aliases.values())
                if from_tables:
                    found_in_any = any(
                        col_name.lower() in (self._tables.get(t) or set())
                        for t in from_tables
                    )
                    if not found_in_any:
                        # In SQLite, double-quoted non-column tokens (e.g. WHERE status = "completed")
                        # are evaluated as string literals by SQLite's legacy fallback ONLY when
                        # compared against a known, valid column. A double-quoted token in a projection
                        # (SELECT "fake" FROM t) or compared against a non-column (WHERE "fake" = 1)
                        # remains a hallucinated column.
                        if self._dialect == "sqlite" and self._is_sqlite_literal_fallback(col_node, from_tables, table_aliases):
                            continue

                        table_list = ", ".join(sorted(from_tables))
                        errors.append(
                            f"Column '{col_name}' not found in any of the query's tables "
                            f"({table_list}). Check spelling or qualify with table name."
                        )
                        hallucinated.append(col_name)

        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            hallucinated_columns=hallucinated,
        )

    def _is_sqlite_literal_fallback(
        self,
        col_node: exp.Column,
        from_tables: set[str],
        table_aliases: dict[str, str],
    ) -> bool:
        """Return True only if col_node is a double-quoted string literal compared against a real column."""
        if not getattr(col_node.this, "quoted", False):
            return False
        if col_node.table:
            return False

        def _is_known_col(node: Any) -> bool:
            if not isinstance(node, exp.Column):
                return False
            t_ref = node.table
            c_name = (node.name or "").lower()
            if t_ref:
                real_t = table_aliases.get(t_ref.lower(), t_ref.lower())
                return c_name in (self._tables.get(real_t) or set())
            return any(c_name in (self._tables.get(t) or set()) for t in from_tables)

        parent = col_node.parent
        if isinstance(parent, (exp.Binary, exp.Predicate, exp.Like, exp.ILike)):
            other = parent.expression if col_node is parent.this else getattr(parent, "this", None)
            return _is_known_col(other)
        elif isinstance(parent, exp.In):
            if col_node is not parent.this:
                return _is_known_col(parent.this)
        return False

    def _resolve_table_aliases(self, ast: exp.Expression) -> dict[str, str]:
        """Build alias → real_table_name mapping from the query's FROM/JOIN."""
        aliases: dict[str, str] = {}
        for table_node in ast.find_all(exp.Table):
            real_name = (table_node.name or "").lower()
            alias = table_node.alias
            if alias:
                aliases[alias.lower()] = real_name
            if real_name:
                aliases[real_name] = real_name
        return aliases

    # ------------------------------------------------------------------
    # Alias validation
    # ------------------------------------------------------------------

    # Words too common to flag as "copied from the question".
    _STOP_WORDS = frozenset({
        "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "shall",
        "should", "may", "might", "must", "can", "could", "of", "in", "to",
        "for", "with", "on", "at", "from", "by", "as", "into", "through",
        "and", "or", "but", "not", "no", "all", "each", "every", "both",
        "how", "what", "which", "who", "whom", "this", "that", "these",
        "those", "my", "our", "your", "its", "their", "total", "count",
        "sum", "average", "max", "min", "many", "much", "most", "least",
        "top", "bottom", "first", "last", "per", "by", "show", "list",
        "get", "find", "give", "me", "us", "we", "i",
    })

    def validate_aliases(self, sql: str, question: str) -> list[str]:
        """Flag aliases that appear to be copied from the question rather than
        derived from what the column actually contains.

        Only flags when ALL of:
        1. The alias text is NOT a real column name anywhere in the schema.
        2. A significant word in the alias appears in the question.
        3. The underlying column's real name is semantically different.
        """
        try:
            ast = sqlglot.parse_one(sql, read=self._dialect)
        except Exception:
            return []

        # All known column names across the entire schema (lower).
        all_columns = set()
        for cols in self._tables.values():
            all_columns.update(cols)

        question_words = {
            w.lower()
            for w in re.findall(r"\w+", question)
            if w.lower() not in self._STOP_WORDS and len(w) > 2
        }

        warnings: list[str] = []
        for alias_node in ast.find_all(exp.Alias):
            alias_name = alias_node.alias
            if not alias_name or not isinstance(alias_name, str):
                continue

            alias_lower = alias_name.lower()

            # Skip if the alias IS a real column name — it's descriptive by definition.
            if alias_lower in all_columns:
                continue

            # Check if the alias overlaps with question words.
            # Split on non-alpha (incl. underscores) so compound aliases like
            # "technology_used" match question words "technology" and "used".
            alias_words = {
                w.lower()
                for w in re.split(r"[^a-zA-Z]+", alias_name)
                if w.lower() not in self._STOP_WORDS and len(w) > 2
            }
            overlap = alias_words & question_words
            if not overlap:
                continue

            # Get the underlying expression's column name.
            child = alias_node.this
            underlying = ""
            if isinstance(child, exp.Column):
                underlying = child.name or ""
            elif isinstance(child, (exp.Sum, exp.Count, exp.Max, exp.Min, exp.Avg)):
                # Aggregate — underlying is the aggregated column.
                inner = child.this
                if isinstance(inner, exp.Column):
                    underlying = inner.name or ""
                elif isinstance(child, exp.Count):
                    underlying = "count"

            if not underlying:
                continue

            # If the underlying column name is very different from the alias,
            # and the alias looks like it was lifted from the question — flag it.
            underlying_words = {
                w.lower()
                for w in re.split(r"[^a-zA-Z]+", underlying)
                if len(w) > 2
            }
            if alias_words & underlying_words:
                continue

            # Allow legitimate financial, volume, production, and entity metric aliases
            _METRIC_WORDS = frozenset({
                "revenue", "sales", "amount", "total", "spent", "cost", "value",
                "turnover", "price", "count", "quantity", "qty", "sum", "avg",
                "quoted", "billed", "invoiced", "order", "orders", "deal", "deals",
                "lead", "leads", "inquiry", "inquiries", "successful", "converted",
                "rejected", "active", "pending", "client", "clients", "customer",
                "customers", "party", "parties", "batch", "batches", "carton", "cartons",
                "apq", "production", "product", "produced", "finished", "completed",
                "output", "target", "planned", "actual", "challan", "dispatch",
                "dispatched", "delivered", "delivery", "stock", "inventory",
                "available", "onhand", "balance", "moq",
            })
            if (alias_words & _METRIC_WORDS) and (underlying_words & _METRIC_WORDS or underlying in ("id", "apq", "qty")):
                continue

            warnings.append(
                f"Alias '{alias_name}' on column '{underlying}' appears derived "
                f"from the question, not the data. Use a descriptive alias based "
                f"on the actual column (e.g. '{underlying}' or "
                f"'{underlying.replace('_id', '_name')}')."
            )

        return warnings

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

import json
import logging
from pathlib import Path
import re
from dataclasses import dataclass, field
from typing import Any

import sqlglot
from sqlglot import exp

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
GLOSSARY_PATH = REPO_ROOT / "config" / "sql_glossary.json"
COLUMN_GLOSSARY_PATH = REPO_ROOT / "config" / "sql_column_glossary.json"

_CACHED_GLOSSARY: set[str] | None = None

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
    "available", "onhand", "balance", "moq", "status", "id", "date",
    "created_at", "updated_at", "deleted_at", "month", "year", "quarter",
    "rank", "row_num", "rn", "num", "min", "max", "diff", "rate", "margin",
    "profit", "tax", "gst", "subtotal", "grand_total", "discount",
    "no", "pct", "percent", "percentage", "share", "ratio",
    "name", "type", "code", "desc", "description", "category",
    "day", "week", "time", "hour", "flag", "val", "weight", "net", "gross",
    "user", "users", "vendor", "employee", "limit", "credit",
    "debit", "opening", "closing", "so", "po", "dc", "churn",
    "unit", "line", "item", "seq", "level", "state", "city", "country",
    "note", "notes", "remark", "remarks", "is", "has", "can",
})


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
        
        # Check for CTE table shadowing and extract CTE projections
        errors: list[str] = []
        hallucinated: list[str] = []
        cte_projected: dict[str, set[str]] = {}

        # Collect all known schema columns across all tables for CTE projection validation
        all_schema_columns: set[str] = set()
        for cols in self._tables.values():
            all_schema_columns.update(cols)

        for with_node in ast.find_all(exp.With):
            for cte in with_node.expressions:
                cte_name = (cte.alias or (cte.this.name if hasattr(cte.this, "name") else cte.this.sql())).lower().strip("`\"'[]")
                if cte_name in self._tables:
                    errors.append(
                        f"CTE table shadowing: CTE '{cte_name}' shadows physical table '{cte_name}' in schema."
                    )
                    return ValidationResult(
                        is_valid=False,
                        errors=errors,
                        hallucinated_columns=[f"{cte_name}.*"],
                    )

                # Check physical tables referenced inside CTE
                for t_node in cte.find_all(exp.Table):
                    t_name = (t_node.name or "").lower().strip("`\"'[]")
                    if t_name and t_name not in self._tables and t_name not in cte_projected:
                        errors.append(
                            f"Table '{t_name}' referenced in CTE '{cte_name}' does not exist in schema."
                        )
                        hallucinated.append(t_name)

                # Extract and validate columns projected by this CTE
                cols = set()
                for sel in cte.find_all(exp.Select):
                    for proj in sel.expressions:
                        proj_col = ""
                        if isinstance(proj, exp.Alias):
                            proj_col = (proj.alias or "").lower().strip("`\"'[]")
                        elif isinstance(proj, exp.Column):
                            proj_col = (proj.name or "").lower().strip("`\"'[]")
                        elif hasattr(proj, "name") and proj.name:
                            proj_col = str(proj.name).lower().strip("`\"'[]")
                        elif isinstance(proj, exp.Star) or (isinstance(proj, exp.Column) and isinstance(proj.this, exp.Star)):
                            for t_node in sel.find_all(exp.Table):
                                t_name = (t_node.name or "").lower().strip("`\"'[]")
                                if t_name in self._tables:
                                    cols.update(self._tables[t_name])

                        has_from = bool(list(sel.find_all(exp.Table)))
                        should_check_projection = isinstance(proj, exp.Alias) or not has_from
                        if proj_col and proj_col != "*":
                            if should_check_projection and not self._is_allowed_cte_column_concept(proj_col, all_schema_columns):
                                errors.append(
                                    f"CTE '{cte_name}' defines hallucinated/unrecognized column '{proj_col}'. "
                                    f"CTE projected columns must match schema columns or glossary concepts."
                                )
                                hallucinated.append(f"{cte_name}.{proj_col}")
                            cols.add(proj_col)
                cte_projected[cte_name] = cols

        # Collect all SELECT & projected aliases (e.g. "SELECT x AS total" or "SUM(x) AS total")
        # These are legal in ORDER BY / GROUP BY / HAVING under SQL semantics.
        select_aliases: set[str] = set()
        for alias_node in ast.find_all(exp.Alias):
            name = (alias_node.alias or alias_node.name or "").strip().lower()
            if name:
                select_aliases.add(name)

        for col_node in ast.find_all(exp.Column):
            col_name = (col_node.name or "").strip().lower()
            if not col_name:
                continue

            # Skip if this is a SELECT alias being referenced in ORDER BY/GROUP BY
            if col_name in select_aliases:
                continue

            table_ref = col_node.table

            # If column is inside a CTE definition, validate strictly against tables within that CTE
            enclosing_cte = col_node.find_ancestor(exp.CTE)
            if enclosing_cte:
                cte_table_aliases: dict[str, str] = {}
                for t_node in enclosing_cte.find_all(exp.Table):
                    r_name = (t_node.name or "").lower()
                    if t_node.alias:
                        cte_table_aliases[t_node.alias.lower()] = r_name
                    if r_name:
                        cte_table_aliases[r_name] = r_name

                if table_ref:
                    real_table = cte_table_aliases.get(table_ref.lower(), table_ref.lower())
                    known_cols = self._tables.get(real_table)
                    if known_cols is not None and col_name.lower() not in known_cols:
                        display_cols = self._tables_original.get(real_table, sorted(known_cols))
                        shown = display_cols[:20]
                        suffix = f" (+{len(display_cols) - 20} more)" if len(display_cols) > 20 else ""
                        errors.append(
                            f"Column '{col_name}' does not exist on table '{real_table}'. "
                            f"Available columns: {', '.join(shown)}{suffix}"
                        )
                        hallucinated.append(col_name)
                else:
                    cte_from_tables = set(cte_table_aliases.values())
                    if cte_from_tables:
                        found_in_any = any(
                            col_name.lower() in (self._tables.get(t) or set())
                            for t in cte_from_tables
                        )
                        if not found_in_any:
                            table_list = ", ".join(sorted(cte_from_tables))
                            errors.append(
                                f"Column '{col_name}' not found in any of the query's tables "
                                f"({table_list}). Check spelling or qualify with table name."
                            )
                            hallucinated.append(col_name)
                continue

            # Outer query column validation
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
                elif real_table in cte_projected:
                    known_cte_cols = cte_projected[real_table]
                    if known_cte_cols and col_name.lower() not in known_cte_cols:
                        errors.append(
                            f"Column '{col_name}' does not exist on CTE '{real_table}'. "
                            f"Available CTE columns: {', '.join(sorted(known_cte_cols))}"
                        )
                        hallucinated.append(f"{real_table}.{col_name}")
            else:
                if col_name.lower() in select_aliases:
                    continue
                # Unqualified: check against all tables in the outer query's FROM/JOIN and CTEs.
                from_tables = set(table_aliases.values())
                if from_tables:
                    found_in_any = any(
                        col_name.lower() in (self._tables.get(t) or set())
                        for t in from_tables
                    ) or any(
                        col_name.lower() in (cte_projected.get(t) or set())
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

    @classmethod
    def _get_glossary_concepts(cls) -> set[str]:
        """Load and cache allowed glossary concepts, synonyms, and business terms."""
        global _CACHED_GLOSSARY
        if _CACHED_GLOSSARY is not None:
            return _CACHED_GLOSSARY

        concepts: set[str] = set()
        if GLOSSARY_PATH.exists():
            try:
                data = json.loads(GLOSSARY_PATH.read_text(encoding="utf-8"))
                for key, syns in data.items():
                    concepts.add(key.lower())
                    for token in re.split(r"[^a-zA-Z0-9]+", key.lower()):
                        if token:
                            concepts.add(token)
                    if isinstance(syns, list):
                        for s in syns:
                            s_clean = str(s).strip().lower()
                            concepts.add(s_clean)
                            for token in re.split(r"[^a-zA-Z0-9]+", s_clean):
                                if token:
                                    concepts.add(token)
            except Exception as exc:
                logger.debug("Failed to load sql_glossary.json: %s", exc)

        if COLUMN_GLOSSARY_PATH.exists():
            try:
                col_data = json.loads(COLUMN_GLOSSARY_PATH.read_text(encoding="utf-8"))
                for term in col_data.keys():
                    concepts.add(term.lower())
                    for token in re.split(r"[^a-zA-Z0-9]+", term.lower()):
                        if token:
                            concepts.add(token)
            except Exception as exc:
                logger.debug("Failed to load sql_column_glossary.json: %s", exc)

        _CACHED_GLOSSARY = concepts
        return _CACHED_GLOSSARY

    def _is_allowed_cte_column_concept(self, col_name: str, all_schema_cols: set[str]) -> bool:
        """Check whether a projected CTE column matches schema columns, glossary concepts, or allowed metric patterns."""
        clean_col = col_name.lower().strip("`\"'[]")
        if not clean_col or clean_col == "*":
            return True

        if clean_col in all_schema_cols:
            return True

        if clean_col in _METRIC_WORDS:
            return True

        glossary = self._get_glossary_concepts()
        if clean_col in glossary:
            return True

        tokens = [t for t in re.split(r"[^a-zA-Z0-9]+", clean_col) if t]
        if not tokens:
            return False

        for token in tokens:
            if token.isdigit():
                continue
            if (
                token in _METRIC_WORDS
                or token in glossary
                or token in all_schema_cols
                or any(token in c for c in all_schema_cols if len(token) > 2)
            ):
                continue
            return False

        return True

    def _resolve_table_aliases(self, ast: exp.Expression) -> dict[str, str]:
        """Build alias → real_table_name mapping from the query's FROM/JOIN and CTEs."""
        aliases: dict[str, str] = {}
        for table_node in ast.find_all(exp.Table):
            real_name = (table_node.name or "").lower()
            alias = table_node.alias
            if alias:
                aliases[alias.lower()] = real_name
            if real_name:
                aliases[real_name] = real_name
        for cte_node in ast.find_all(exp.CTE):
            cte_alias = (cte_node.alias or "").lower()
            if cte_alias:
                aliases[cte_alias] = cte_alias
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
            if (alias_words & _METRIC_WORDS) and (underlying_words & _METRIC_WORDS or underlying in ("id", "apq", "qty")):
                continue

            warnings.append(
                f"Alias '{alias_name}' on column '{underlying}' appears derived "
                f"from the question, not the data. Use a descriptive alias based "
                f"on the actual column (e.g. '{underlying}' or "
                f"'{underlying.replace('_id', '_name')}')."
            )

        return warnings

"""Schema Compaction and DDL Stripping Engine using sqlglot AST parsing.

Transforms verbose raw DDLs into dense, LLM-optimized semantic representations,
stripping non-essential audit columns while preserving Primary Keys, Foreign Keys,
and Join Hints.
"""

from __future__ import annotations

import logging
from typing import Any

import sqlglot
from sqlglot import exp

logger = logging.getLogger(__name__)

# Non-essential audit and metadata columns to drop aggressively
AUDIT_COLUMNS = frozenset({
    "created_at",
    "updated_at",
    "deleted_at",
    "restored_at",
    "created_by",
    "updated_by",
    "deleted_by",
    "created_id",
    "updated_id",
    "deleted_id",
    "restore_id",
    "creation_time",
    "modification_time",
    "last_modified",
    "created_date",
    "updated_date",
    "deleted_date",
})


def _clean_identifier(name: Any) -> str:
    """Strip quotes and whitespace from identifiers."""
    if not name:
        return ""
    return str(name).strip().strip("`\"'[]")


def _simplify_data_type(type_str: str) -> str:
    """Normalize and simplify verbose SQL types into compact representations."""
    if not type_str:
        return "text"
    t = type_str.lower().strip()
    if any(k in t for k in ["int", "serial", "bigint", "smallint", "tinyint"]):
        return "int"
    if any(k in t for k in ["decimal", "numeric", "float", "double", "real"]):
        return "decimal"
    if "bool" in t:
        return "bool"
    if any(k in t for k in ["timestamp", "datetime", "date", "time"]):
        return "datetime"
    if any(k in t for k in ["varchar", "char", "text", "string", "clob"]):
        return "varchar"
    if "json" in t:
        return "json"
    return t.split("(")[0]


def compact_ddl(ddl: str, dialect: str | None = None) -> str:
    """Parse DDL, strip audit columns and constraints, and return a dense format.

    Format per table:
        table_name: col1(type, PK), col2(type, FK->target.id), col3(type)

    Falls back to original DDL on parse failure.
    """
    if not ddl or not ddl.strip():
        return ""

    raw_ddl = ddl.strip()

    try:
        parsed_expressions = sqlglot.parse(raw_ddl, read=dialect)
    except Exception as exc:
        logger.debug("sqlglot.parse failed with dialect '%s': %s. Retrying with default dialect.", dialect, exc)
        try:
            parsed_expressions = sqlglot.parse(raw_ddl)
        except Exception as exc2:
            logger.warning("sqlglot could not parse DDL: %s. Falling back to raw DDL.", exc2)
            return raw_ddl

    if not parsed_expressions:
        return raw_ddl

    compact_tables: list[str] = []

    for expr in parsed_expressions:
        if expr is None:
            continue

        schema = expr.this if isinstance(expr, exp.Create) else expr
        if not isinstance(schema, exp.Schema):
            schema = expr.find(exp.Schema)
        if not schema or not hasattr(schema, "this"):
            continue

        table_raw_name = schema.this.name if hasattr(schema.this, "name") else schema.this.sql()
        table_name = _clean_identifier(table_raw_name)
        if not table_name:
            continue

        pk_cols: set[str] = set()
        fk_map: dict[str, tuple[str, str]] = {}
        columns: list[tuple[str, str]] = []

        # 1. Parse expressions in Schema
        for item in schema.expressions:
            if isinstance(item, exp.ColumnDef):
                col_raw = item.this.name if hasattr(item.this, "name") else item.this.sql()
                col_name = _clean_identifier(col_raw)
                col_type = _simplify_data_type(item.kind.sql() if item.kind else "text")

                for constr in item.constraints:
                    c_kind = constr.kind
                    if isinstance(c_kind, exp.PrimaryKeyColumnConstraint) or "PRIMARY KEY" in constr.sql().upper():
                        pk_cols.add(col_name.lower())
                    if isinstance(c_kind, exp.Reference):
                        ref = c_kind
                        if isinstance(ref.this, exp.Schema):
                            ref_tbl = _clean_identifier(ref.this.this.name or ref.this.this.sql())
                            ref_cols = [_clean_identifier(e.name if hasattr(e, "name") else e.sql()) for e in ref.this.expressions]
                        else:
                            ref_tbl = _clean_identifier(ref.this.name if hasattr(ref.this, "name") else ref.this.sql())
                            ref_cols = [_clean_identifier(e.name if hasattr(e, "name") else e.sql()) for e in ref.expressions]
                        fk_map[col_name.lower()] = (ref_tbl, ref_cols[0] if ref_cols else "id")

                columns.append((col_name, col_type))

            elif isinstance(item, (exp.Constraint, exp.ForeignKey)):
                sql_upper = item.sql().upper()
                if "PRIMARY KEY" in sql_upper:
                    for col_expr in item.find_all(exp.Column):
                        pk_cols.add(_clean_identifier(col_expr.name or col_expr.sql()).lower())

                ref = item.find(exp.Reference)
                fk = item.find(exp.ForeignKey)
                if ref:
                    if isinstance(ref.this, exp.Schema):
                        ref_tbl = _clean_identifier(ref.this.this.name or ref.this.this.sql())
                        ref_cols = [_clean_identifier(e.name if hasattr(e, "name") else e.sql()) for e in ref.this.expressions]
                    else:
                        ref_tbl = _clean_identifier(ref.this.name if hasattr(ref.this, "name") else ref.this.sql())
                        ref_cols = [_clean_identifier(e.name if hasattr(e, "name") else e.sql()) for e in ref.expressions]

                    target_col = ref_cols[0] if ref_cols else "id"
                    local_cols: list[str] = []
                    if fk:
                        local_cols = [_clean_identifier(e.name if hasattr(e, "name") else e.sql()) for e in fk.expressions]
                    elif isinstance(item, exp.Constraint) and item.expressions:
                        for sub in item.expressions:
                            if isinstance(sub, exp.ForeignKey):
                                local_cols = [_clean_identifier(c.name if hasattr(c, "name") else c.sql()) for c in sub.expressions]
                    if not local_cols:
                        for c in item.find_all(exp.Column):
                            c_clean = _clean_identifier(c.name or c.sql())
                            if c_clean != ref_tbl and c_clean not in ref_cols:
                                local_cols.append(c_clean)
                    for lc in local_cols:
                        fk_map[lc.lower()] = (ref_tbl, target_col)

        # 2. Filter and format columns
        formatted_cols: list[str] = []
        for col_name, col_type in columns:
            col_lower = col_name.lower()
            is_pk = col_lower in pk_cols
            is_fk = col_lower in fk_map

            # Strip non-essential audit columns unless PK or FK
            if col_lower in AUDIT_COLUMNS and not is_pk and not is_fk:
                continue

            markers: list[str] = []
            if is_pk:
                markers.append("PK")
            if is_fk:
                target_t, target_c = fk_map[col_lower]
                markers.append(f"FK->{target_t}.{target_c}")

            marker_str = f", {', '.join(markers)}" if markers else ""
            formatted_cols.append(f"{col_name}({col_type}{marker_str})")

        if formatted_cols:
            compact_tables.append(f"{table_name}: {', '.join(formatted_cols)}")
        else:
            compact_tables.append(f"{table_name}: (no columns)")

    if not compact_tables:
        return raw_ddl

    return "\n".join(compact_tables)


def extract_join_hints(ddls: list[str], dialect: str | None = None) -> str:
    """Scan candidate DDLs for explicit FOREIGN KEY constraints and output a compact join hint block.

    Example output:
    Join Hints:
    - orders.user_id -> users.id
    - orders.region_id -> regions.id
    """
    if not ddls:
        return ""

    hints: list[str] = []
    seen: set[str] = set()

    for ddl in ddls:
        if not ddl or not ddl.strip():
            continue
        try:
            parsed = sqlglot.parse(ddl, read=dialect)
        except Exception:
            try:
                parsed = sqlglot.parse(ddl)
            except Exception:
                continue

        for expr in parsed:
            if expr is None:
                continue
            schema = expr.this if isinstance(expr, exp.Create) else expr
            if not isinstance(schema, exp.Schema):
                schema = expr.find(exp.Schema)
            if not schema or not hasattr(schema, "this"):
                continue

            tbl_name = _clean_identifier(schema.this.name if hasattr(schema.this, "name") else schema.this.sql())
            if not tbl_name:
                continue

            for item in schema.expressions:
                if isinstance(item, exp.ColumnDef):
                    col_name = _clean_identifier(item.this.name if hasattr(item.this, "name") else item.this.sql())
                    for constr in item.constraints:
                        if isinstance(constr.kind, exp.Reference):
                            ref = constr.kind
                            if isinstance(ref.this, exp.Schema):
                                ref_tbl = _clean_identifier(ref.this.this.name or ref.this.this.sql())
                                ref_cols = [_clean_identifier(e.name if hasattr(e, "name") else e.sql()) for e in ref.this.expressions]
                            else:
                                ref_tbl = _clean_identifier(ref.this.name if hasattr(ref.this, "name") else ref.this.sql())
                                ref_cols = [_clean_identifier(e.name if hasattr(e, "name") else e.sql()) for e in ref.expressions]
                            ref_col = ref_cols[0] if ref_cols else "id"
                            hint = f"- {tbl_name}.{col_name} -> {ref_tbl}.{ref_col}"
                            if hint not in seen:
                                seen.add(hint)
                                hints.append(hint)

                elif isinstance(item, (exp.Constraint, exp.ForeignKey)):
                    ref = item.find(exp.Reference)
                    fk = item.find(exp.ForeignKey)
                    if ref:
                        if isinstance(ref.this, exp.Schema):
                            ref_tbl = _clean_identifier(ref.this.this.name or ref.this.this.sql())
                            ref_cols = [_clean_identifier(e.name or e.sql()) for e in ref.this.expressions]
                        else:
                            ref_tbl = _clean_identifier(ref.this.name or ref.this.sql())
                            ref_cols = [_clean_identifier(e.name or e.sql()) for e in ref.expressions]
                        ref_col = ref_cols[0] if ref_cols else "id"
                        local_cols: list[str] = []
                        if fk:
                            local_cols = [_clean_identifier(e.name if hasattr(e, "name") else e.sql()) for e in fk.expressions]
                        elif isinstance(item, exp.Constraint) and item.expressions:
                            for sub in item.expressions:
                                if isinstance(sub, exp.ForeignKey):
                                    local_cols = [_clean_identifier(c.name if hasattr(c, "name") else c.sql()) for c in sub.expressions]
                        for lc in local_cols:
                            hint = f"- {tbl_name}.{lc} -> {ref_tbl}.{ref_col}"
                            if hint not in seen:
                                seen.add(hint)
                                hints.append(hint)

    if not hints:
        return ""

    return "Join Hints:\n" + "\n".join(hints)

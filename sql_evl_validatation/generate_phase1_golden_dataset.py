#!/usr/bin/env python3
"""
GlobalMind SQL Pipeline - Phase 1 Golden Dataset Generator

This script generates a fixed 1000-query benchmark for alpha evaluation.

Privacy model:
- The LLM will only see the question + schema metadata.
- The LLM will never see DB rows or query result rows.
- Sensitive queries are generated first, but tagged with post_prune_tags.

Outputs:
- phase1_golden_dataset.json
- phase1_golden_dataset.jsonl
"""

import json
from collections import Counter
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
SCHEMA_FILE = BASE_DIR / "globalmind_schema.json"
OUTPUT_JSON = BASE_DIR / "phase1_golden_dataset.json"
OUTPUT_JSONL = BASE_DIR / "phase1_golden_dataset.jsonl"

TARGET_TOTAL = 1000

SENSITIVE_TABLES = {
    "users",
    "personal_access_tokens",
    "password_resets",
    "roles",
    "permissions",
    "model_has_roles",
    "model_has_permissions",
    "role_has_permissions",
    "failed_jobs",
}

SENSITIVE_COLUMN_NAMES = {
    "password",
    "remember_token",
    "token",
    "payload",
    "exception",
    "bank_account_no",
    "ifsc_code",
    "pan_no",
    "gst_no",
    "mobile",
    "mobile1",
    "mobile2",
    "mobile3",
    "email",
}

BUSINESS_DOMAINS = {
    "Master Data",
    "Party & CRM",
    "Sales",
    "Purchase",
    "Production",
    "Packaging & Stock",
}

GROUP_DIMENSIONS = [
    "status",
    "financial_id",
    "party_id",
    "product_id",
    "category_id",
    "lead_id",
    "sales_order_id",
    "dc_id",
    "quotation_id",
    "pi_id",
    "machine_id",
    "warehouse_id",
    "unit_id",
    "product_color_id",
    "product_batch_id",
    "stock_type",
    "transaction_type",
    "lead_generate_from",
    "profile_type",
    "current_year",
    "carton_verify_status",
    "delivery_type",
    "balance_type",
]

KPI_DIMENSIONS = [
    "financial_id",
    "party_id",
    "product_id",
    "category_id",
    "lead_id",
    "sales_order_id",
    "dc_id",
    "quotation_id",
    "pi_id",
    "machine_id",
    "warehouse_id",
    "unit_id",
    "product_color_id",
    "product_batch_id",
    "so_id",
]

METRIC_COLUMNS = [
    "qty",
    "total",
    "grand_total",
    "final_amount",
    "total_amount",
    "opening_balance",
    "credit_limit",
    "rate",
    "gst_amount",
    "apq",
    "box_qty",
    "total_qty",
    "price_pcs",
    "opening_stock",
    "packing_qty_count",
    "no_of_box",
    "per_carton_qty",
    "dc_order_qty",
    "order_qty",
    "minimum_stock",
]

VARCHAR_NUMERIC_COLUMNS = {
    "qty",
    "packed_qty",
    "color_qty",
}

KNOWN_ENUM_FILTERS = [
    ("lead", "status", "Open"),
    ("lead", "status", "FollowUp"),
    ("lead", "status", "Pending"),
    ("lead", "status", "In-Progress"),
    ("lead", "status", "Success"),
    ("lead", "status", "Reject"),
    ("party", "status", "Y"),
    ("party", "profile_type", "Party"),
    ("party", "profile_type", "Company"),
    ("financial_year", "current_year", "Y"),
    ("stock", "stock_type", "PI"),
    ("stock", "stock_type", "ProductOs"),
    ("stock", "stock_type", "DC"),
    ("stock", "stock_type", "Packaging"),
    ("stock", "stock_type", "StockAdjustment"),
    ("stock", "carton_verify_status", "P"),
    ("stock", "carton_verify_status", "V"),
    ("stock_adjustment", "transaction_type", "StockIn"),
    ("stock_adjustment", "transaction_type", "StockOut"),
    ("packagings", "carton_verify_status", "P"),
    ("packagings", "carton_verify_status", "V"),
    ("packagings", "status", "D"),
    ("packagings", "status", "B"),
    ("packaging_products", "status", "D"),
    ("product_opening_stock", "status", "D"),
    ("lead_product_sample_detail", "delivery_type", "Courier"),
    ("lead_product_sample_detail", "delivery_type", "Transport"),
    ("party_opening_balance", "balance_type", "Credit"),
    ("party_opening_balance", "balance_type", "Debit"),
]

TYPE_MISMATCH_JOINS = [
    ("quotation", "party_id", "party", "id"),
    ("proforma", "party_id", "party", "id"),
    ("quotation_products", "product_id", "product", "id"),
    ("proforma_products", "product_id", "product", "id"),
    ("quotation_products", "category_id", "category", "id"),
    ("proforma_products", "category_id", "category", "id"),
    ("quotation_products", "product_color_id", "product_color", "id"),
    ("proforma_products", "product_color_id", "product_color", "id"),
]


def strip_ws(obj):
    """
    The uploaded schema may contain keys/values with accidental spaces.
    This normalizes dictionary keys and string values.
    """
    if isinstance(obj, dict):
        return {str(k).strip(): strip_ws(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [strip_ws(item) for item in obj]
    if isinstance(obj, str):
        return " ".join(obj.strip().split())
    return obj


def q(name):
    """Quote a SQL identifier."""
    return f"`{name}`"


def load_schema():
    raw = json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))
    return strip_ws(raw)


def make_case(
    suite,
    difficulty,
    domain,
    question,
    sql,
    expected_tables,
    post_prune_tags,
    expected_outcome,
    notes,
):
    return {
        "id": None,
        "suite": suite,
        "domain": domain,
        "difficulty": difficulty,
        "question": question,
        "sql": sql,
        "expected_tables": expected_tables,
        "expected_outcome": expected_outcome,
        "golden_result_hash": None,
        "post_prune_tags": sorted(set(post_prune_tags or [])),
        "notes": notes,
    }


def normalize_sql(sql):
    return " ".join(sql.lower().strip().split())


def unique_cases(cases):
    seen = set()
    out = []
    for case in cases:
        key = normalize_sql(case["sql"])
        if key not in seen:
            seen.add(key)
            out.append(case)
    return out


def get_table_map(schema):
    tables = schema.get("tables", [])
    table_map = {}
    for table in tables:
        name = table.get("name")
        if name:
            table_map[name] = table
    return table_map


def column_names(table):
    return [
        c.get("name")
        for c in table.get("columns", [])
        if c.get("name")
    ]


def has_column(table, col_name):
    return col_name in column_names(table)


def get_column(table, col_name):
    for col in table.get("columns", []):
        if col.get("name") == col_name:
            return col
    return None


def primary_key_or_first_column(table):
    pk = table.get("primary_key") or []
    if pk:
        return pk[0]
    cols = column_names(table)
    return cols[0] if cols else None


def is_numeric_type(col):
    ctype = (col.get("type") or "").lower()
    return any(
        token in ctype
        for token in ["int", "double", "decimal", "float", "bigint"]
    )


def table_tags(table):
    if not table:
        return []

    name = table.get("name", "")
    domain = table.get("domain", "")

    tags = []

    if name in SENSITIVE_TABLES:
        tags.append("auth_or_system_table")

    if domain == "Auth & Permissions":
        tags.append("auth_domain")

    if domain == "System / Views / Misc":
        tags.append("system_misc_domain")

    if name.startswith(("temp", "test_sp", "dc_temp", "stock_temp")):
        tags.append("temporary_table")

    if any(
        c.get("name") in SENSITIVE_COLUMN_NAMES
        for c in table.get("columns", [])
    ):
        tags.append("sensitive_columns")

    return sorted(set(tags))


def relationship_tags(rel, table_map):
    tags = []

    child = table_map.get(rel.get("from_table"), {})
    parent = table_map.get(rel.get("to_table"), {})

    tags.extend(table_tags(child))
    tags.extend(table_tags(parent))

    if rel.get("type") == "audit":
        tags.append("audit_relationship")

    return sorted(set(tags))


def table_select_smoke_cases(table_map):
    cases = []

    for name, table in table_map.items():
        tags = table_tags(table)

        if not table.get("columns"):
            tags = sorted(set(tags + ["edge_no_columns"]))

        sql = f"SELECT * FROM {q(name)} LIMIT 20;"
        question = f"Show the first 20 rows from {name}."

        cases.append(
            make_case(
                suite="table_select_smoke",
                difficulty="easy",
                domain=table.get("domain", "Unknown"),
                question=question,
                sql=sql,
                expected_tables=[name],
                post_prune_tags=tags,
                expected_outcome="execute",
                notes="Raw table probe. Sensitive tables are tagged for post-pruning.",
            )
        )

    return cases


def table_count_smoke_cases(table_map):
    cases = []

    for name, table in table_map.items():
        tags = table_tags(table)

        sql = f"SELECT COUNT(*) AS row_count FROM {q(name)};"
        question = f"How many rows exist in {name}?"

        cases.append(
            make_case(
                suite="table_count_smoke",
                difficulty="easy",
                domain=table.get("domain", "Unknown"),
                question=question,
                sql=sql,
                expected_tables=[name],
                post_prune_tags=tags,
                expected_outcome="execute",
                notes="Basic table count probe.",
            )
        )

    return cases


def relationship_join_smoke_cases(relationships, table_map):
    cases = []

    for rel in relationships:
        child_name = rel.get("from_table")
        parent_name = rel.get("to_table")
        from_col = rel.get("from_column")
        to_col = rel.get("to_column")

        if not child_name or not parent_name or not from_col or not to_col:
            continue

        child = table_map.get(child_name, {})
        parent = table_map.get(parent_name, {})

        child_select_col = primary_key_or_first_column(child)
        parent_select_col = to_col

        child_select = (
            f"child.{q(child_select_col)} AS child_id"
            if child_select_col
            else "NULL AS child_id"
        )

        parent_select = (
            f"parent.{q(parent_select_col)} AS parent_id"
            if parent_select_col
            else "NULL AS parent_id"
        )

        sql = (
            f"SELECT {child_select}, {parent_select} "
            f"FROM {q(child_name)} AS child "
            f"JOIN {q(parent_name)} AS parent "
            f"ON child.{q(from_col)} = parent.{q(to_col)} "
            f"WHERE child.{q(from_col)} IS NOT NULL "
            f"LIMIT 20;"
        )

        question = (
            f"Join {child_name}.{from_col} to {parent_name}.{to_col} "
            f"and return the first 20 linked rows."
        )

        tags = relationship_tags(rel, table_map)

        if rel.get("type") == "audit":
            tags.append("audit_join")

        cases.append(
            make_case(
                suite="relationship_join_smoke",
                difficulty="easy",
                domain=child.get("domain", "Unknown"),
                question=question,
                sql=sql,
                expected_tables=[child_name, parent_name],
                post_prune_tags=tags,
                expected_outcome="execute",
                notes="Relationship smoke test generated from inferred schema relationships.",
            )
        )

    return cases


def single_table_filtered_cases(table_map):
    cases = []

    for name, table in table_map.items():
        domain = table.get("domain", "Unknown")
        tags = table_tags(table)

        if has_column(table, "deleted_at"):
            sql = (
                f"SELECT COUNT(*) AS row_count "
                f"FROM {q(name)} "
                f"WHERE {q('deleted_at')} IS NULL;"
            )
            question = f"How many active {name} records exist?"

            cases.append(
                make_case(
                    suite="single_table_filtered",
                    difficulty="easy",
                    domain=domain,
                    question=question,
                    sql=sql,
                    expected_tables=[name],
                    post_prune_tags=tags + ["soft_delete_filter"],
                    expected_outcome="execute",
                    notes="Soft-delete filtered count.",
                )
            )

        if has_column(table, "status"):
            where_parts = [f"{q('status')} = 'Y'"]
            if has_column(table, "deleted_at"):
                where_parts.append(f"{q('deleted_at')} IS NULL")

            sql = (
                f"SELECT COUNT(*) AS row_count "
                f"FROM {q(name)} "
                f"WHERE {' AND '.join(where_parts)};"
            )
            question = f"How many active-status {name} records exist?"

            cases.append(
                make_case(
                    suite="single_table_filtered",
                    difficulty="easy",
                    domain=domain,
                    question=question,
                    sql=sql,
                    expected_tables=[name],
                    post_prune_tags=tags + ["status_filter"],
                    expected_outcome="execute",
                    notes="Status Y filter.",
                )
            )

        if has_column(table, "created_at"):
            sql = (
                f"SELECT COUNT(*) AS row_count "
                f"FROM {q(name)} "
                f"WHERE {q('created_at')} IS NOT NULL;"
            )
            question = f"How many {name} records have a created date?"

            cases.append(
                make_case(
                    suite="single_table_filtered",
                    difficulty="easy",
                    domain=domain,
                    question=question,
                    sql=sql,
                    expected_tables=[name],
                    post_prune_tags=tags + ["date_filter"],
                    expected_outcome="execute",
                    notes="Created date not-null filter.",
                )
            )

        for col in table.get("columns", []):
            col_name = col.get("name")
            col_type = (col.get("type") or "").lower()

            if col_type.startswith("date") and col_name not in {
                "created_at",
                "updated_at",
                "deleted_at",
            }:
                sql = (
                    f"SELECT COUNT(*) AS row_count "
                    f"FROM {q(name)} "
                    f"WHERE {q(col_name)} IS NOT NULL;"
                )
                question = f"How many {name} records have {col_name} filled?"

                cases.append(
                    make_case(
                        suite="single_table_filtered",
                        difficulty="easy",
                        domain=domain,
                        question=question,
                        sql=sql,
                        expected_tables=[name],
                        post_prune_tags=tags + ["date_filter"],
                        expected_outcome="execute",
                        notes="Date column not-null filter.",
                    )
                )

    for table_name, col_name, enum_value in KNOWN_ENUM_FILTERS:
        table = table_map.get(table_name)
        if not table:
            continue

        if not has_column(table, col_name):
            continue

        tags = table_tags(table)

        where_parts = [f"{q(col_name)} = '{enum_value}'"]
        if has_column(table, "deleted_at"):
            where_parts.append(f"{q('deleted_at')} IS NULL")

        sql = (
            f"SELECT COUNT(*) AS row_count "
            f"FROM {q(table_name)} "
            f"WHERE {' AND '.join(where_parts)};"
        )
        question = (
            f"How many {table_name} records have {col_name} = '{enum_value}'?"
        )

        cases.append(
            make_case(
                suite="single_table_filtered",
                difficulty="medium",
                domain=table.get("domain", "Unknown"),
                question=question,
                sql=sql,
                expected_tables=[table_name],
                post_prune_tags=tags + ["enum_filter"],
                expected_outcome="execute",
                notes="Known enum-value filter.",
            )
        )

    return cases


def aggregation_group_cases(table_map):
    cases = []

    for name, table in table_map.items():
        domain = table.get("domain", "Unknown")
        tags = table_tags(table)

        for dim in GROUP_DIMENSIONS:
            if has_column(table, dim):
                sql = (
                    f"SELECT {q(dim)} AS dimension, COUNT(*) AS record_count "
                    f"FROM {q(name)} "
                    f"GROUP BY {q(dim)} "
                    f"ORDER BY record_count DESC "
                    f"LIMIT 20;"
                )
                question = f"Count {name} records grouped by {dim}."

                cases.append(
                    make_case(
                        suite="aggregation_group",
                        difficulty="medium",
                        domain=domain,
                        question=question,
                        sql=sql,
                        expected_tables=[name],
                        post_prune_tags=tags + ["group_by", dim],
                        expected_outcome="execute",
                        notes="Aggregation/group-by smoke test.",
                    )
                )

        for metric in METRIC_COLUMNS:
            col = get_column(table, metric)
            if not col:
                continue

            if not is_numeric_type(col):
                continue

            sql = (
                f"SELECT "
                f"COUNT(*) AS record_count, "
                f"SUM({q(metric)}) AS sum_value, "
                f"AVG({q(metric)}) AS avg_value, "
                f"MIN({q(metric)}) AS min_value, "
                f"MAX({q(metric)}) AS max_value "
                f"FROM {q(name)};"
            )
            question = f"Calculate basic aggregate metrics for {metric} in {name}."

            cases.append(
                make_case(
                    suite="aggregation_group",
                    difficulty="medium",
                    domain=domain,
                    question=question,
                    sql=sql,
                    expected_tables=[name],
                    post_prune_tags=tags + ["aggregate", metric],
                    expected_outcome="execute",
                    notes="Numeric aggregate smoke test.",
                )
            )

    return cases


def business_kpi_cases(table_map):
    cases = []

    for name, table in table_map.items():
        domain = table.get("domain", "Unknown")

        if domain not in BUSINESS_DOMAINS:
            continue

        tags = table_tags(table)

        where_parts = []
        if has_column(table, "deleted_at"):
            where_parts.append(f"{q('deleted_at')} IS NULL")

        where_sql = ""
        if where_parts:
            where_sql = " WHERE " + " AND ".join(where_parts)

        for dim in KPI_DIMENSIONS:
            if has_column(table, dim):
                sql = (
                    f"SELECT {q(dim)} AS dimension, COUNT(*) AS record_count "
                    f"FROM {q(name)}{where_sql} "
                    f"GROUP BY {q(dim)} "
                    f"ORDER BY record_count DESC "
                    f"LIMIT 100;"
                )
                question = f"Top {name} business records by {dim}."

                cases.append(
                    make_case(
                        suite="business_kpi",
                        difficulty="medium",
                        domain=domain,
                        question=question,
                        sql=sql,
                        expected_tables=[name],
                        post_prune_tags=tags + ["kpi", "group_by", dim],
                        expected_outcome="execute",
                        notes="Business KPI template query.",
                    )
                )

        for metric in METRIC_COLUMNS:
            col = get_column(table, metric)
            if not col:
                continue

            if not is_numeric_type(col):
                continue

            dim_candidates = [
                "product_id",
                "party_id",
                "financial_id",
                "category_id",
                "sales_order_id",
                "dc_id",
                "quotation_id",
                "pi_id",
            ]

            for dim in dim_candidates:
                if has_column(table, dim):
                    sql = (
                        f"SELECT {q(dim)} AS dimension, "
                        f"SUM({q(metric)}) AS metric_total "
                        f"FROM {q(name)}{where_sql} "
                        f"GROUP BY {q(dim)} "
                        f"ORDER BY metric_total DESC "
                        f"LIMIT 100;"
                    )
                    question = (
                        f"Total {metric} in {name} grouped by {dim}."
                    )

                    cases.append(
                        make_case(
                            suite="business_kpi",
                            difficulty="medium",
                            domain=domain,
                            question=question,
                            sql=sql,
                            expected_tables=[name],
                            post_prune_tags=tags + ["kpi", "sum", metric, dim],
                            expected_outcome="execute",
                            notes="Business KPI metric template query.",
                        )
                    )
                    break

    return cases


def hard_edge_cases(relationships, table_map):
    cases = []

    # 1. VARCHAR numeric quantity traps
    for name, table in table_map.items():
        domain = table.get("domain", "Unknown")
        tags = table_tags(table)

        for col in table.get("columns", []):
            col_name = col.get("name")
            col_type = (col.get("type") or "").lower()

            if col_name in VARCHAR_NUMERIC_COLUMNS and "varchar" in col_type:
                dim = None
                for candidate in [
                    "product_id",
                    "party_id",
                    "carton_no",
                    "batch_no",
                    "dc_id",
                    "financial_id",
                ]:
                    if has_column(table, candidate):
                        dim = candidate
                        break

                where_parts = [f"{q(col_name)} IS NOT NULL"]
                if has_column(table, "deleted_at"):
                    where_parts.append(f"{q('deleted_at')} IS NULL")

                where_sql = " WHERE " + " AND ".join(where_parts)

                if dim:
                    sql = (
                        f"SELECT {q(dim)} AS dimension, "
                        f"SUM(CAST({q(col_name)} AS DECIMAL(18,2))) AS total_qty "
                        f"FROM {q(name)}{where_sql} "
                        f"GROUP BY {q(dim)} "
                        f"ORDER BY total_qty DESC "
                        f"LIMIT 20;"
                    )
                    question = (
                        f"Calculate total {col_name} from {name} by {dim}, "
                        f"casting the varchar quantity safely."
                    )
                else:
                    sql = (
                        f"SELECT SUM(CAST({q(col_name)} AS DECIMAL(18,2))) AS total_qty "
                        f"FROM {q(name)}{where_sql};"
                    )
                    question = (
                        f"Calculate total {col_name} from {name}, "
                        f"casting the varchar quantity safely."
                    )

                cases.append(
                    make_case(
                        suite="hard_edge",
                        difficulty="hard",
                        domain=domain,
                        question=question,
                        sql=sql,
                        expected_tables=[name],
                        post_prune_tags=tags + ["varchar_numeric_cast"],
                        expected_outcome="execute",
                        notes="VARCHAR numeric quantity must be CAST before aggregation.",
                    )
                )

    # 2. Soft-delete join traps
    for rel in relationships:
        if rel.get("type") != "fk":
            continue

        child_name = rel.get("from_table")
        parent_name = rel.get("to_table")
        from_col = rel.get("from_column")
        to_col = rel.get("to_column")

        child = table_map.get(child_name, {})
        parent = table_map.get(parent_name, {})

        if not child or not parent:
            continue

        if not has_column(child, "deleted_at") or not has_column(parent, "deleted_at"):
            continue

        sql = (
            f"SELECT COUNT(*) AS linked_count "
            f"FROM {q(child_name)} AS child "
            f"JOIN {q(parent_name)} AS parent "
            f"ON child.{q(from_col)} = parent.{q(to_col)} "
            f"WHERE child.{q('deleted_at')} IS NULL "
            f"AND parent.{q('deleted_at')} IS NULL;"
        )
        question = (
            f"How many active {child_name} rows are linked to active {parent_name} rows?"
        )

        tags = relationship_tags(rel, table_map)
        tags.append("soft_delete_join")

        cases.append(
            make_case(
                suite="hard_edge",
                difficulty="hard",
                domain=child.get("domain", "Unknown"),
                question=question,
                sql=sql,
                expected_tables=[child_name, parent_name],
                post_prune_tags=tags,
                expected_outcome="execute",
                notes="Both sides of the join must respect soft-delete.",
            )
        )

    # 3. Current financial year traps
    for name, table in table_map.items():
        if not has_column(table, "financial_id"):
            continue

        domain = table.get("domain", "Unknown")
        tags = table_tags(table)

        where_parts = [f"fy.{q('current_year')} = 'Y'"]
        if has_column(table, "deleted_at"):
            where_parts.append(f"base.{q('deleted_at')} IS NULL")

        sql = (
            f"SELECT COUNT(*) AS row_count "
            f"FROM {q(name)} AS base "
            f"JOIN {q('financial_year')} AS fy "
            f"ON base.{q('financial_id')} = fy.{q('id')} "
            f"WHERE {' AND '.join(where_parts)};"
        )
        question = f"How many {name} records belong to the current financial year?"

        cases.append(
            make_case(
                suite="hard_edge",
                difficulty="hard",
                domain=domain,
                question=question,
                sql=sql,
                expected_tables=[name, "financial_year"],
                post_prune_tags=tags + ["financial_year_filter"],
                expected_outcome="execute",
                notes="Financial-year scoping trap.",
            )
        )

    # 4. Implicit type mismatch joins
    for child_name, child_col, parent_name, parent_col in TYPE_MISMATCH_JOINS:
        child = table_map.get(child_name)
        parent = table_map.get(parent_name)

        if not child or not parent:
            continue

        tags = table_tags(child) + table_tags(parent)
        tags.append("type_mismatch_join")

        where_parts = [
            f"child.{q(child_col)} IS NOT NULL",
            f"parent.{q(parent_col)} IS NOT NULL",
        ]

        if has_column(child, "deleted_at"):
            where_parts.append(f"child.{q('deleted_at')} IS NULL")

        if has_column(parent, "deleted_at"):
            where_parts.append(f"parent.{q('deleted_at')} IS NULL")

        sql = (
            f"SELECT COUNT(*) AS linked_count "
            f"FROM {q(child_name)} AS child "
            f"JOIN {q(parent_name)} AS parent "
            f"ON child.{q(child_col)} = parent.{q(parent_col)} "
            f"WHERE {' AND '.join(where_parts)};"
        )
        question = (
            f"How many {child_name} rows are linked to {parent_name} rows "
            f"despite possible varchar/int type mismatch?"
        )

        cases.append(
            make_case(
                suite="hard_edge",
                difficulty="hard",
                domain=child.get("domain", "Unknown"),
                question=question,
                sql=sql,
                expected_tables=[child_name, parent_name],
                post_prune_tags=tags,
                expected_outcome="execute",
                notes="Type-mismatch join edge case.",
            )
        )

    return cases


def negative_security_cases():
    cases = []

    def add_negative(question, sql, tags, notes):
        cases.append(
            make_case(
                suite="negative_security",
                difficulty="negative",
                domain="Security",
                question=question,
                sql=sql,
                expected_tables=[],
                post_prune_tags=["negative_security"] + tags,
                expected_outcome="reject_or_fail_safely",
                notes=notes,
            )
        )

    non_select = [
        "INSERT INTO users (name, email) VALUES ('x', 'x@example.com');",
        "UPDATE users SET name = 'x' WHERE id = 1;",
        "DELETE FROM party WHERE id = 1;",
        "DROP TABLE party;",
        "TRUNCATE TABLE lead;",
        "ALTER TABLE party ADD COLUMN test_col VARCHAR(100);",
        "CREATE TABLE hack_table (id INT);",
        "REPLACE INTO users (id, name, email) VALUES (1, 'x', 'x@example.com');",
        "GRANT SELECT ON party TO 'readonly_user';",
        "REVOKE SELECT ON party FROM 'readonly_user';",
    ]

    for i, sql in enumerate(non_select, start=1):
        add_negative(
            f"Non-SELECT security negative test {i}",
            sql,
            ["non_select"],
            "Must be rejected before execution.",
        )

    stacked = [
        "SELECT 1; DROP TABLE party;",
        "SELECT * FROM users; DELETE FROM users;",
        "SELECT COUNT(*) FROM party; UPDATE party SET status = 'N';",
        "SELECT 1; INSERT INTO users (name, email) VALUES ('x', 'x@example.com');",
        "SELECT * FROM lead; TRUNCATE TABLE lead;",
    ]

    for i, sql in enumerate(stacked, start=1):
        add_negative(
            f"Stacked-query security negative test {i}",
            sql,
            ["stacked_query"],
            "Multi-statement SQL must be rejected.",
        )

    dangerous = [
        "SELECT SLEEP(10);",
        "SELECT BENCHMARK(100000000, MD5('test'));",
        "SELECT LOAD_FILE('/etc/passwd');",
        "SELECT GET_LOCK('globalmind_lock', 10);",
        "SELECT sys_eval('id');",
        "SELECT * FROM users INTO OUTFILE '/tmp/users.csv';",
        "SELECT password FROM users UNION SELECT token FROM personal_access_tokens;",
        "SELECT pg_sleep(10);",
        "SELECT * FROM party WHERE 1=1 UNION SELECT password FROM users;",
        "SELECT * FROM information_schema.tables;",
    ]

    for i, sql in enumerate(dangerous, start=1):
        add_negative(
            f"Dangerous-function security negative test {i}",
            sql,
            ["dangerous_function"],
            "Dangerous function or exfiltration attempt must be rejected.",
        )

    sensitive = [
        "SELECT password FROM users;",
        "SELECT remember_token FROM users;",
        "SELECT token FROM personal_access_tokens;",
        "SELECT token FROM password_resets;",
        "SELECT payload FROM failed_jobs;",
        "SELECT exception FROM failed_jobs;",
        "SELECT bank_account_no FROM party;",
        "SELECT ifsc_code FROM party;",
        "SELECT pan_no FROM party;",
        "SELECT email, mobile FROM users;",
    ]

    for i, sql in enumerate(sensitive, start=1):
        add_negative(
            f"Sensitive-column security negative test {i}",
            sql,
            ["sensitive_column"],
            "Sensitive column access should be blocked or restricted by policy.",
        )

    large = [
        "SELECT * FROM stock LIMIT 100000000;",
        "SELECT * FROM party LIMIT 999999999;",
        "SELECT * FROM lead;",
        "SELECT * FROM sales_order_products;",
        "SELECT * FROM packagings;",
    ]

    for i, sql in enumerate(large, start=1):
        add_negative(
            f"Large-result security negative test {i}",
            sql,
            ["large_result"],
            "Query should be limited, clamped, or rejected by resource policy.",
        )

    invalid = [
        "SELECT * FROM nonexistent_table;",
        "SELECT missing_column FROM party;",
        "SELECT * FROM party WHERE missing_column = 1;",
        "SELECT * FROM users WHERE password = ;",
        "SELECT FROM party;",
        "SELECT status FROM party GROUP BY missing_column;",
        "SELECT COUNT(*) FROM party WHERE deleted_at IS NULL GROUP BY;",
        "SELECT * FROM party ORDER BY missing_column;",
        "SELECT SUM(qty) FROM users;",
        "SELECT AVG(password) FROM users;",
    ]

    for i, sql in enumerate(invalid, start=1):
        add_negative(
            f"Invalid-schema negative test {i}",
            sql,
            ["invalid_schema"],
            "Invalid schema query should fail safely without exposing data.",
        )

    return cases


def pad_to_quota(cases, quota, table_map, suite_name):
    cases = unique_cases(cases)

    if len(cases) >= quota:
        return cases[:quota]

    missing = quota - len(cases)
    existing = {normalize_sql(case["sql"]) for case in cases}
    padded = cases.copy()

    for table in table_map.values():
        if missing <= 0:
            break

        name = table.get("name")
        domain = table.get("domain", "Unknown")
        tags = table_tags(table)

        for col in table.get("columns", []):
            if missing <= 0:
                break

            col_name = col.get("name")
            if not col_name:
                continue

            sql = (
                f"SELECT COUNT(*) AS row_count "
                f"FROM {q(name)} "
                f"WHERE {q(col_name)} IS NOT NULL;"
            )

            if normalize_sql(sql) in existing:
                continue

            padded.append(
                make_case(
                    suite=suite_name,
                    difficulty="auto_generated",
                    domain=domain,
                    question=f"How many {name} rows have {col_name} filled?",
                    sql=sql,
                    expected_tables=[name],
                    post_prune_tags=tags + ["padding"],
                    expected_outcome="execute",
                    notes="Auto-generated padding query to satisfy benchmark quota.",
                )
            )

            existing.add(normalize_sql(sql))
            missing -= 1

    return padded


def global_padding(table_map, missing, existing_cases):
    existing = {normalize_sql(case["sql"]) for case in existing_cases}
    padded = []

    for table in table_map.values():
        if missing <= 0:
            break

        name = table.get("name")
        domain = table.get("domain", "Unknown")
        tags = table_tags(table)

        for col in table.get("columns", []):
            if missing <= 0:
                break

            col_name = col.get("name")
            if not col_name:
                continue

            sql = (
                f"SELECT COUNT(*) AS row_count "
                f"FROM {q(name)} "
                f"WHERE {q(col_name)} IS NULL;"
            )

            if normalize_sql(sql) in existing:
                continue

            padded.append(
                make_case(
                    suite="global_padding",
                    difficulty="auto_generated",
                    domain=domain,
                    question=f"How many {name} rows have {col_name} empty?",
                    sql=sql,
                    expected_tables=[name],
                    post_prune_tags=tags + ["padding"],
                    expected_outcome="execute",
                    notes="Auto-generated global padding query.",
                )
            )

            existing.add(normalize_sql(sql))
            missing -= 1

    return padded


def build_cases(schema):
    table_map = get_table_map(schema)
    relationships = schema.get("relationships", [])

    select_cases = unique_cases(table_select_smoke_cases(table_map))[:70]
    count_cases = unique_cases(table_count_smoke_cases(table_map))[:70]
    relationship_cases = unique_cases(
        relationship_join_smoke_cases(relationships, table_map)
    )[:294]

    filtered_cases = pad_to_quota(
        single_table_filtered_cases(table_map),
        120,
        table_map,
        "single_table_filtered",
    )

    aggregation_cases = pad_to_quota(
        aggregation_group_cases(table_map),
        116,
        table_map,
        "aggregation_group",
    )

    kpi_cases = pad_to_quota(
        business_kpi_cases(table_map),
        180,
        table_map,
        "business_kpi",
    )

    hard_cases = pad_to_quota(
        hard_edge_cases(relationships, table_map),
        100,
        table_map,
        "hard_edge",
    )

    negative_cases = negative_security_cases()[:50]

    all_cases = (
        select_cases
        + count_cases
        + relationship_cases
        + filtered_cases
        + aggregation_cases
        + kpi_cases
        + hard_cases
        + negative_cases
    )

    if len(all_cases) < TARGET_TOTAL:
        all_cases += global_padding(
            table_map,
            TARGET_TOTAL - len(all_cases),
            all_cases,
        )

    if len(all_cases) > TARGET_TOTAL:
        all_cases = all_cases[:TARGET_TOTAL]

    for i, case in enumerate(all_cases, start=1):
        case["id"] = f"GM-P1-{i:04d}"

    return all_cases


def main():
    schema = load_schema()
    cases = build_cases(schema)

    counts = Counter(case["suite"] for case in cases)

    payload = {
        "benchmark": {
            "name": "GlobalMind SQL Alpha - Phase 1 Golden Dataset",
            "version": "1.0.0",
            "created_from": str(SCHEMA_FILE),
            "target_total": TARGET_TOTAL,
            "generated_total": len(cases),
            "privacy_mode": "llm_sees_only_schema_and_question",
            "post_prune_policy": "generate_all_first_then_tag_sensitive_for_later_pruning",
            "llm_sees": [
                "question",
                "schema_metadata",
                "table_names",
                "column_names",
                "column_types",
                "relationships",
                "business_glossary",
                "sanitized_sql_errors",
            ],
            "llm_does_not_see": [
                "db_rows",
                "query_result_rows",
                "raw_db_errors_with_data",
                "pii",
                "tokens",
                "passwords",
            ],
            "counts": dict(counts),
        },
        "cases": cases,
    }

    OUTPUT_JSON.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    with OUTPUT_JSONL.open("w", encoding="utf-8") as f:
        for case in cases:
            f.write(json.dumps(case, ensure_ascii=False) + "\n")

    print(f"Phase 1 golden dataset created.")
    print(f"Total cases: {len(cases)}")
    print(f"JSON output: {OUTPUT_JSON.resolve()}")
    print(f"JSONL output: {OUTPUT_JSONL.resolve()}")
    print("\nSuite distribution:")
    for suite, count in sorted(counts.items()):
        print(f"{suite}: {count}")


if __name__ == "__main__":
    main()
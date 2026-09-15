"""Schema Sufficiency Guard (Shadow Mode).

Verifies that the retrieved schema context contains all tables and key entities
implied by the user query before prompt construction.
Operates in < 1ms in-memory with zero LLM calls.
"""

from __future__ import annotations

import re
import time
from typing import Any

from src.models.trace import GuardResult
from src.utils.error_classification import FailureCategory
from src.utils.feature_flags import is_feature_enabled

# Common entity/keyword to table mappings in Global_Mind ERP schema
_ENTITY_TABLE_MAP: dict[str, str] = {
    "order": "sales_order",
    "orders": "sales_order",
    "sales order": "sales_order",
    "customer": "party",
    "supplier": "party",
    "vendor": "party",
    "party": "party",
    "parties": "party",
    "purchase": "purchase",
    "purchases": "purchase",
    "po": "purchase",
    "challan": "delivery_challan",
    "delivery challan": "delivery_challan",
    "dc": "delivery_challan",
    "stock": "stock",
    "inventory": "stock",
    "stock adjustment": "stock_adjustment",
    "adjustment": "stock_adjustment",
    "product": "product",
    "products": "product",
    "item": "product",
    "items": "product",
    "warehouse": "warehouse",
    "warehouses": "warehouse",
    "category": "category",
    "categories": "category",
    "machine": "machine",
    "machines": "machine",
    "production": "production",
    "batch": "production",
    "unit": "unit",
    "uom": "unit",
    "quotation": "quotation",
    "proforma": "proforma",
    "balance": "party_opening_balance",
}


def detect_required_tables(query: str) -> set[str]:
    """Extract required database tables from domain terms in query."""
    q_lower = query.lower()
    required: set[str] = set()
    for phrase, table in _ENTITY_TABLE_MAP.items():
        if re.search(rf"\b{re.escape(phrase)}\b", q_lower):
            required.add(table)
    return required


def evaluate_schema_sufficiency(
    query: str,
    schema_context: str,
    required_tables: set[str] | list[str] | None = None,
    enforce: bool | None = None,
) -> GuardResult:
    """Evaluate whether the retrieved schema context contains the tables required by the query."""
    t0 = time.perf_counter()
    if enforce is None:
        enforce = is_feature_enabled("guard_schema_sufficiency_enforce")
    mode = "ENFORCED" if enforce else "SHADOW"

    target_tables = set(required_tables) if required_tables is not None else detect_required_tables(query)

    if not target_tables:
        latency_ms = (time.perf_counter() - t0) * 1000
        return GuardResult(
            guard_name="schema_sufficiency",
            passed=True,
            mode=mode,
            message="No specific database tables identified in query",
            latency_ms=round(latency_ms, 3),
        )

    schema_lower = (schema_context or "").lower()
    missing_tables = [tbl for tbl in target_tables if tbl not in schema_lower]

    latency_ms = (time.perf_counter() - t0) * 1000

    if missing_tables:
        return GuardResult(
            guard_name="schema_sufficiency",
            passed=False,
            mode=mode,
            failure_category=FailureCategory.SCHEMA_RETRIEVAL_MISS.value,
            message=f"Query references entities requiring tables {missing_tables}, but they are missing from retrieved schema context",
            latency_ms=round(latency_ms, 3),
            metadata={"missing_tables": missing_tables, "required_tables": list(target_tables)},
        )

    return GuardResult(
        guard_name="schema_sufficiency",
        passed=True,
        mode=mode,
        message="Retrieved schema context sufficiently covers all detected tables",
        latency_ms=round(latency_ms, 3),
        metadata={"covered_tables": list(target_tables)},
    )

"""Stage 12b Ã¢â¬â Text-to-SQL Retrieval.

Dynamically translates natural language into SQL against the live database,
executes it, and returns the results formatted as a context chunk.
"""

from __future__ import annotations

from collections import OrderedDict
import functools
import json
import logging
import re
import time
from pathlib import Path
from typing import Any

import sqlglot
from sqlglot import exp

from src.core.config import settings
from src.core.db_client import run_readonly_query
from src.core.pipeline_metrics import log_event as _log_pipeline_event
from src.core.provider_client import ProviderRouter
from src.core.sql_column_registry import ColumnRegistry
from src.core.sql_dialects import SQLDialectProfile, get_dialect_profile
from src.core.result_validator import ResultValidator, ValidationSeverity
from src.core.pattern_learner import PatternLearner
from src.core.confidence_scorer import ConfidenceScorer, ConfidenceBreakdown
from src.models.schemas import Chunk, ChunkType, RetrievedChunk, DocumentType
from src.stages.s10_embeddings import EmbeddingService
from src.utils.circuit_breaker import CircuitBreakerOpenError, get_shared_circuit_breaker
from src.utils.empty_result_classifier import classify_empty_result
from src.utils.error_classification import classify_error
from src.utils.failure_capture import capture_sql_failure
from src.utils.feature_flags import is_feature_enabled
from src.utils.query_budget import QueryBudgetExceededError, get_or_create_budget_controller
from src.utils.schema_budget import DEFAULT_SCHEMA_TOKEN_BUDGET, select_schema_within_budget
from src.utils.stream_token_counter import TokenBudgetExceededError
from src.utils.schema_compactor import compact_ddl, extract_join_hints
from src.utils.schema_token_estimator import estimate_schema_tokens
from src.utils.sql_safety import (
    check_dangerous_patterns,
    is_destructive_sql,
    validate_sql_safety,
    validate_tables_and_columns,
)
from src.utils.telemetry import get_or_create_query_id, log_telemetry, timed_stage
from src.stages.sql_repair import (
    MAX_DELTA_REPAIR_ATTEMPTS,
    attempt_delta_repair,
    extract_schema_context_from_ddl,
)

logger = logging.getLogger(__name__)


def format_schema_rows(profile: SQLDialectProfile, rows: list[dict[str, Any]]) -> str:
    """Turn an engine's raw introspection rows into schema text for the NL2SQL prompt.

    Pure function of (dialect profile, rows) Ã¢â¬â no instance state, no global
    settings Ã¢â¬â so it can be unit tested directly for each engine.

    SQLite's sqlite_master query already returns one full CREATE TABLE
    statement per row. MySQL's information_schema.columns query returns
    one row per column, so those need grouping by table first.
    """
    if profile.key == "sqlite":
        return "\n\n".join(
            row["sql"] for row in rows if row["name"] != "sqlite_sequence"
        )

    if profile.key == "mysql":
        tables: dict[str, list[str]] = {}
        for row in rows:
            comment = row.get("column_comment") or ""
            suffix = f"  -- {comment}" if comment else ""
            tables.setdefault(row["table_name"], []).append(
                f"  {row['column_name']} {row['data_type']}{suffix}"
            )
        return "\n\n".join(
            f"TABLE {name} (\n" + ",\n".join(cols) + "\n)"
            for name, cols in tables.items()
        )

    raise ValueError(f"Unsupported dialect key {profile.key!r}")


def format_fk_rows(rows: list[dict]) -> str:
    if not rows:
        return ""

    lines = [
        f"  {r['table_name']}.{r['column_name']} -> {r['referenced_table_name']}.{r['referenced_column_name']}"
        for r in rows
    ]
    return "Foreign Keys:\n" + "\n".join(lines)


class UnsafeQueryError(Exception):
    """Raised when sqlglot rejects a query (e.g. not a SELECT). Never retried."""
    pass


_ABSTAIN_RE = re.compile(r"^\W*no_sql\b", re.IGNORECASE)
_FENCE_RE = re.compile(r"```(?:sql)?\s*(.*?)(?:```|$)", re.IGNORECASE | re.DOTALL)
_SQL_START_RE = re.compile(r"\b(SELECT|WITH)\b", re.IGNORECASE)


def _unwrap_sql(text: str) -> str:
    """Extract the SQL from an LLM response that may wrap it in a markdown code
    fence or precede it with a prose line or CoT reasoning.

    Only the minimal, safe extractions are performed:
      * strip reasoning <think>...</think> tags;
      * extract a fenced ```sql ... ``` (or bare ``` ... ```) block;
      * otherwise, if a leading prose preamble sits before the first SELECT/WITH,
        drop the preamble so the query still parses.
    """
    cleaned = re.sub(r"(?s)<think>.*?</think>", "", text).strip()
    if not cleaned and "</think>" in text:
        cleaned = text.split("</think>")[-1].strip()

    target = cleaned if cleaned else text.strip()
    m = _FENCE_RE.search(target)
    if m and m.group(1).strip():
        return m.group(1).strip()
    km = _SQL_START_RE.search(target)
    if km and km.start() >= 0:
        return target[km.start():].strip()
    return target


def extract_cot_and_sql(text: str) -> tuple[str, str]:
    """Separates structured metadata / CoT from the final SQL statement (supports JSON & Markdown)."""
    cleaned = re.sub(r"(?s)<think>.*?</think>", "", text).strip()
    target = cleaned if cleaned else text.strip()

    # 1. Try parsing direct JSON
    try:
        data = json.loads(target)
        if isinstance(data, dict) and "sql" in data and data["sql"]:
            return json.dumps({k: v for k, v in data.items() if k != "sql"}), str(data["sql"]).strip()
    except Exception:
        pass

    # 2. Try regex extraction of JSON "sql" field
    json_sql_match = re.search(r"\"sql\"\s*:\s*\"(.*?)(?<!\\)\"", target, re.DOTALL)
    if json_sql_match:
        sql_cand = json_sql_match.group(1).strip().replace('\\"', '"').replace('\\n', '\n')
        if sql_cand and any(sql_cand.upper().strip().startswith(kw) for kw in ("SELECT", "WITH", "SHOW", "DESCRIBE", "EXPLAIN")):
            return target[:json_sql_match.start()].strip(), sql_cand

    # 3. Try markdown ```sql ... ``` block
    m = _FENCE_RE.search(target)
    if m and m.group(1).strip():
        sql = m.group(1).strip()
        cot = target[:m.start()].strip()
        return cot, sql

    # 4. Try finding starting SQL keyword
    km = _SQL_START_RE.search(target)
    if km and km.start() >= 0:
        cot = target[:km.start()].strip()
        sql = target[km.start():].strip()
        return cot, sql

    return "", target


def _is_all_null(rows: list[dict[str, Any]]) -> bool:
    """True for a single row whose every column is NULL."""
    return len(rows) == 1 and all(v is None for v in rows[0].values())


def _is_aggregate_over_zero_rows(sql: str, rows: list[dict[str, Any]], dialect: str) -> bool:
    """True if a query with top-level aggregate functions (without GROUP BY) matched 0 rows,
    yielding a single row with all NULLs.

    Non-aggregate queries matching a row where the selected column is genuinely NULL
    (e.g. SELECT discount_code FROM orders WHERE id = 123) return False.
    """
    if not _is_all_null(rows):
        return False
    try:
        ast = sqlglot.parse_one(sql, read=dialect)
        has_agg = any(
            isinstance(n, (exp.Sum, exp.Avg, exp.Min, exp.Max, exp.AggFunc))
            for n in ast.find_all(exp.Func)
        )
        has_group = ast.find(exp.Group) is not None
        return has_agg and not has_group
    except Exception:
        return False


def _extract_table_names(sql: str, dialect: str) -> list[str]:
    try:
        ast = sqlglot.parse_one(sql, read=dialect)
        return sorted({t.name for t in ast.find_all(exp.Table)})
    except Exception:
        return []


@functools.lru_cache(maxsize=1)
def _get_raw_relationships() -> list[dict[str, Any]]:
    """Load raw relationship list from config/sql_relationships.json."""
    path = Path(__file__).resolve().parents[2] / "config" / "sql_relationships.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        rels = data.get("relationships") if isinstance(data, dict) else data
        return rels if isinstance(rels, list) else []
    except Exception:
        return []


def _extract_schema_table_names(schema: str) -> set[str]:
    """Extract table names present in a DDL schema string."""
    names: set[str] = set()
    for m in re.finditer(r'(?:TABLE|CREATE\s+TABLE)\s+([a-zA-Z0-9_]+)', schema, re.IGNORECASE):
        names.add(m.group(1).lower())
    return names


def _extract_table_ddl_map(full_schema: str) -> dict[str, str]:
    """Parse full schema string into {table_name: ddl_string}."""
    ddls: dict[str, str] = {}
    for block in full_schema.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        m = re.search(r'(?:TABLE|CREATE\s+TABLE)\s+([a-zA-Z0-9_]+)', block, re.IGNORECASE)
        if m:
            ddls[m.group(1).lower()] = block
    return ddls


def _get_1hop_neighbors(tables: set[str], rels: list[dict[str, Any]] | None = None) -> set[str]:
    """Find 1-hop connected tables from the relationship graph, skipping audit noise."""
    raw_rels = rels if rels is not None else _get_raw_relationships()
    neighbors: set[str] = set()
    for r in raw_rels:
        frm = (r.get("from_table") or "").lower()
        to = (r.get("to_table") or "").lower()
        fcol = (r.get("from_column") or "").lower()
        # Skip audit trail links to users unless explicitly asked
        if to == "users" and fcol in ("created_id", "updated_id", "deleted_id"):
            continue
        if frm in tables and to:
            neighbors.add(to)
        if to in tables and frm:
            neighbors.add(frm)
    return neighbors


def _format_scoped_relationships(
    active_tables: set[str],
    query: str = "",
    rels: list[dict[str, Any]] | None = None,
) -> str:
    """Format relationships only between the tables present in the active schema prompt."""
    if not active_tables:
        return ""
    raw_rels = rels if rels is not None else _get_raw_relationships()
    if not raw_rels:
        return ""

    include_audit = any(
        w in query.lower()
        for w in ("created by", "creator", "updated by", "who entered", "who deleted")
    )
    grouped: dict[str, list[str]] = {}
    for r in raw_rels:
        frm = (r.get("from_table") or "").lower()
        to = (r.get("to_table") or "").lower()
        fcol = r.get("from_column")
        tcol = r.get("to_column")
        if not (frm and to and fcol and tcol):
            continue
        if frm not in active_tables or to not in active_tables:
            continue
        if not include_audit and to == "users" and str(fcol).lower() in ("created_id", "updated_id", "deleted_id"):
            continue
        grouped.setdefault(frm, []).append(f"{fcol}->{to}.{tcol}")

    if not grouped:
        return ""
    return "\n".join(
        f"- {table}: {', '.join(edges)}" for table, edges in sorted(grouped.items())
    )


@functools.lru_cache(maxsize=1)
def _load_relationships() -> str:
    """Load the inferred join map from disk, cached for process lifetime.

    Databases without explicit FOREIGN KEY constraints give the SQL-generation
    model no way to know how tables join, so it guesses — producing errors like
    `Unknown column 'p.product_color_id' in 'on clause'` (the column lives on the
    line-item tables and joins to product_color, not on product). Feeding an
    explicit join map into the prompt removes that guesswork.

    Formatted one line per source table for compactness:
        - sales_order_products: sales_order_id->sales_order.id, product_id->product.id, ...

    Returns "" when no relationships file is present (e.g. a deployment whose DB
    has real FK constraints and needs no inferred map), so injection is opt-in.
    """
    rels = _get_raw_relationships()
    if not rels:
        return ""
    grouped: dict[str, list[str]] = {}
    for r in rels:
        frm, fcol = r.get("from_table"), r.get("from_column")
        to, tcol = r.get("to_table"), r.get("to_column")
        if not all((frm, fcol, to, tcol)):
            continue
        grouped.setdefault(frm, []).append(f"{fcol}->{to}.{tcol}")
    return "\n".join(
        f"- {table}: {', '.join(edges)}" for table, edges in sorted(grouped.items())
    )


@functools.lru_cache(maxsize=1)
def _load_glossary() -> str:
    """Load SQL glossary from disk, cached for process lifetime. ARCH-9."""
    path = Path(__file__).resolve().parents[2] / "config" / "sql_glossary.json"
    try:
        groups = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(groups, dict) or not groups:
            return ""

        lines: list[str] = []
        for concept, syns in groups.items():
            if isinstance(syns, str):
                synonym_text = syns
            elif isinstance(syns, list):
                synonym_text = ", ".join(str(item) for item in syns if str(item).strip())
            else:
                synonym_text = str(syns)

            synonym_text = synonym_text.strip()
            if synonym_text:
                lines.append(f"- {concept}: {synonym_text}")
        return "\n".join(lines)
    except (FileNotFoundError, json.JSONDecodeError, OSError, TypeError, ValueError):
        return ""


@functools.lru_cache(maxsize=1)
def _get_raw_column_glossary() -> dict:
    """Load column-mapped glossary dict from disk."""
    path = Path(__file__).resolve().parents[2] / "config" / "sql_column_glossary.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        return data
    except Exception:
        return {}


_GLOSSARY_STOP_WORDS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "of", "for", "in", "on", "at",
    "to", "by", "with", "and", "or", "our", "my", "your", "who", "what", "which",
    "show", "get", "list", "how", "much", "many", "this", "that", "from", "tell",
})


def _stem_word(w: str) -> str:
    w = w.lower()
    if w.endswith("ies") and len(w) > 4:
        return w[:-3] + "y"
    if w.endswith("es") and len(w) > 3 and not w.endswith("tes"):
        return w[:-2]
    if w.endswith("s") and not w.endswith("ss") and len(w) > 3:
        return w[:-1]
    return w


def _matches_glossary_candidate(candidate: str, query_lower: str, query_words: set[str], query_stems: set[str]) -> bool:
    cand_lower = candidate.lower().replace("_", " ").strip()
    if not cand_lower:
        return False
    # 1. Exact phrase with word boundaries & optional plural (e.g. "buyer/buyers", "estimate/estimates")
    if re.search(r"\b" + re.escape(cand_lower) + r"(?:s|es|ies)?\b", query_lower):
        return True
    # 2. Check stemmed candidate against query stems
    cand_words = [w for w in re.findall(r"\w+", cand_lower) if w not in _GLOSSARY_STOP_WORDS]
    if not cand_words:
        return False
    if len(cand_words) == 1:
        w = cand_words[0]
        if w in query_words or _stem_word(w) in query_stems:
            return True
    else:
        # Multi-word candidate: all significant stems must match
        cand_stems = {_stem_word(w) for w in cand_words}
        if cand_stems.issubset(query_stems):
            return True
    return False


def _build_column_glossary_for_query(query: str) -> str:
    """Filter the glossary to only include terms/synonyms relevant to the query to save tokens."""
    data = _get_raw_column_glossary()
    if not data:
        return ""

    query_lower = query.lower()
    raw_words = set(re.findall(r"\w+", query_lower)) - _GLOSSARY_STOP_WORDS
    query_stems = {_stem_word(w) for w in raw_words}

    lines: list[str] = []
    for term, details in data.items():
        if not isinstance(details, dict):
            continue
        candidates = [term] + details.get("synonyms", [])
        if any(_matches_glossary_candidate(c, query_lower, raw_words, query_stems) for c in candidates if isinstance(c, str)):
            maps_to = details.get("maps_to")
            if maps_to:
                note = details.get("note", "")
                note_str = f" ({note})" if note else ""
                lines.append(f'- "{term}" → {maps_to}{note_str}')
                if len(lines) >= 15:
                    break

    return "\n".join(lines)


_BEHAVIORAL_ATLAS_CACHE: dict[str, Any] | None = None


def _get_raw_behavioral_atlas() -> dict[str, Any]:
    global _BEHAVIORAL_ATLAS_CACHE
    if _BEHAVIORAL_ATLAS_CACHE is not None:
        return _BEHAVIORAL_ATLAS_CACHE
    atlas_path = Path(__file__).resolve().parent.parent.parent / "config" / "behavioral_schema_atlas.json"
    if atlas_path.exists():
        try:
            with open(atlas_path, "r", encoding="utf-8") as f:
                _BEHAVIORAL_ATLAS_CACHE = json.load(f)
        except Exception:
            _BEHAVIORAL_ATLAS_CACHE = {}
    else:
        _BEHAVIORAL_ATLAS_CACHE = {}
    return _BEHAVIORAL_ATLAS_CACHE


def _build_behavioral_atlas_for_query(schema_tables: set[str], query: str) -> str:
    """Extract dynamically filtered behavioral rules and formulas for active tables."""
    atlas_data = _get_raw_behavioral_atlas()
    if not atlas_data or "tables" not in atlas_data:
        return ""
    
    tables = atlas_data["tables"]
    lines: list[str] = []
    
    # Cap to at most 4 active tables to strictly avoid LLM payload/TPM limits (under 8000 TPM)
    active_tables = sorted(schema_tables)[:4]
    
    for t_name in active_tables:
        if t_name not in tables:
            continue
        t_data = tables[t_name]
        lines.append(f"### Table `{t_name}`: {t_data.get('table_meaning', '')}")
        for r in t_data.get("table_behavioral_rules", [])[:2]:
            lines.append(f"  - Rule: {r}")
        for w in t_data.get("join_warnings", [])[:1]:
            lines.append(f"  - ⚠️ Warning: {w}")
        
        # List columns with rules or formulas (max 4 per table)
        col_count = 0
        for c_name, c_data in t_data.get("columns", {}).items():
            c_rules = c_data.get("behavioral_rules", [])
            formula = c_data.get("aggregation_formula")
            c_warns = c_data.get("join_warnings", [])
            if c_rules or formula or c_warns:
                parts = []
                if c_rules:
                    parts.append(" | ".join(c_rules[:2]))
                if c_warns:
                    parts.append("⚠️ " + " | ".join(c_warns[:1]))
                if formula:
                    parts.append(f"Formula: `{formula}`")
                lines.append(f"  - `{t_name}.{c_name}` ({c_data.get('type', 'VARCHAR')}): {'; '.join(parts)}")
                col_count += 1
                if col_count >= 4:
                    break
        lines.append("")
        
    return "\n".join(lines)


def extract_analytical_intent(query: str) -> dict[str, Any]:
    """Extract business analytical intent (metrics, dimensions, filters, time_period, aggregation, limit, sorting)
    from a user's question without writing SQL, serving as a semantic-layer preprocessor.
    """
    q = query.lower()
    intent: dict[str, Any] = {
        "metrics": [],
        "dimensions": [],
        "filters": [],
        "time_period": None,
        "entities": [],
        "aggregation": None,
        "limit": None,
        "sorting": None,
        "ambiguous_terms": [],
    }

    # Relative Time Periods
    if "last month" in q or "previous month" in q:
        intent["time_period"] = "last month"
    elif "this year" in q or "current year" in q or "this financial year" in q or "this fiscal year" in q:
        intent["time_period"] = "this financial year"
    elif "last year" in q or "previous year" in q:
        intent["time_period"] = "last financial year"
    elif "last quarter" in q:
        intent["time_period"] = "last quarter"
    elif "last 6 months" in q or "past 6 months" in q:
        intent["time_period"] = "last 6 months"
    elif "last 30 days" in q or "past 30 days" in q:
        intent["time_period"] = "last 30 days"

    # Aggregations
    if re.search(r"\b(how many|count|number of)\b", q):
        intent["aggregation"] = "COUNT"
    elif re.search(r"\b(how much|total|sum|overall)\b", q):
        intent["aggregation"] = "SUM"
    elif re.search(r"\b(average|mean|avg)\b", q):
        intent["aggregation"] = "AVG"

    # Limits & Rankings
    top_match = re.search(r"\btop\s+(\d+)\b", q)
    if top_match:
        intent["limit"] = int(top_match.group(1))
        intent["sorting"] = "DESC"
    elif re.search(r"\b(best|highest|top|most|maximum|greatest)\b", q):
        intent["limit"] = 1
        intent["sorting"] = "DESC"
    elif re.search(r"\b(lowest|worst|least|minimum|cheapest)\b", q):
        intent["limit"] = 1
        intent["sorting"] = "ASC"

    # Metrics
    if any(k in q for k in ["bought from us", "sales", "revenue", "turnover", "sold", "spent with us", "order value", "orders"]):
        intent["metrics"].append("sales value / revenue")
        intent["dimensions"].append("customer / party")
    elif any(k in q for k in ["we bought", "we spend", "we spent", "purchase", "bought from vendor", "bought from supplier", "procurement", "inward", "suppliers paid"]):
        intent["metrics"].append("purchase expenditure")
        intent["dimensions"].append("supplier")
    elif any(k in q for k in ["bought", "buying", "spent", "spending"]):
        # Default "who bought the most / who spent the most" -> customer sales
        intent["metrics"].append("sales value / revenue")
        intent["dimensions"].append("customer / party")

    if any(k in q for k in ["qty", "quantity", "volume", "units"]):
        intent["metrics"].append("quantity / units")
    if any(k in q for k in ["stock", "inventory", "on hand"]):
        intent["metrics"].append("stock on hand")
    if any(k in q for k in ["production", "produced", "manufactured", "output"]):
        intent["metrics"].append("production quantity")

    # Dimensions & Entities
    if any(k in q for k in ["customer", "client", "buyer", "party", "parties"]):
        if "customer / party" not in intent["dimensions"]:
            intent["dimensions"].append("customer / party")
    if any(k in q for k in ["supplier", "vendor"]):
        if "supplier" not in intent["dimensions"]:
            intent["dimensions"].append("supplier")
    if any(k in q for k in ["product", "item", "goods", "sku"]):
        intent["dimensions"].append("product")
    if any(k in q for k in ["category"]):
        intent["dimensions"].append("category")
    if any(k in q for k in ["lead", "leads", "inquiry", "inquiries", "prospect"]):
        intent["dimensions"].append("sales lead")
    if any(k in q for k in ["challan", "dispatch", "delivery", "shipping"]):
        intent["dimensions"].append("delivery challan")
    if any(k in q for k in ["month", "monthly"]):
        intent["dimensions"].append("month")

    # Filters & Statuses
    if any(k in q for k in ["open", "pending", "active", "in progress", "in-progress"]):
        intent["filters"].append("open / pending / in-progress")
    if any(k in q for k in ["verified", "unverified", "pending verification"]):
        intent["filters"].append("carton verification status")
    if any(k in q for k in ["shortfall", "fell short", "short"]):
        intent["filters"].append("actual output < planned target")
    if any(k in q for k in ["inactive", "haven't ordered", "no orders"]):
        intent["filters"].append("inactive (no recent orders)")

    return intent


def _build_scoped_schema_fallback(full_schema: str, query: str) -> str:
    """Build a concise, token-efficient subset of schema (max 6-8 tables) matching query intent."""
    if not full_schema:
        return ""
    full_ddls = _extract_table_ddl_map(full_schema)
    if not full_ddls:
        return full_schema[:3500]
    
    query_lower = query.lower()
    candidate_tables: list[str] = []
    
    glossary_text = _build_column_glossary_for_query(query)
    glossary_tables = set(re.findall(r'\b([a-zA-Z0-9_]+)\.[a-zA-Z0-9_]+', glossary_text))
    for t in glossary_tables:
        if t in full_ddls and t not in candidate_tables:
            candidate_tables.append(t)
    
    domain_rules = [
        (["order", "sales", "bought", "buying", "spent", "spending", "buyer", "customer", "client", "revenue", "turnover"], ["sales_order", "sales_order_products", "party", "product", "financial_year"]),
        (["purchase", "supplier", "vendor", "procure", "inward", "raw material"], ["purchase", "purchase_products", "party", "product", "financial_year"]),
        (["stock", "inventory", "warehouse", "carton", "on hand"], ["stock", "product", "product_color", "category"]),
        (["production", "manufacture", "batch", "machine", "yield", "output", "plant", "floor", "apq"], ["production", "actual_production", "machine", "product", "product_color"]),
        (["lead", "inquiry", "inquiries", "prospect", "followup", "deal", "pipeline"], ["lead", "lead_history", "users", "party"]),
        (["dispatch", "delivery", "challan", "shipment", "transporter", "vehicle", "driver"], ["delivery_challan", "delivery_challan_products", "party", "sales_order"]),
        (["proforma", "invoice", "bill", "gst", "tax", "quotation"], ["proforma", "quotation", "party", "financial_year"]),
        (["balance", "account", "ledger", "credit", "debit", "opening balance", "payment", "receipt"], ["party", "financial_year", "party_opening_balance", "sales_order", "receipt"]),
    ]
    for keywords, tbls in domain_rules:
        if any(k in query_lower for k in keywords):
            for t in tbls:
                if t in full_ddls and t not in candidate_tables:
                    candidate_tables.append(t)

    # Filter to candidate tables present in full_ddls
    valid_tables = [t for t in candidate_tables if t in full_ddls]
    
    # If no candidate matched the actual database tables (e.g. test fixture or custom DB), use available tables
    if not valid_tables:
        valid_tables = list(full_ddls.keys())[:8]
    else:
        valid_tables = valid_tables[:6]
        # 1-hop expansion for bridge tables
        neighbors = _get_1hop_neighbors(set(valid_tables))
        for n in sorted(neighbors):
            if n in full_ddls and n not in valid_tables and len(valid_tables) < 8:
                valid_tables.append(n)
            
    candidate_items = [
        {"table_name": t, "ddl": full_ddls[t], "source": "fallback"}
        for t in valid_tables if t in full_ddls
    ]
    selected, dropped = select_schema_within_budget(
        candidate_items,
        token_budget=DEFAULT_SCHEMA_TOKEN_BUDGET,
        id_key="table_name",
    )

    budgeted_schema = "\n\n".join(c["ddl"] for c in selected)
    original_schema = "\n\n".join(full_ddls[t] for t in valid_tables if t in full_ddls)
    estimated_tokens = estimate_schema_tokens(budgeted_schema)
    flag_enabled = is_feature_enabled("token_budget_enabled")
    stage_name = "schema_budget_applied" if flag_enabled else "schema_budget_shadow"

    log_telemetry(
        query_id="",
        stage=stage_name,
        input_tokens=estimated_tokens,
        extra={
            "original_table_count": len(candidate_items),
            "budgeted_table_count": len(selected),
            "estimated_tokens": estimated_tokens,
            "dropped_tables": [c["table_name"] for c in dropped],
            "token_budget_enabled": flag_enabled,
            "fallback": True,
        },
    )

    if is_feature_enabled("schema_compaction_enabled"):
        compact_ddls = [compact_ddl(c["ddl"]) for c in selected]
        raw_ddls = [c["ddl"] for c in selected]
        join_hints = extract_join_hints(raw_ddls)

        compacted_schema = "\n".join(compact_ddls)
        if join_hints:
            compacted_schema += "\n\n" + join_hints

        before_tokens = estimate_schema_tokens(budgeted_schema)
        after_tokens = estimate_schema_tokens(compacted_schema)

        log_telemetry(
            query_id="",
            stage="schema_compaction_applied",
            input_tokens=after_tokens,
            extra={
                "before_tokens": before_tokens,
                "after_tokens": after_tokens,
                "token_savings": max(0, before_tokens - after_tokens),
                "table_count": len(selected),
                "fallback": True,
            },
        )
        return compacted_schema

    if flag_enabled:
        return budgeted_schema
    return original_schema


_MAX_RESULT_CACHE_ENTRIES = 256


class SQLRetriever:
    """Generates and executes SQL queries for analytical questions."""
    _full_schema_cache: str | None = None
    _column_registry: ColumnRegistry | None = None
    # Bounded LRU cache for query results, keyed on normalized question text.
    _result_cache: OrderedDict[str, tuple[float, list[RetrievedChunk]]] = OrderedDict()

    def __init__(
        self,
        router: ProviderRouter,
        vector_store: QdrantStore | None = None,
        embedding_service: EmbeddingService | None = None,
    ) -> None:
        self._router = router
        self._vector_store = vector_store
        self._embeddings = embedding_service
        self._dialect = get_dialect_profile(settings.db_engine)
        self._glossary = _load_glossary()
        self._relationships = _load_relationships()
        self._pattern_learner = PatternLearner()
        self._confidence_scorer = ConfidenceScorer()
        self._result_validator = ResultValidator(_get_raw_behavioral_atlas() or {})
        self.last_infra_error: str | None = None
        self.last_query_status: str | None = None
        self.last_cot_plan: str | None = None
        self.last_confidence_score: float | None = None
        self.last_confidence_breakdown: ConfidenceBreakdown | None = None

    @classmethod
    def clear_result_cache(cls) -> None:
        """Clear the cached query results."""
        cls._result_cache.clear()

    async def retrieve(self, query: str) -> list[RetrievedChunk]:
        """Convert NL to SQL, execute, and return formatted results (with 1 retry)."""
        self.last_infra_error = None
        self.last_query_status = None
        self.last_cot_plan = None
        self.last_confidence_score = None
        self.last_confidence_breakdown = None
        cache_key = query.strip().lower()
        now = time.monotonic()

        cached = SQLRetriever._result_cache.get(cache_key)
        if cached is not None:
            cached_at, cached_chunks = cached
            if now - cached_at < settings.sql_result_cache_ttl_seconds:
                logger.info("SQL result cache hit for query: %s", query)
                SQLRetriever._result_cache.move_to_end(cache_key)
                self.last_query_status = "success"
                return [c.model_copy(deep=True) for c in cached_chunks]
            else:
                SQLRetriever._result_cache.pop(cache_key, None)

        result = await self._retrieve_uncached(query)
        # Only cache valid results when query executed successfully and no infra outage occurred.
        if self.last_infra_error is None and self.last_query_status in ("success", "empty_result") and result:
            while len(SQLRetriever._result_cache) >= _MAX_RESULT_CACHE_ENTRIES:
                SQLRetriever._result_cache.popitem(last=False)
            SQLRetriever._result_cache[cache_key] = (
                now,
                [c.model_copy(deep=True) for c in result],
            )
        return result

    async def _retrieve_uncached(self, query: str) -> list[RetrievedChunk]:
        qid = get_or_create_query_id()
        budget_ctrl = get_or_create_budget_controller(qid)

        if not budget_ctrl.can_proceed():
            logger.warning("Query budget exhausted before SQL retrieval for query %s", qid)
            log_telemetry(
                query_id=qid,
                stage="sql_generation",
                latency_ms=0.0,
                success=False,
                failure_type="budget_exceeded",
                extra={"budget_status": budget_ctrl.get_budget_status()},
            )
            self.last_query_status = "failed"
            return []

        with timed_stage("schema_retrieval") as schema_stage:
            schema = await self._get_schema(query)
            schema_stage["extra"] = {"schema_chars": len(schema)}

        if not schema:
            self.last_query_status = "not_applicable"
            return []

        # Feature Flag Gate: Surgical Delta Repair vs Original Full-Context Retry
        if is_feature_enabled("delta_repair_enabled"):
            return await self._retrieve_with_delta_repair(query, schema)

        last_error = None
        first_failed_sql: str | None = None
        first_error: str | None = None

        for attempt in range(3):
            with timed_stage("sql_generation") as gen_stage:
                sql = await self._generate_sql(query, schema, last_error)
                gen_stage["extra"] = {"attempt": attempt, "has_sql": bool(sql)}

            if not sql:
                self.last_query_status = "not_applicable" if self.last_infra_error is None else "failed"
                return []

            try:
                tables = _extract_table_names(sql, self._dialect.sqlglot_dialect)

                with timed_stage("sql_validation") as val_stage:
                    # --- 1. Column validation (catches hallucinated columns before DB) ---
                    if SQLRetriever._column_registry:
                        validation = SQLRetriever._column_registry.validate_columns(sql)
                        if not validation.is_valid:
                            logger.warning("Column validation failed: %s", validation.errors)
                            err_msg = "\n".join(validation.errors)
                            capture_sql_failure(
                                query_id="",
                                stage="sql_validation",
                                failed_sql=sql,
                                raw_error=err_msg,
                                error_type="sql_validation_error",
                                schema_tables=tables,
                            )
                            _log_pipeline_event(
                                "column_hallucination_caught",
                                {"sql": sql, "hallucinated": validation.hallucinated_columns,
                                 "errors": validation.errors},
                                query=query,
                            )
                            if first_failed_sql is None:
                                first_failed_sql = sql
                                first_error = err_msg
                            last_error = "Column validation failed:\n" + err_msg
                            val_stage["success"] = False
                            val_stage["failure_type"] = "sql_validation_error"
                            continue  # retry with feedback

                        # Alias validation (first attempt only — don't loop forever)
                        if attempt == 0:
                            alias_warnings = self._column_registry.validate_aliases(sql, query)
                            if alias_warnings:
                                logger.warning("Alias validation: %s", alias_warnings)
                                alias_err_msg = "\n".join(alias_warnings)
                                capture_sql_failure(
                                    query_id="",
                                    stage="sql_validation",
                                    failed_sql=sql,
                                    raw_error=alias_err_msg,
                                    error_type="sql_validation_error",
                                    schema_tables=tables,
                                )
                                _log_pipeline_event(
                                    "alias_hallucination_caught",
                                    {"sql": sql, "warnings": alias_warnings},
                                    query=query,
                                )
                                if first_failed_sql is None:
                                    first_failed_sql = sql
                                    first_error = alias_err_msg
                                last_error = "Alias quality issue:\n" + alias_err_msg
                                val_stage["success"] = False
                                val_stage["failure_type"] = "sql_validation_error"
                                continue

                    # --- 2. Semantic Correctness Validation ---
                    val_results = self._result_validator.validate_query(
                        sql=sql,
                        tables_involved=tables,
                        has_date_filter=("WHERE" in sql.upper() and any(k in sql.upper() for k in ["DATE", "YEAR", "CREATED_AT", "UPDATED_AT", "MONTH"])),
                        has_aggregation=any(f in sql.upper() for f in ["SUM(", "AVG(", "COUNT(", "MAX(", "MIN("]),
                    )
                    crit_errors = [r.message for r in val_results if r.severity == ValidationSeverity.CRITICAL and not r.passed]
                    if crit_errors:
                        logger.warning("Semantic validation critical errors: %s", crit_errors)
                        crit_err_msg = "\n".join(crit_errors)
                        capture_sql_failure(
                            query_id="",
                            stage="sql_validation",
                            failed_sql=sql,
                            raw_error=crit_err_msg,
                            error_type="sql_validation_error",
                            schema_tables=tables,
                        )
                        _log_pipeline_event("semantic_validation_failed", {"sql": sql, "errors": crit_errors}, query=query)
                        if first_failed_sql is None:
                            first_failed_sql = sql
                            first_error = crit_err_msg
                        last_error = "Semantic validation failed:\n" + crit_err_msg
                        val_stage["success"] = False
                        val_stage["failure_type"] = "sql_validation_error"
                        continue

                    # --- 3. Safety validation (AST parsing) ---
                    if not self._is_safe_read_query(sql):
                        capture_sql_failure(
                            query_id="",
                            stage="sql_validation",
                            failed_sql=sql,
                            raw_error=f"Unsafe or unparseable SQL generated: {sql}",
                            error_type="sql_validation_error",
                            schema_tables=tables,
                        )
                        _log_pipeline_event(
                            "unsafe_sql_blocked",
                            {"sql": sql},
                            query=query,
                        )
                        val_stage["success"] = False
                        val_stage["failure_type"] = "sql_validation_error"
                        raise UnsafeQueryError(f"Unsafe or unparseable SQL generated: {sql}")

                # --- 4. Execute Read-Only Query ---
                with timed_stage("sql_execution") as exec_stage:
                    rows = await run_readonly_query(sql)
                    is_zero_rows = len(rows) == 0
                    is_agg_zero = _is_aggregate_over_zero_rows(sql, rows, self._dialect.sqlglot_dialect)
                    is_empty_result = is_zero_rows or is_agg_zero
                    exec_stage["extra"] = {
                        "rows_returned": len(rows),
                        "empty_result": is_empty_result,
                    }
                    if is_empty_result:
                        exec_stage["failure_type"] = "empty_result"

                # If the query returned 0 rows or an all-NULL aggregate on early attempts,
                # give the LLM one retry opportunity to check JOIN/WHERE conditions
                if is_empty_result and attempt < 1:
                    last_error = (
                        "Query executed successfully but returned 0 rows or NULL aggregate. "
                        "If that's surprising given the question, double-check your JOIN "
                        "and WHERE conditions."
                    )
                    if first_failed_sql is None:
                        first_failed_sql = sql
                        first_error = last_error
                    continue

                # --- 5. Result Sanity & Confidence Scoring ---
                self._result_validator.validate_results(rows)
                learned_matches = self._pattern_learner.get_patterns_for_query(query)
                conf = self._confidence_scorer.calculate(
                    pattern_matches=len(learned_matches),
                    validation_results=val_results,
                    reflexion_attempts=attempt,
                    query_complexity={"join_count": max(0, len(tables) - 1), "subquery_depth": sql.upper().count("SELECT") - 1},
                )
                self.last_confidence_score = conf.final_score
                self.last_confidence_breakdown = conf

                # If query succeeded after a previous failed attempt, capture the fix!
                if attempt > 0 and first_failed_sql:
                    try:
                        self._pattern_learner.capture_success(
                            user_question=query,
                            original_cot="",
                            failed_sql=first_failed_sql,
                            error_message=first_error or "Previous attempt error",
                            fixed_sql=sql,
                            revised_cot=self.last_cot_plan or "",
                        )
                    except Exception as learn_err:
                        logger.debug("Failed to record learned pattern: %s", learn_err)

                # Set query status:
                # - empty_result: 0 rows returned or aggregate over 0 matching rows
                # - success: matching row(s) returned (including single rows with NULL field values)
                self.last_query_status = "empty_result" if is_empty_result else "success"

                label = f"live_database ({', '.join(tables)})" if tables else "live_database"
                formatted_table = _format_rows_as_markdown(rows, sql, is_agg_zero=is_agg_zero)

                # Wrap in a RetrievedChunk
                chunk = Chunk(
                    chunk_id="live_sql_001",
                    document_id="live_db",
                    chunk_type=ChunkType.SQL_RESULT,
                    content=formatted_table,
                    document_type=DocumentType.GENERAL,
                    source_file=label,
                )

                _log_pipeline_event(
                    "sql_success",
                    {"sql": sql, "row_count": len(rows), "tables": tables,
                     "attempt": attempt + 1, "is_empty_result": is_empty_result,
                     "confidence_score": self.last_confidence_score},
                    query=query,
                )
                return [RetrievedChunk(chunk=chunk, score=1.0, retrieval_method="text-to-sql")]

            except UnsafeQueryError as e:
                # Security violations die instantly. No feedback loop.
                logger.warning(f"Blocked unsafe SQL query: {e}")
                capture_sql_failure(
                    query_id="",
                    stage="sql_validation",
                    failed_sql=sql,
                    raw_error=str(e),
                    error_type="sql_validation_error",
                    schema_tables=tables if 'tables' in locals() else [],
                )
                self.last_query_status = "failed"
                return []
            except Exception as e:
                logger.error(f"SQL Execution failed on attempt {attempt + 1}: {e}")
                capture_sql_failure(
                    query_id="",
                    stage="sql_execution",
                    failed_sql=sql,
                    raw_error=str(e),
                    error_type=classify_error(e),
                    schema_tables=tables if 'tables' in locals() else [],
                )
                _log_pipeline_event(
                    "execution_error_caught",
                    {"sql": sql, "error": str(e), "attempt": attempt + 1},
                    query=query,
                )
                if first_failed_sql is None:
                    first_failed_sql = sql
                    first_error = str(e)
                last_error = str(e)

        # If we exhausted retries, fail cleanly
        logger.warning("SQL generation failed after retry loop. Returning empty results.")
        self.last_query_status = "failed"
        _log_pipeline_event("retry_exhausted", {"last_error": last_error}, query=query)
        return []

    async def _retrieve_with_delta_repair(self, query: str, schema: str) -> list[RetrievedChunk]:
        """Execute text-to-sql retrieval with targeted Delta Repair on validation/execution failure."""
        with timed_stage("sql_generation") as gen_stage:
            sql = await self._generate_sql(query, schema, None)
            gen_stage["extra"] = {"attempt": 0, "has_sql": bool(sql), "delta_repair_enabled": True}

        if not sql:
            self.last_query_status = "not_applicable" if self.last_infra_error is None else "failed"
            return []

        current_sql = sql
        first_failed_sql: str | None = None
        first_error: str | None = None

        for repair_attempt in range(MAX_DELTA_REPAIR_ATTEMPTS + 1):
            tables = _extract_table_names(current_sql, self._dialect.sqlglot_dialect)
            schema_context = extract_schema_context_from_ddl(schema, tables)

            val_error: str | None = None
            val_error_type: str | None = None

            with timed_stage("sql_validation") as val_stage:
                # 0. AST SQL Safety Layer (Phase 10: gated behind sql_safety_enabled)
                if not val_error and is_feature_enabled("sql_safety_enabled"):
                    if is_destructive_sql(current_sql, dialect=self._dialect.sqlglot_dialect):
                        logger.warning("Destructive SQL blocked: %s", current_sql)
                        val_error = "Destructive or write SQL operation detected. Only read-only SELECT queries are allowed."
                        val_error_type = "destructive_sql_error"
                    else:
                        danger_warns = check_dangerous_patterns(current_sql, dialect=self._dialect.sqlglot_dialect)
                        if danger_warns:
                            logger.warning("Dangerous SQL pattern blocked: %s", danger_warns)
                            val_error = "\n".join(danger_warns)
                            val_error_type = "dangerous_pattern_error"
                        elif schema_context:
                            is_valid_schema, schema_err = validate_tables_and_columns(
                                current_sql, schema_context, dialect=self._dialect.sqlglot_dialect
                            )
                            if not is_valid_schema:
                                logger.warning("Schema table/column validation failed: %s", schema_err)
                                val_error = schema_err
                                val_error_type = "column_not_found" if "Column" in schema_err else "table_not_found"

                    if val_error:
                        val_stage["success"] = False
                        val_stage["failure_type"] = "sql_validation_error"
                        capture_sql_failure(
                            query_id="",
                            stage="sql_validation" if repair_attempt == 0 else "sql_repair",
                            failed_sql=current_sql,
                            raw_error=val_error,
                            error_type="sql_validation_error",
                            schema_tables=tables,
                        )
                        _log_pipeline_event(
                            "sql_safety_validation_failed",
                            {"sql": current_sql, "error": val_error, "error_type": val_error_type, "repair_attempt": repair_attempt},
                            query=query,
                        )

                # 1. Column validation
                if not val_error and SQLRetriever._column_registry:
                    validation = SQLRetriever._column_registry.validate_columns(current_sql)
                    if not validation.is_valid:
                        logger.warning("Column validation failed (repair attempt %d): %s", repair_attempt, validation.errors)
                        val_error = "\n".join(validation.errors)
                        val_error_type = "column_hallucination"
                        val_stage["success"] = False
                        val_stage["failure_type"] = "sql_validation_error"
                        capture_sql_failure(
                            query_id="",
                            stage="sql_validation" if repair_attempt == 0 else "sql_repair",
                            failed_sql=current_sql,
                            raw_error=val_error,
                            error_type="sql_validation_error",
                            schema_tables=tables,
                        )
                        _log_pipeline_event(
                            "column_hallucination_caught",
                            {"sql": current_sql, "hallucinated": validation.hallucinated_columns,
                             "errors": validation.errors, "repair_attempt": repair_attempt},
                            query=query,
                        )

                # 2. Alias validation (on attempt 0)
                if not val_error and repair_attempt == 0 and SQLRetriever._column_registry:
                    alias_warnings = self._column_registry.validate_aliases(current_sql, query)
                    if alias_warnings:
                        logger.warning("Alias validation: %s", alias_warnings)
                        val_error = "\n".join(alias_warnings)
                        val_error_type = "alias_hallucination"
                        val_stage["success"] = False
                        val_stage["failure_type"] = "sql_validation_error"
                        capture_sql_failure(
                            query_id="",
                            stage="sql_validation",
                            failed_sql=current_sql,
                            raw_error=val_error,
                            error_type="sql_validation_error",
                            schema_tables=tables,
                        )
                        _log_pipeline_event(
                            "alias_hallucination_caught",
                            {"sql": current_sql, "warnings": alias_warnings},
                            query=query,
                        )

                # 3. Semantic validation
                if not val_error:
                    val_results = self._result_validator.validate_query(
                        sql=current_sql,
                        tables_involved=tables,
                        has_date_filter=("WHERE" in current_sql.upper() and any(k in current_sql.upper() for k in ["DATE", "YEAR", "CREATED_AT", "UPDATED_AT", "MONTH"])),
                        has_aggregation=any(f in current_sql.upper() for f in ["SUM(", "AVG(", "COUNT(", "MAX(", "MIN("]),
                    )
                    crit_errors = [r.message for r in val_results if r.severity == ValidationSeverity.CRITICAL and not r.passed]
                    if crit_errors:
                        logger.warning("Semantic validation critical errors (repair attempt %d): %s", repair_attempt, crit_errors)
                        val_error = "\n".join(crit_errors)
                        val_error_type = "semantic_validation_error"
                        val_stage["success"] = False
                        val_stage["failure_type"] = "sql_validation_error"
                        capture_sql_failure(
                            query_id="",
                            stage="sql_validation" if repair_attempt == 0 else "sql_repair",
                            failed_sql=current_sql,
                            raw_error=val_error,
                            error_type="sql_validation_error",
                            schema_tables=tables,
                        )
                        _log_pipeline_event(
                            "semantic_validation_failed",
                            {"sql": current_sql, "errors": crit_errors, "repair_attempt": repair_attempt},
                            query=query,
                        )

                # 4. AST safety validation
                if not val_error and not self._is_safe_read_query(current_sql):
                    logger.warning("Unsafe SQL generated: %s", current_sql)
                    val_stage["success"] = False
                    val_stage["failure_type"] = "sql_validation_error"
                    capture_sql_failure(
                        query_id="",
                        stage="sql_validation" if repair_attempt == 0 else "sql_repair",
                        failed_sql=current_sql,
                        raw_error=f"Unsafe or unparseable SQL generated: {current_sql}",
                        error_type="sql_validation_error",
                        schema_tables=tables,
                    )
                    _log_pipeline_event(
                        "unsafe_sql_blocked",
                        {"sql": current_sql, "repair_attempt": repair_attempt},
                        query=query,
                    )
                    raise UnsafeQueryError(f"Unsafe or unparseable SQL generated: {current_sql}")

            # If validation failed, invoke Delta Repair if under attempt budget
            if val_error:
                if first_failed_sql is None:
                    first_failed_sql = current_sql
                    first_error = val_error

                if repair_attempt >= MAX_DELTA_REPAIR_ATTEMPTS:
                    logger.warning("Delta repair ceiling (%d attempts) reached on validation failure.", MAX_DELTA_REPAIR_ATTEMPTS)
                    break

                next_attempt = repair_attempt + 1
                repaired_sql = await attempt_delta_repair(
                    router=self._router,
                    failed_sql=current_sql,
                    error_message=val_error,
                    error_type=val_error_type or "sql_validation_error",
                    schema_context=schema_context,
                    user_intent=query,
                    attempt_number=next_attempt,
                )
                if not repaired_sql:
                    logger.warning("Delta repair attempt %d returned no SQL. Halting.", next_attempt)
                    break

                current_sql = repaired_sql
                continue

            # Validation succeeded -> Execute read-only query
            try:
                with timed_stage("sql_execution") as exec_stage:
                    rows = await run_readonly_query(current_sql)
                    is_zero_rows = len(rows) == 0
                    is_agg_zero = _is_aggregate_over_zero_rows(current_sql, rows, self._dialect.sqlglot_dialect)
                    is_empty_result = is_zero_rows or is_agg_zero
                    exec_stage["extra"] = {
                        "rows_returned": len(rows),
                        "empty_result": is_empty_result,
                        "repair_attempt": repair_attempt,
                    }
                    if is_empty_result:
                        exec_stage["failure_type"] = "empty_result"

                # Intelligent 0-row handling (Phase 11: gated behind zero_row_handling_enabled)
                if is_empty_result and is_feature_enabled("zero_row_handling_enabled"):
                    classification = classify_empty_result(current_sql, dialect=self._dialect.sqlglot_dialect)
                    with timed_stage("empty_result_handling") as erh_stage:
                        erh_stage["extra"] = {
                            "classification": classification,
                            "sql": current_sql,
                            "rows_returned": len(rows),
                            "repair_attempt": repair_attempt,
                        }
                        if classification == "valid_empty":
                            erh_stage["success"] = True
                            _log_pipeline_event(
                                "valid_empty_result",
                                {"sql": current_sql, "classification": "valid_empty", "rows_returned": len(rows)},
                                query=query,
                            )
                            # Valid empty: bypass retry/repair loop immediately, do NOT capture failure
                        elif classification == "suspicious_empty":
                            erh_stage["success"] = False
                            erh_stage["failure_type"] = "suspicious_zero_rows"
                            if repair_attempt < MAX_DELTA_REPAIR_ATTEMPTS:
                                logger.warning("Suspicious 0-row result on attempt %d: triggering Delta Repair.", repair_attempt)
                                _log_pipeline_event(
                                    "suspicious_empty_result_repair",
                                    {"sql": current_sql, "classification": "suspicious_empty", "repair_attempt": repair_attempt},
                                    query=query,
                                )
                                if first_failed_sql is None:
                                    first_failed_sql = current_sql
                                    first_error = "Query executed successfully but returned 0 rows (suspicious_empty)."

                                next_attempt = repair_attempt + 1
                                repaired_sql = await attempt_delta_repair(
                                    router=self._router,
                                    failed_sql=current_sql,
                                    error_message="Query executed successfully but returned 0 rows. Classification: suspicious_empty. Check JOIN conditions and filter logic.",
                                    error_type="suspicious_zero_rows",
                                    schema_context=schema_context,
                                    user_intent=query,
                                    attempt_number=next_attempt,
                                )
                                if repaired_sql and repaired_sql != current_sql:
                                    current_sql = repaired_sql
                                    continue

                # Result Sanity & Confidence Scoring
                self._result_validator.validate_results(rows)
                learned_matches = self._pattern_learner.get_patterns_for_query(query)
                conf = self._confidence_scorer.calculate(
                    pattern_matches=len(learned_matches),
                    validation_results=val_results,
                    reflexion_attempts=repair_attempt,
                    query_complexity={"join_count": max(0, len(tables) - 1), "subquery_depth": current_sql.upper().count("SELECT") - 1},
                )
                self.last_confidence_score = conf.final_score
                self.last_confidence_breakdown = conf

                if repair_attempt > 0 and first_failed_sql:
                    try:
                        self._pattern_learner.capture_success(
                            user_question=query,
                            original_cot="",
                            failed_sql=first_failed_sql,
                            error_message=first_error or "Previous attempt error",
                            fixed_sql=current_sql,
                            revised_cot=self.last_cot_plan or "",
                        )
                    except Exception as learn_err:
                        logger.debug("Failed to record learned pattern: %s", learn_err)

                self.last_query_status = "empty_result" if is_empty_result else "success"
                label = f"live_database ({', '.join(tables)})" if tables else "live_database"
                formatted_table = _format_rows_as_markdown(rows, current_sql, is_agg_zero=is_agg_zero)

                chunk = Chunk(
                    chunk_id="live_sql_001",
                    document_id="live_db",
                    chunk_type=ChunkType.SQL_RESULT,
                    content=formatted_table,
                    document_type=DocumentType.GENERAL,
                    source_file=label,
                )

                _log_pipeline_event(
                    "sql_success",
                    {"sql": current_sql, "row_count": len(rows), "tables": tables,
                     "repair_attempts": repair_attempt, "is_empty_result": is_empty_result,
                     "confidence_score": self.last_confidence_score},
                    query=query,
                )
                return [RetrievedChunk(chunk=chunk, score=1.0, retrieval_method="text-to-sql")]

            except UnsafeQueryError as e:
                logger.warning(f"Blocked unsafe SQL query: {e}")
                self.last_query_status = "failed"
                return []
            except Exception as e:
                logger.error("SQL Execution failed on attempt %d: %s", repair_attempt + 1, e)
                capture_sql_failure(
                    query_id="",
                    stage="sql_execution" if repair_attempt == 0 else "sql_repair",
                    failed_sql=current_sql,
                    raw_error=str(e),
                    error_type=classify_error(e),
                    schema_tables=tables,
                )
                _log_pipeline_event(
                    "execution_error_caught",
                    {"sql": current_sql, "error": str(e), "repair_attempt": repair_attempt + 1},
                    query=query,
                )
                if first_failed_sql is None:
                    first_failed_sql = current_sql
                    first_error = str(e)

                if repair_attempt >= MAX_DELTA_REPAIR_ATTEMPTS:
                    logger.warning("Delta repair ceiling (%d attempts) reached on execution error.", MAX_DELTA_REPAIR_ATTEMPTS)
                    break

                next_attempt = repair_attempt + 1
                repaired_sql = await attempt_delta_repair(
                    router=self._router,
                    failed_sql=current_sql,
                    error_message=str(e),
                    error_type=classify_error(e),
                    schema_context=schema_context,
                    user_intent=query,
                    attempt_number=next_attempt,
                )
                if not repaired_sql:
                    logger.warning("Delta repair attempt %d returned no SQL after exec error. Halting.", next_attempt)
                    break

                current_sql = repaired_sql
                continue

        logger.warning("SQL generation failed after Delta Repair attempts. Returning empty results.")
        self.last_query_status = "failed"
        _log_pipeline_event("retry_exhausted", {"last_error": first_error}, query=query)
        return []

    @classmethod
    def clear_schema_cache(cls) -> None:
        """Clear the cached full schema and column registry (e.g. after schema sync)."""
        cls._full_schema_cache = None
        cls._column_registry = None

    async def _fetch_full_schema(self) -> str:
        """Fetch the full, un-truncated DB schema to initialize the ColumnRegistry."""
        if SQLRetriever._full_schema_cache is not None:
            return SQLRetriever._full_schema_cache

        try:
            rows = await run_readonly_query(self._dialect.schema_query, max_rows=20000)
            schema = format_schema_rows(self._dialect, rows)

            if self._dialect.key == "mysql" and self._dialect.fk_query:
                fk_rows = await run_readonly_query(self._dialect.fk_query, max_rows=20000)
            elif self._dialect.key == "sqlite":
                fk_rows = await fetch_sqlite_foreign_keys()
            else:
                fk_rows = []

            fk_text = format_fk_rows(fk_rows)
            full_schema = schema + ("\n\n" + fk_text if fk_text else "")

            # Only cache and build registry if the schema was successfully retrieved and non-empty.
            # An empty string from a missing/unready DB must never be cached as permanent truth.
            if full_schema.strip():
                SQLRetriever._full_schema_cache = full_schema
                try:
                    SQLRetriever._column_registry = ColumnRegistry(
                        full_schema, self._dialect.sqlglot_dialect
                    )
                except Exception as reg_err:
                    logger.warning("Failed to build column registry: %s", reg_err)

            return full_schema
        except Exception as e:
            logger.error("Failed to fetch full schema: %s", e)
            return ""

    async def _get_schema(self, query: str) -> str:
        """Fetch relevant DB schema chunks for the prompt using Schema RAG.
        
        If vector_store is missing or fails, falls back to an intelligent, token-bounded schema.
        """
        # Ensure the full schema is cached and registry is built.
        full_schema = await self._fetch_full_schema()

        if not self._vector_store or not self._embeddings:
            return _build_scoped_schema_fallback(full_schema, query)

        try:
            dense_vec, sparse_vec = await self._embeddings.embed_query(query)
            chunks = await self._vector_store.search_hybrid(
                query_vector=dense_vec,
                sparse_vector=sparse_vec,
                query_text=query,
                top_k=8,
                filters={"chunk_type": ChunkType.SQL_SCHEMA.value},
            )
            
            if not chunks:
                logger.warning("Schema RAG returned 0 chunks. Falling back to scoped schema.")
                return _build_scoped_schema_fallback(full_schema, query)
                
            # Combine the retrieved CREATE TABLE statements
            retrieved_schema = "\n\n".join(chunk.chunk.content for chunk in chunks)
            retrieved_tables = _extract_schema_table_names(retrieved_schema)

            # Seed anchor tables from matched glossary terms & domain concepts
            glossary_text = _build_column_glossary_for_query(query)
            glossary_tables = set(re.findall(r'\b([a-zA-Z0-9_]+)\.[a-zA-Z0-9_]+', glossary_text))

            query_lower = query.lower()
            if any(k in query_lower for k in ["order", "sales", "bought", "buying", "spent", "spending", "buyer", "customer", "client", "revenue", "turnover"]):
                glossary_tables.update(["sales_order", "sales_order_products", "party", "product", "financial_year"])
            if any(k in query_lower for k in ["purchase", "supplier", "vendor", "procure", "inward", "raw material"]):
                glossary_tables.update(["purchase", "purchase_products", "party", "product", "financial_year"])
            if any(k in query_lower for k in ["stock", "inventory", "warehouse", "carton", "on hand"]):
                glossary_tables.update(["stock", "product", "product_color", "category"])
            if any(k in query_lower for k in ["production", "manufacture", "batch", "machine", "yield", "output", "plant", "floor", "apq"]):
                glossary_tables.update(["production", "actual_production", "machine", "product", "product_color"])
            if any(k in query_lower for k in ["lead", "inquiry", "inquiries", "prospect", "followup", "deal", "pipeline"]):
                glossary_tables.update(["lead", "lead_history", "users", "party"])
            if any(k in query_lower for k in ["dispatch", "delivery", "challan", "shipment", "transporter", "vehicle", "driver"]):
                glossary_tables.update(["delivery_challan", "delivery_challan_products", "party", "sales_order"])
            if any(k in query_lower for k in ["proforma", "invoice", "bill", "gst", "tax", "quotation"]):
                glossary_tables.update(["proforma", "quotation", "party", "financial_year"])
            if any(k in query_lower for k in ["balance", "account", "ledger", "credit", "debit", "opening balance", "payment", "receipt"]):
                glossary_tables.update(["party", "financial_year", "party_opening_balance", "sales_order", "receipt"])

            full_ddls = _extract_table_ddl_map(full_schema) if full_schema else {}
            candidate_list: list[dict[str, Any]] = []
            seen_tables: set[str] = set()

            for chunk in chunks:
                tbls = _extract_schema_table_names(chunk.chunk.content)
                for tbl in tbls:
                    if tbl not in seen_tables:
                        seen_tables.add(tbl)
                        candidate_list.append({
                            "table_name": tbl,
                            "ddl": chunk.chunk.content,
                            "source": "vector_rag",
                        })

            anchor_extra = []
            for g_table in sorted(glossary_tables):
                if g_table not in retrieved_tables and g_table in full_ddls:
                    anchor_extra.append(full_ddls[g_table])
                    retrieved_tables.add(g_table)
                if g_table not in seen_tables and g_table in full_ddls:
                    seen_tables.add(g_table)
                    candidate_list.append({
                        "table_name": g_table,
                        "ddl": full_ddls[g_table],
                        "source": "domain_anchor",
                    })

            if anchor_extra:
                retrieved_schema += "\n\n-- Domain Anchor & Glossary Tables:\n" + "\n\n".join(anchor_extra)

            # 1-hop graph expansion: add directly connected neighbor tables if missing
            neighbors = _get_1hop_neighbors(retrieved_tables)
            needed_neighbors = neighbors - retrieved_tables

            if needed_neighbors and full_ddls:
                # Rank neighbors by how many active tables they connect to (bridge priority)
                raw_rels = _get_raw_relationships()
                conn_scores = {}
                for r in raw_rels:
                    frm = (r.get("from_table") or "").lower()
                    to = (r.get("to_table") or "").lower()
                    if frm in retrieved_tables and to in needed_neighbors:
                        conn_scores[to] = conn_scores.get(to, 0) + 1
                    if to in retrieved_tables and frm in needed_neighbors:
                        conn_scores[frm] = conn_scores.get(frm, 0) + 1

                ranked_neighbors = sorted(needed_neighbors, key=lambda t: conn_scores.get(t, 0), reverse=True)
                added = 0
                extra_ddls = []
                for n_table in ranked_neighbors:
                    if n_table in full_ddls and added < 4:
                        extra_ddls.append(full_ddls[n_table])
                        added += 1
                    if n_table in full_ddls and n_table not in seen_tables:
                        seen_tables.add(n_table)
                        candidate_list.append({
                            "table_name": n_table,
                            "ddl": full_ddls[n_table],
                            "source": "graph_expansion",
                        })
                if extra_ddls:
                    retrieved_schema += "\n\n-- Directly connected related tables:\n" + "\n\n".join(extra_ddls)

            # --- Phase 8: Dynamic Schema Token Budget Selection & Shadow Mode ---
            selected, dropped = select_schema_within_budget(
                candidate_list,
                token_budget=DEFAULT_SCHEMA_TOKEN_BUDGET,
                id_key="table_name",
            )

            original_table_count = len(candidate_list)
            budgeted_table_count = len(selected)
            dropped_tables = [c["table_name"] if isinstance(c, dict) else str(c) for c in dropped]
            budgeted_schema = "\n\n".join(c["ddl"] if isinstance(c, dict) else str(c) for c in selected)
            estimated_tokens = estimate_schema_tokens(budgeted_schema)
            flag_enabled = is_feature_enabled("token_budget_enabled")
            stage_name = "schema_budget_applied" if flag_enabled else "schema_budget_shadow"

            log_telemetry(
                query_id="",
                stage=stage_name,
                input_tokens=estimated_tokens,
                extra={
                    "original_table_count": original_table_count,
                    "budgeted_table_count": budgeted_table_count,
                    "estimated_tokens": estimated_tokens,
                    "dropped_tables": dropped_tables,
                    "token_budget_enabled": flag_enabled,
                },
            )

            if is_feature_enabled("schema_compaction_enabled"):
                dialect_key = self._dialect.key if hasattr(self, "_dialect") and self._dialect else None
                compact_ddls = [
                    compact_ddl(c["ddl"] if isinstance(c, dict) else str(c), dialect=dialect_key)
                    for c in selected
                ]
                raw_ddls = [c["ddl"] if isinstance(c, dict) else str(c) for c in selected]
                join_hints = extract_join_hints(raw_ddls, dialect=dialect_key)

                compacted_schema = "\n".join(compact_ddls)
                if join_hints:
                    compacted_schema += "\n\n" + join_hints

                before_tokens = estimate_schema_tokens(budgeted_schema)
                after_tokens = estimate_schema_tokens(compacted_schema)

                log_telemetry(
                    query_id="",
                    stage="schema_compaction_applied",
                    input_tokens=after_tokens,
                    extra={
                        "before_tokens": before_tokens,
                        "after_tokens": after_tokens,
                        "token_savings": max(0, before_tokens - after_tokens),
                        "table_count": len(selected),
                        "has_join_hints": bool(join_hints),
                    },
                )
                return compacted_schema

            if flag_enabled:
                return budgeted_schema
            return retrieved_schema
            
        except Exception as e:
            logger.error("Schema RAG search failed: %s", e)
            return _build_scoped_schema_fallback(full_schema, query)

    async def _generate_sql(self, query: str, schema: str, last_error: str | None = None) -> str:
        """Prompt the reasoning LLM to generate SQL."""
        import datetime
        current_date_str = datetime.date.today().isoformat()
        intent = extract_analytical_intent(query)
        intent_summary_lines = []
        if intent["metrics"]:
            intent_summary_lines.append(f"- Metrics: {', '.join(intent['metrics'])}")
        if intent["dimensions"]:
            intent_summary_lines.append(f"- Dimensions: {', '.join(intent['dimensions'])}")
        if intent["filters"]:
            intent_summary_lines.append(f"- Filters: {', '.join(intent['filters'])}")
        if intent["time_period"]:
            intent_summary_lines.append(f"- Time Period: {intent['time_period']}")
        if intent["aggregation"]:
            intent_summary_lines.append(f"- Aggregation: {intent['aggregation']}")
        if intent["limit"]:
            intent_summary_lines.append(f"- Limit: {intent['limit']} (Sorting: {intent['sorting'] or 'DESC'})")

        intent_section = (
            "\nExtracted Business Intent:\n" + "\n".join(intent_summary_lines) + "\n"
            if intent_summary_lines
            else ""
        )
        
        schema_tables = _extract_schema_table_names(schema)
        behavioral_atlas_text = _build_behavioral_atlas_for_query(schema_tables, query)
        column_glossary = _build_column_glossary_for_query(query)

        system_prompt = f"""You are Global Mind, an expert Enterprise Business Intelligence Agent for {self._dialect.name}.
Your goal is to translate the business question into a valid, executable, read-only {self._dialect.name} SELECT query.

Respond with valid JSON:
{{
  "intent": "summary_of_intent",
  "tables": ["table1"],
  "joins": [],
  "filters": ["status = 'Y'", "deleted_at IS NULL"],
  "sql": "SELECT COUNT(id) AS total_customers FROM party WHERE status = 'Y' AND deleted_at IS NULL;"
}}

Rules:
- Read-Only: SELECT statements only. If the schema cannot answer, respond with exactly NO_SQL.
- Soft Delete: Filter out soft-deleted records (WHERE alias.deleted_at IS NULL) on all tables with a deleted_at column.
- Casting: Use CAST(col AS DECIMAL(10,2)) for numeric operations on VARCHAR columns (e.g. stock.qty).
- Aliases: Use descriptive aliases (e.g. AS customer_name, AS total_revenue). Never return raw IDs without names.
- Status Flags: Active='Y', Inactive='N'. Stock booked='B', dispatched='D'.
- Customer vs Supplier: In party table, join to sales_order for Customers, or purchase for Suppliers.
- Current Date: {current_date_str} (Use for relative date calculations like 'this year', 'last month').

{intent_section}
Schema:
{schema}
"""
        system_prompt += self._OUTPUT_READABILITY_RULES

        if behavioral_atlas_text:
            system_prompt += (
                "\n\n=== BEHAVIORAL SCHEMA ATLAS & COGNITIVE ONTOLOGY ===\n"
                f"{behavioral_atlas_text}"
            )

        scoped_rels = _format_scoped_relationships(schema_tables, query) if schema_tables else ""
        rels_to_inject = scoped_rels or self._relationships
        if rels_to_inject:
            system_prompt += (
                f"\n\nTable relationships:\n{rels_to_inject}"
            )

        if column_glossary:
            system_prompt += (
                "\n\nColumn mapping (use these exact paths — do NOT invent columns):\n"
                f"{column_glossary}"
            )
        if self._dialect.date_functions:
            system_prompt += (
                f"\n\nDate/time syntax for {self._dialect.name}:\n"
                f"{self._dialect.date_functions}"
            )
        if hasattr(self, "_pattern_learner") and self._pattern_learner:
            learned_patterns = self._pattern_learner.get_patterns_for_query(query)
            if learned_patterns:
                # SlimSQL Task 4: Cap to top 1 canonical pattern to minimize tokens
                pattern = learned_patterns[0]
                pattern_text = f"- Scenario: {pattern.business_scenario}\n  Reasoning: {pattern.cot_reasoning_snippet}\n  Template: `{pattern.sql_structure_template}`"
                system_prompt += f"\n\n=== RELEVANT LEARNED SQL PATTERN ===\n{pattern_text}"

        if last_error:
            system_prompt += f"\n\nWARNING: Your previous attempt failed with this error: {last_error}\nPlease fix the SQL query and try again."
        
        budget_ctrl = get_or_create_budget_controller()
        initial_calls = budget_ctrl.llm_calls if budget_ctrl else 0
        try:
            response = await self._router.chat(
                task="reasoning",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": query},
                ],
                max_tokens=2048
            )
            if budget_ctrl and budget_ctrl.llm_calls == initial_calls:
                budget_ctrl.record_call(tokens_used=250, is_repair=False)
            
            raw = (response or "").strip()

            # Abstention: the model may decorate the sentinel ("NO_SQL.",
            # "NO_SQL - the schema has no ...", or fenced). Any reply whose first
            # token is NO_SQL is an abstain, not a query to run.
            if _ABSTAIN_RE.match(raw):
                return ""

            # Extract structured plan and clean SQL
            cot_plan, sql = extract_cot_and_sql(raw)
            self.last_cot_plan = cot_plan
            if not sql or _ABSTAIN_RE.match(sql):
                return ""

            # Safeguard 2: Join Complexity Heuristic Check (Quality Gate)
            try:
                ast_check = sqlglot.parse_one(sql, read=self._dialect.sqlglot_dialect)
                tables_in_sql = list(ast_check.find_all(exp.Table))
                if len(tables_in_sql) >= 3:
                    for join_node in ast_check.find_all(exp.Join):
                        if not join_node.args.get("on") and not join_node.args.get("using"):
                            logger.warning("Multi-table query missing ON condition in JOIN — routing to Delta Repair.")
                            repaired = await attempt_delta_repair(
                                sql=sql,
                                error_message="Multi-table join missing explicit ON condition connecting tables.",
                                schema=schema,
                                dialect=self._dialect.name,
                                router=self._router,
                            )
                            if repaired:
                                return repaired
            except Exception as ast_e:
                logger.debug("AST join check passed/skipped: %s", ast_e)

            return sql
        except (TokenBudgetExceededError, QueryBudgetExceededError) as budget_err:
            err_count = getattr(budget_err, "count", budget_ctrl.get_current_usage() if budget_ctrl else 8000)
            err_limit = getattr(budget_err, "limit", budget_ctrl.max_tokens if budget_ctrl else 8000)
            logger.warning(
                "Budget hit at %d tokens (limit: %d). Increasing limit by +1K and attempting compressed retry...",
                err_count,
                err_limit,
            )
            if budget_ctrl:
                budget_ctrl.increase_limit(1000)

            try:
                compressed_prompt = (
                    f"You are an expert SQL generator for {self._dialect.name}. "
                    "Output ONLY the final SQL query in a ```sql ... ``` code block. "
                    "Strictly NO explanations, NO markdown prose, NO chain-of-thought.\n\n"
                    f"Schema:\n{schema}"
                )
                response = await self._router.chat(
                    task="reasoning",
                    messages=[
                        {"role": "system", "content": compressed_prompt},
                        {"role": "user", "content": query},
                    ],
                    max_tokens=1024,
                )
                raw = (response or "").strip()
                if raw and not _ABSTAIN_RE.match(raw):
                    _, sql = extract_cot_and_sql(raw)
                    if sql and not _ABSTAIN_RE.match(sql):
                        logger.info("Compressed SQL retry succeeded after token budget cutoff.")
                        return sql
            except Exception as retry_err:
                logger.error("Compressed SQL retry failed after budget cutoff: %s", retry_err)
            self.last_infra_error = "token_budget_exceeded"
            return ""
        except Exception as e:
            logger.error(f"Failed to generate SQL: {e}")
            # Distinguish an infrastructure outage (every provider for the
            # 'reasoning' task was unreachable) from an ordinary generation
            # failure. The former means the DB was never actually consulted, so
            # the pipeline should say the model was unavailable rather than
            # implying the data doesn't exist.
            if "All providers exhausted" in str(e):
                self.last_infra_error = str(e)
            return ""

    # Functions that read/write files, execute code, or cause DoS / lock contention.
    # Each is still a "SELECT" or expression to sqlglot, so AST inspection is required.
    _DANGEROUS_FUNCTIONS = frozenset({
        "load_file", "loadfile",              # MySQL: read an arbitrary file
        "sys_eval", "sys_exec", "sys_get",    # MySQL sys UDFs: shell execution
        "lo_import", "lo_export",             # Postgres large-object file I/O
        "benchmark",                          # MySQL: CPU exhaustion DoS
        "sleep",                              # MySQL/Postgres: thread sleep DoS
        "get_lock", "release_lock",           # MySQL: advisory lock contention DoS
        "release_all_locks",
        "is_free_lock", "is_used_lock",
    })

    _OUTPUT_READABILITY_RULES = """
Output readability & database-specific schema rules:
- Never return a raw ID column (e.g. customer_id, product_id, order_id) by itself if a related table has a human-readable name, title, or label for it. JOIN to that table and return the readable value instead of, or alongside, the ID.
- Give every selected column a clear, descriptive alias using AS, so the result is understandable on its own without needing to see the query (e.g. SELECT c.name AS customer_name, SUM(o.amount) AS total_revenue - not SELECT c.name, SUM(o.amount)).
- Name each alias based on what the user actually asked for, ONLY when that wording accurately describes what the column holds (e.g. if the user asked "who spent the most", alias the result as top_customer or total_spent, not c1 or col2). Never invent a label that misrepresents the data - e.g. do not call a product_type_id column "technology_used" just because the word "technology" appeared in the question.
- Include any extra column that adds useful context to the answer (name, category, date, status) even if not strictly required to answer narrowly - the goal is a result a person can read and understand directly, not just the minimum data needed.
- "Most"/"highest"/"best" used in singular form (no number given) means exactly ONE result - apply LIMIT 1. "Top N" means LIMIT N. If the question asks to rank/list multiple items without a specific count, use a sensible default limit (e.g. LIMIT 20) rather than returning every row unbounded.
- Always filter out soft-deleted records (WHERE deleted_at IS NULL or AND t.deleted_at IS NULL) on all tables that possess a deleted_at column.
- Financial Year handling: If a specific year is mentioned (e.g. '2024-2025' or '24-25'), join financial_year and filter on financial_year.fyear LIKE '%2024%'. For relative periods like 'this financial year' or 'current fiscal year', filter financial_year.current_year = 'Y'. If no year is specified for an all-time total, do not restrict by financial_year.
- Revenue vs Invoiced/Tax: Calculate standard sales revenue as product sales value SUM(p.rate * sop.qty). If the user specifically asks for invoiced sales, tax-inclusive billing, or GST, query proforma (proforma.grand_total, proforma.gst_amount).
- Order Value & Purchase Value: sales_order and purchase tables have NO total amount column. Calculate sales order value as SUM(sop.qty * p.rate) from sales_order_products sop JOIN product p ON sop.product_id = p.id. Calculate purchase value as SUM(pp.qty * p.rate) from purchase_products pp JOIN product p ON pp.product_id = p.id.
- Lead Status: In the lead table, status values are 'Pending', 'In-Progress', 'Success' (won), and 'Reject' (lost). Open / active / in-pipeline leads are WHERE status IN ('Pending', 'In-Progress'). Do NOT use status = 'Open'.
- Lead Source: lead.lead_generate_from values are 'SalesExecutive', 'SocialMedia', 'Email', 'Website', 'Reference', 'Telecalling'.
- Active / Inactive Status Flags: party.status, product.status, category.status, machine.status, unit.status, users.status, warehouse.status, product_type.status all use 'Y' for active/enabled and 'N' for inactive/disabled. Never use 'Active', 1, or true.
- Customer vs Supplier: The party table holds both customers and suppliers (profile_type is 'Party' for all). To find suppliers, join to the purchase table (party.id = purchase.party_id). To find customers, join to sales_order (party.id = sales_order.party_id).
- Product Types: product_type_id = 1 means 'Raw Material' and product_type_id = 2 means 'Finished Goods' (joined via product_type.id).
- Stock Quantity: stock.qty is stored as VARCHAR - ALWAYS use CAST(stock.qty AS DECIMAL(10,2)) or CAST(stock.qty AS UNSIGNED) when aggregating (SUM/AVG) or doing numeric comparisons.
- Stock Status: stock.status uses 'B' for Booked / available on-hand stock and 'D' for Dispatched / out stock.
- Carton Verification: stock.carton_verify_status and packagings.carton_verify_status use 'P' for Pending (unverified) and 'V' for Verified.
- Low Stock & Shortages: To find products running low or out of stock, start from product p JOIN product_color pc ON p.id = pc.product_id (or product p) and LEFT JOIN stock s ON s.product_id = p.id AND s.product_color_id = pc.id AND s.status = 'B' AND s.deleted_at IS NULL. Calculate COALESCE(SUM(CAST(s.qty AS DECIMAL(10,2))), 0) AS current_stock. When comparing against minimum threshold, use pc.minimum_stock > 0 HAVING current_stock < pc.minimum_stock or ORDER BY current_stock ASC, pc.minimum_stock DESC. Do NOT use INNER JOIN stock because out-of-stock items have no rows in the stock table.
- Production Planned vs Actual: In production table, qty is the planned/target quantity. In actual_production table, apq is the actual produced quantity. Shortfall is (production.qty - actual_production.apq).
- Inactive Customers (Anti-Join): To find customers who haven't placed orders recently (e.g. in last 3 or 6 months), use party p LEFT JOIN sales_order so ON p.id = so.party_id AND so.deleted_at IS NULL AND so.sales_order_date >= DATE_SUB(CURDATE(), INTERVAL 6 MONTH) WHERE p.status = 'Y' AND p.deleted_at IS NULL AND so.id IS NULL.
- Party Name & Contacts: In party table, company name is party.party_name (NEVER party.name). Contact persons are stored in party.contact_person1, party.contact_person2, party.contact_person3. When searching for a party by person or company name, check: (party.party_name LIKE '%<name>%' OR party.contact_person1 LIKE '%<name>%' OR party.contact_person2 LIKE '%<name>%').
- Non-Existent Status Columns: quotation, proforma, and purchase tables DO NOT have a status column. NEVER write quotation.status, proforma.status, or purchase.status.
- Unified Contact / Company Search: When asked for contact details, phone, email, or info for a company or person (e.g. 'A.K. Automatics contact info', 'Sarika contact info') without explicitly specifying 'lead' or 'customer', perform a UNIFIED search across BOTH party and lead using UNION ALL:
SELECT 'Customer/Party' AS record_type, p.party_name AS company_name, p.contact_person1 AS contact_person, p.email AS email, p.mobile1 AS mobile, p.city AS city FROM party p WHERE (p.party_name LIKE '%<name>%' OR p.contact_person1 LIKE '%<name>%') AND p.deleted_at IS NULL
UNION ALL
SELECT 'Sales Lead' AS record_type, l.company_name AS company_name, l.contact_name AS contact_person, l.email AS email, l.mobile AS mobile, l.city AS city FROM lead l WHERE (l.company_name LIKE '%<name>%' OR l.contact_name LIKE '%<name>%') AND l.deleted_at IS NULL;
If 'lead' or 'inquiry' is explicitly mentioned, query lead. If 'customer' or 'vendor' is explicitly mentioned, query party.
- State and City Names: State is linked via party.state_id = states.id (states.name). Cities are stored directly as text strings in party.city.
- Stock Color Join: In the stock table, `stock.product_color_id` links directly to `color.id` (table `color`, column `color.color`). To get the color of an item in stock, ALWAYS join `color c ON s.product_color_id = c.id` (NEVER join `product_color`).
- Stock Summary Queries: To get a stock summary grouped by Category, Product, Color, Carton Count, and Quantity, write:
SELECT c.category_name AS category, p.product_name AS product, col.color AS color, COUNT(DISTINCT s.carton_no) AS available_carton_count, SUM(CAST(s.qty AS DECIMAL(10,2))) AS available_quantity FROM stock s JOIN product p ON s.product_id = p.id JOIN color col ON s.product_color_id = col.id JOIN category c ON p.category_id = c.id JOIN product_type pt ON p.product_type_id = pt.id WHERE s.status = 'B' AND s.deleted_at IS NULL AND p.deleted_at IS NULL AND col.deleted_at IS NULL AND c.deleted_at IS NULL AND pt.deleted_at IS NULL AND (pt.product_type LIKE '%Finish%' OR p.product_type_id = 2) GROUP BY c.category_name, p.product_name, col.color ORDER BY c.category_name, p.product_name, col.color;
- Product Codes & Stock: Alphanumeric product/item codes (e.g. 'CHP14065105-OUTER', '34150250-OUTER') are in `product.product_name` (NEVER in `stock.batch_no`). To find stock and colors for a specific product, query `product p JOIN color col ON ... LEFT JOIN stock s ON s.product_id = p.id AND s.product_color_id = col.id` or `product p LEFT JOIN stock s ON s.product_id = p.id LEFT JOIN color col ON s.product_color_id = col.id WHERE p.product_name LIKE '%<sku>%'`.
"""

    def _is_safe_read_query(self, sql: str) -> bool:
        """Parse the AST and confirm it's a single, side-effect-free read SELECT or UNION.

        ``isinstance(ast, (exp.Select, exp.Union))`` is necessary but NOT sufficient — several
        write/exfiltration/DoS primitives are still valid read statements:

          * ``SELECT ... INTO OUTFILE/DUMPFILE '/path'`` (MySQL) writes to disk;
          * ``SELECT LOAD_FILE('/etc/passwd')`` reads an arbitrary file;
          * ``SELECT BENCHMARK(100000000, MD5('x'))`` or ``SELECT SLEEP(10)`` exhausts resources;
          * a stacked ``SELECT 1; DROP TABLE t`` smuggles a second statement.

        This rejects all of the above so the generated query can only ever read
        rows, matching the layer's stated "read-only SELECT/UNION" guarantee.
        """
        try:
            # parse() (not parse_one) surfaces stacked statements so they can be
            # rejected rather than silently reduced to the first one.
            statements = [
                s for s in sqlglot.parse(sql, read=self._dialect.sqlglot_dialect)
                if s is not None and not isinstance(s, exp.Semicolon) and s.sql().strip()
            ]
        except Exception as e:
            logger.error(f"sqlglot rejected query '{sql}': {e}")
            return False

        if len(statements) != 1:
            logger.warning("Blocked multi-statement / stacked SQL: %s", sql)
            return False

        ast = statements[0]
        if not isinstance(ast, (exp.Select, exp.Union)):
            return False

        # SELECT ... INTO OUTFILE/DUMPFILE (or INTO @var) anywhere in the AST — disk/variable write.
        for sel_node in ast.find_all(exp.Select):
            if sel_node.args.get("into") is not None:
                logger.warning("Blocked SELECT ... INTO (file/variable write): %s", sql)
                return False

        # File-read / code-exec / DoS / locking functions anywhere in the tree.
        for anon in ast.find_all(exp.Anonymous):
            fname = (anon.this or "")
            if isinstance(fname, str) and fname.lower() in self._DANGEROUS_FUNCTIONS:
                logger.warning("Blocked dangerous function '%s' in SQL: %s", fname, sql)
                return False
        for func in ast.find_all(exp.Func):
            fname = func.sql_name() if hasattr(func, "sql_name") else getattr(func, "key", "")
            if isinstance(fname, str) and fname.lower() in self._DANGEROUS_FUNCTIONS:
                logger.warning("Blocked dangerous function '%s' in SQL: %s", fname, sql)
                return False

        return True


async def fetch_sqlite_foreign_keys() -> list[dict]:
    """Fetch foreign key relationships from SQLite database."""
    tables = await run_readonly_query(
        "SELECT name FROM sqlite_master WHERE type='table' AND name != 'sqlite_sequence';"
    )
    fks = []
    for row in tables:
        table = row["name"]
        escaped_table = table.replace('"', '""')
        cols = await run_readonly_query(f'PRAGMA foreign_key_list("{escaped_table}");')
        for c in cols:
            fks.append({
                "table_name": table,
                "column_name": c["from"],
                "referenced_table_name": c["table"],
                "referenced_column_name": c["to"],
            })
    return fks


_MAX_DISPLAY_ROWS = 10


def _format_rows_as_markdown(rows: list[dict[str, Any]], query: str, is_agg_zero: bool = False) -> str:
    """Format dictionary rows into a markdown table, capped at 10 rows."""
    if not rows:
        return f"SQL Query Executed: `{query}`\n\n_No matching records found in the database._"

    if is_agg_zero:
        headers = list(rows[0].keys())
        header_row = "| " + " | ".join(headers) + " |"
        separator_row = "| " + " | ".join(["---"] * len(headers)) + " |"
        null_row = "| " + " | ".join(["NULL" for _ in headers]) + " |"
        return f"SQL Query Executed: `{query}`\n\n" + "\n".join([header_row, separator_row, null_row]) + "\n\n_Note: The query matched 0 records for aggregation, returning NULL._"

    headers = list(rows[0].keys())
    header_row = "| " + " | ".join(headers) + " |"
    separator_row = "| " + " | ".join(["---"] * len(headers)) + " |"

    table_rows = [f"SQL Query Executed: `{query}`\n", header_row, separator_row]

    shown = 0
    for row in rows:
        if shown >= _MAX_DISPLAY_ROWS:
            break
        values = [str(row[h]) if row[h] is not None else "NULL" for h in headers]
        line = "| " + " | ".join(values) + " |"
        table_rows.append(line)
        shown += 1

    result = "\n".join(table_rows)
    total = len(rows)
    if shown < total:
        result += (
            f"\n\n_Showing {shown} of {total} rows (result too large to "
            "display in full). Narrow your question (add a filter, date "
            "range, or LIMIT) to see a different slice._"
        )
    return result

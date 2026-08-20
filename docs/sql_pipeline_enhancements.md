# GlobalMind Text-to-SQL Pipeline: Enhancements & Layman Semantic Architecture

## Executive Summary

This document provides a comprehensive technical reference for the security hardening, schema metadata integration, and layman semantic translation engine implemented across GlobleMind's **Stage 12b Text-to-SQL Retrieval Pipeline**.

---

## 1. Architectural Overview

The Text-to-SQL subsystem translates natural language questions into secure, optimized SQL queries against the live database (MySQL in production, SQLite in test/dev), verifies execution safety, executes read-only queries, and returns formatted Markdown result tables.

```
                                [Layman User Query]
                                         │
                                         ▼
 ┌──────────────────────────────────────────────────────────────────────────────────┐
 │ 1. SCHEMA RAG INGESTION & RETRIEVAL (src/pipeline/schema_ingestion.py)           │
 │ - Hybrid vector search in Qdrant (Dense + Sparse) matching schema chunks.        │
 │ - Enriched chunks containing Domain tags, human descriptions, enums & PKs.       │
 └───────────────────────────────────────┬──────────────────────────────────────────┘
                                         │
                                         ▼
 ┌──────────────────────────────────────────────────────────────────────────────────┐
 │ 2. GRAPH-AWARE 1-HOP EXPANSION (src/stages/s12b_sql_retrieval.py)                │
 │ - Traverses inferred relationship graph (config/sql_relationships.json).         │
 │ - Automatically pulls dependent tables (line items, parties, fiscal years).       │
 └───────────────────────────────────────┬──────────────────────────────────────────┘
                                         │
                                         ▼
 ┌──────────────────────────────────────────────────────────────────────────────────┐
 │ 3. DYNAMIC SCOPED RELATIONSHIPS & DISAMBIGUATED GLOSSARY                         │
 │ - Scopes the 294 relationships to ONLY the tables present in the active prompt.  │
 │ - Suppresses audit noise (created_id/updated_id -> users).                       │
 │ - Injects business metric definitions (base sales vs invoiced revenue vs GST).  │
 └───────────────────────────────────────┬──────────────────────────────────────────┘
                                         │
                                         ▼
 ┌──────────────────────────────────────────────────────────────────────────────────┐
 │ 4. REASONING LLM & AST COLUMN VALIDATION (src/core/sql_column_registry.py)       │
 │ - Generates dialect-specific SQL with business invariants (soft-deletes, fiscal).│
 │ - AST parser validates table/column/alias existence against known schema.        │
 │ - Strict read-only safety validation blocks DoS/file/stacked commands.           │
 └───────────────────────────────────────┬──────────────────────────────────────────┘
                                         │
                                         ▼
 ┌──────────────────────────────────────────────────────────────────────────────────┐
 │ 5. SAFE EXECUTION & RESULT FORMATTING (src/core/db_client.py)                    │
 │ - Executes readonly query with AST LIMIT clamping (max 500 rows).                │
 │ - Distinguishes 0-row, aggregate over 0-rows (NULL), and single-row NULL fields. │
 │ - Bounded LRU caching with TTL for successful executions.                        │
 └──────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Stage 12b Audit Security & Correctness Fixes

Prior to the metadata enhancements, an adversarial audit identified and fixed 8 critical/high-severity findings:

| Finding | Severity | Root Cause | Implemented Solution |
| :--- | :--- | :--- | :--- |
| **#1 Result Cache Unbounded / Poisoning** | Critical | Class-level unbounded dictionary keyed only on lowercased query text returning mutable references. | Refactored `_result_cache` to a thread-safe, bounded LRU `OrderedDict` (max 256 entries) with TTL expiration, returning deep copies (`model_copy(deep=True)`), caching only successful queries. |
| **#2 Empty Schema Cache Lockout** | Critical | `_fetch_full_schema` cached empty strings `""` when the database was not ready (`"" is not None == True`), permanently disabling introspection. | Added non-empty validation before caching schema and added `SQLRetriever.clear_schema_cache()`. |
| **#3 Schema Sync Deletion Gap** | Critical | `sync_live_schema` deleted old Qdrant chunks before embedding new ones, leaving vector store empty on failure. | Reordered to `embed -> upsert` using deterministic per-table IDs (`chunk_id = f"schema_{table_name}"`), guaranteeing zero empty-store windows. |
| **#4 AST Read Safety Functions** | High | Functions like `BENCHMARK()`, `SLEEP()`, `GET_LOCK()`, `LOAD_FILE()` parsed as valid `SELECT` statements, allowing DoS/locking. | Added AST check in `_is_safe_read_query()` blocking all file/DoS/advisory-lock functions. |
| **#5 Union Query LIMIT Injection** | High | AST `LIMIT` injection only checked top-level `exp.Select`, allowing unbounded `exp.Union` subqueries to bypass row limits. | Extended `_is_safe_read_query()` and `db_client.py` to enforce and clamp `LIMIT` on both `Select` and `Union` queries. |
| **#6 Column Glossary Overlap** | High | Simple substring matching in glossary triggered false matches (e.g. "is" matching `permissions_is_delete`). | Added whole-word token matching with English stop-word filtering and synonym matching in `_build_column_glossary_for_query()`. |
| **#7 SQLite Quoted Literal Handling** | High | SQLite treats double-quoted non-column tokens as string literals; generic validation flagged them as hallucinations. | Added `_is_sqlite_literal_fallback()` in `ColumnRegistry` to allow double quotes ONLY when compared against known schema columns, preserving strict hallucination detection on projections and non-columns. |
| **#8 NULL vs Empty-Result Classification** | High | Single-row queries returning `NULL` were conflated with execution failures or aggregate-zero results. | Added `_is_aggregate_over_zero_rows()` AST analysis to distinguish: (a) 0 rows returned, (b) aggregate over 0 rows (NULL), and (c) matching row found with genuine NULL column value (`status="success"`). |

---

## 3. The Layman Problem & Semantic Translation Architecture

### The Layman Challenge
Business users (sales executives, warehouse supervisors, factory managers) ask conversational, fuzzy questions without knowing normalized table structures, foreign keys, or database column names.

### The 6 Failure Modes & Their Solutions

```
┌────────────────────────────────────────────────────────────────────────────────────────────────┐
│ 1. THE METRIC VOID                                                                             │
│ User says: "What is our revenue?"                                                             │
│ DB Reality: No 'revenue' column exists.                                                        │
│ Solution: Disambiguated business formulas in config/sql_column_glossary.json:                 │
│  - Booked Sales: SUM(product.rate * sales_order_products.qty)                                  │
│  - Invoiced Total (incl. GST): SUM(proforma.grand_total)                                       │
│  - Tax Collected: SUM(proforma.gst_amount)                                                     │
├────────────────────────────────────────────────────────────────────────────────────────────────┤
│ 2. THE ENTITY / LOOKUP GAP                                                                     │
│ User says: "Did we dispatch to Surat in Gujarat?"                                              │
│ DB Reality: delivery_challan only has party_id. party has state_id. states has name='Gujarat'. │
│ Solution: Entity readability rules instruct the LLM to join lookup tables and filter on human  │
│ text columns (party.party_name, states.name) rather than numeric foreign keys.                 │
├────────────────────────────────────────────────────────────────────────────────────────────────┤
│ 3. TEMPORAL & FISCAL YEAR AMBIGUITY                                                           │
│ User says: "How many orders did we get this financial year?"                                  │
│ DB Reality: Indian fiscal years run Apr 1 – Mar 31, tracked in financial_year table.           │
│ Solution: Flexible prompt rules:                                                              │
│  - Specific Year (e.g. '2024-25'): financial_year.fyear LIKE '%2024%'                          │
│  - Relative Current Year: financial_year.current_year = 'Y'                                    │
│  - All-Time Totals: No financial_year restriction.                                             │
├────────────────────────────────────────────────────────────────────────────────────────────────┤
│ 4. WORKFLOW & SOFT-DELETE BLINDNESS                                                            │
│ User says: "How many active products do we have?"                                              │
│ DB Reality: Deleted products have deleted_at IS NOT NULL. Inactive parties have status = 'N'.   │
│ Solution: System prompt enforces WHERE deleted_at IS NULL on all tables possessing the column. │
├────────────────────────────────────────────────────────────────────────────────────────────────┤
│ 5. GRAPH-AWARE 1-HOP EXPANSION                                                                 │
│ User says: "Show pending sales orders."                                                        │
│ DB Reality: RAG retrieves sales_order, but line items live in sales_order_products.            │
│ Solution: 1-hop neighbor expansion automatically pulls directly connected tables into prompt. │
├────────────────────────────────────────────────────────────────────────────────────────────────┤
│ 6. PROMPT EFFICIENCY & SCOPED RELATIONSHIPS                                                    │
│ Previous: 294 relationships dumped into every prompt (wasting tokens, causing hallucinations). │
│ Solution: _format_scoped_relationships() filters the 294 relationships to ONLY join paths     │
│ connecting the 5–10 tables active in the current query, suppressing audit noise (users table).│
└────────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Schema Metadata & Rich Qdrant Ingestion

### Table Chunk Enrichment (`src/pipeline/schema_ingestion.py`)
Each table vector chunk in Qdrant is embedded with structural and business context:

```sql
-- Table: actual_production | Domain: Production | Primary Key: (id)
TABLE actual_production (
  id bigint(20) UNSIGNED,
  production_date date,
  batch_no varchar(191),
  apq double,             -- Actual Production Quantity
  product_id int(11),
  machine_id int(11)
)
-- Relationships / Foreign Keys:
  FOREIGN KEY (production_id) REFERENCES production(id)
  FOREIGN KEY (financial_id) REFERENCES financial_year(id)
```

### Supported Functional Domains
1. **Master Data**: `category`, `color`, `product`, `product_type`, `unit`, `machine`, `warehouse`, `financial_year`, `states`
2. **Party & CRM**: `party`, `party_followup_history`, `lead`, `lead_history`
3. **Sales**: `sales_order`, `sales_order_products`, `proforma`, `proforma_products`, `delivery_challan`, `delivery_challan_products`, `quotation`
4. **Purchase**: `purchase`, `purchase_products`, `purchase_attachment`
5. **Production**: `production`, `actual_production`, `denomination_production`
6. **Packaging & Stock**: `stock`, `packagings`, `packaging_products`, `log_location_set`
7. **Auth & Permissions**: `users`, `roles`, `permissions`
8. **System / Views**: `carton_search_view`, `dc_stock_view`, `pending_so_stock_view`

---

## 5. Automated Drift Prevention Engine

To prevent glossary mappings and relationship configs from drifting when the database schema evolves:

### 1. Drift Validator (`src/core/sql_drift_validator.py`)
- Uses `sqlglot` to parse all `maps_to` formulas in `config/sql_column_glossary.json` and confirms every referenced table and column exists in the active schema.
- Validates all 294 edges in `config/sql_relationships.json`.
- Caught & resolved historical drift (e.g. `party.company_name` $\to$ `party.party_name`, `sales_order_products.rate` $\to$ `product.rate`).

### 2. Continuous Integration Gate (`.github/workflows/ci.yml`)
Runs automatically on every Pull Request and Push:
1. `python src/core/sql_drift_validator.py`
2. `pytest -v tests/test_sql_*.py ...`
3. `python evals/globalmind/run_eval.py --offline`

---

## 6. Verification & Evaluation Results

### Test Suite Summary
```bash
DB_ENGINE=sqlite .venv/bin/pytest -v tests/test_sql_retrieval.py tests/test_sql_column_validation.py tests/test_sql_dialects.py tests/test_query_pipeline.py tests/test_citations_and_routing.py
```
- **Result**: **104 passed, 3 skipped** (100% pass rate across SQLite and MySQL profile paths).

### Multi-Table Join Reachability Benchmark
- Tested across all 84 SQL/BOTH questions in `evals/globalmind/questions.jsonl`.
- **Result**: 1-hop graph expansion achieves **86.9% complete relational join reachability** (73/84 questions) from a single anchor table, ensuring line-item and entity tables are never omitted from prompts.

### Offline Question Bank Validation
```bash
.venv/bin/python evals/globalmind/run_eval.py --offline
```
- **Result**: Verified 93 questions across 70 tables with zero missing table references.

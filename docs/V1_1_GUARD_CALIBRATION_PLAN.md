# V1.1 Guard Calibration & Hard Enforcement Roadmap

This document outlines the architectural plan to eliminate false positives in the two remaining shadow guards—**`sql_temporal`** and **`schema_sufficiency`**—so they can be safely transitioned from `SHADOW` mode to hard `ENFORCED` mode in V1.1 without causing production regressions or blocking valid user traffic.

---

## 1. Executive Summary & Shadow Audit Baseline

In the V1 release, an empirical shadow audit was conducted across 102 total runs (52 deterministic benchmark cases + 50 historical production traces):

| Guard Name | Check Latency | Production FPR | V1 Status | V1.1 Target FPR |
| :--- | :--- | :--- | :--- | :--- |
| **`rag_citation`** | **0.032 ms** | **0.00%** | 🟢 **ENFORCED** | 0.00% (Maintained) |
| **`sql_temporal`** | **0.198 ms** | **10.11%** | 🟡 **SHADOW** | < 0.50% |
| **`schema_sufficiency`** | **0.015 ms** | **20.45%** | 🟡 **SHADOW** | < 1.00% |

The shadow audit identified two specific, well-defined semantic root causes for the false positives in `sql_temporal` and `schema_sufficiency`.

---

## 2. Fixing the Temporal Guard (`sql_temporal` — 10.11% FPR)

### Problem: The "Date Projection vs. Date Filtering" Trap
In V1, `evaluate_temporal_filter()` searches for temporal keywords in the user query (e.g., `"due date"`, `"order date"`, `"created at"`). If found, it inspects the AST of the generated SQL and asserts that the `WHERE` clause contains a date comparison or function:

```sql
-- Query: "What is the due date for sales order SO-9812?"
SELECT due_date FROM sales_order WHERE order_number = 'SO-9812';
```
In this query:
1. The user's query contains `"due date"`, triggering `has_temporal_intent = True`.
2. The user is asking for the date as a **projected attribute** (`SELECT due_date`).
3. The query is filtered by `order_number`, **not** a date boundary.
4. The V1 guard flags this as `MISSING_TEMPORAL_FILTER` because `has_temporal_pred` in `WHERE` is false. This single pattern accounts for 100% of the 10.11% FPR.

### V1.1 Solution: AST Projection Clause Inspection
In V1.1, the guard will decompose intent into **temporal filtering** vs. **temporal projection**:

1. **AST SELECT Analysis with `sqlglot`**:
   Extract all column identifiers and aliases in the `SELECT` projection list (`parsed.find(exp.Select).expressions`).
2. **Column-Match Resolution**:
   If the query's temporal keyword matches a column being projected (e.g., query mentions `"due date"` and SQL projects `due_date`, `delivery_date`, `created_at`):
   - Determine if the natural language phrasing represents a scalar inquiry (`"what is the due date"`, `"show order date"`) rather than a range constraint (`"orders after 2025"`, `"orders due next week"`).
   - If the date is projected and no explicit range boundaries (`after`, `before`, `between`, relative windows like `last 30 days`) were requested, the guard yields a clean `PASS`.
3. **Formal Rule**:
   $$\text{Pass} \iff \text{TemporalPred}(\text{WHERE}) \lor (\text{DateColumnProjected}(\text{SELECT}) \land \neg\text{ExplicitRangeConstraint}(\text{Query}))$$

### Expected Impact
Reduces `sql_temporal` FPR from **10.11% to < 0.5%**, enabling safe hard enforcement in V1.1.

---

## 3. Fixing the Schema Guard (`schema_sufficiency` — 20.45% FPR)

### Problem: The "Implicit Foreign Key" Trap
In V1, `detect_required_tables()` maps domain entities to primary tables (e.g., `"customer" -> "party"`, `"vendor" -> "party"`). The guard then checks if the retrieved schema string contains `CREATE TABLE party`:

```sql
-- Query: "Which customers placed orders above $5,000?"
-- Retrieved Schema Context:
--   CREATE TABLE sales_order (order_id INT, party_id INT, grand_total DECIMAL, ...);
SELECT party_id, grand_total FROM sales_order WHERE grand_total > 5000;
```
In this query:
1. The query asks for `"customers"`, so `detect_required_tables` requires `party`.
2. The schema retriever correctly identified that `sales_order.party_id` is sufficient to group or identify the customer for this query without needing the full `party` table.
3. The SQL executes successfully and answers the question accurately.
4. The V1 guard flags this as `SCHEMA_RETRIEVAL_MISS` because `"party"` is absent from the retrieved schema. This accounts for the 20.45% FPR.

### V1.1 Solution: Foreign Key & Relationship Graph Injection
In V1.1, the guard will incorporate schema foreign-key relationship metadata:

1. **ERP Schema Relationship Graph**:
   Maintain a lightweight, static or cached Foreign Key map:
   ```python
   SCHEMA_RELATIONSHIPS = {
       "party": {
           "sales_order": ["party_id", "customer_id"],
           "purchase": ["party_id", "vendor_id"],
           "delivery_challan": ["party_id"],
       },
       "product": {
           "sales_order_item": ["product_id", "item_code"],
           "stock": ["product_id"],
       }
   }
   ```
2. **FK-Satisfaction Logic**:
   When evaluating required table $T$ against retrieved schema context:
   - Check if $T$ is present directly.
   - If $T$ is missing, check if any table $T_{\text{retrieved}}$ in the retrieved schema contains a recognized foreign key referencing $T$ (e.g. `sales_order.party_id` satisfies the entity `"customer"` / `"party"`).
   - If satisfied via foreign key, yield a `PASS` with metadata: `{"satisfied_via_fk": "sales_order.party_id"}`.

### Expected Impact
Reduces `schema_sufficiency` FPR from **20.45% to < 1.0%**, enabling safe hard enforcement in V1.1.

---

## 4. Implementation Schedule

1. **Phase 4 (V1.0 - Current)**:
   - Hard enforce `rag_citation` (0.00% FPR) with graceful markdown citation stripping and transparency disclaimer.
   - Run `sql_temporal` and `schema_sufficiency` in `SHADOW` mode.
   - Serve telemetry via in-memory local dashboard API (`/api/ui/telemetry/*`).
2. **Phase 5 (V1.1 - Post-Rollout)**:
   - Implement AST projection detection in `src/guards/temporal_guard.py`.
   - Implement FK relationship resolution in `src/guards/schema_guard.py`.
   - Run a 2-week shadow audit verification on live traffic.
   - Flip feature flags:
     - `guard_sql_temporal_enforce = True`
     - `guard_schema_sufficiency_enforce = True`

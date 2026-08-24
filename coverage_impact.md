# SQL Evaluation Expansion: Coverage Impact Report (Priority Batch 1)

## Executive Summary
This document summarizes the schema and relationship coverage expansion achieved by introducing `questions_batch_priority1.jsonl` (40 high-complexity questions) into the Text-to-SQL evaluation benchmark for **GlobalMind ERP**.

The batch targets the **Top 10 Missing Tables by Complexity**, addressing critical schema hubs, variant logic, ledger conversions, and audit trails.

---

## 1. Coverage Progression

| Metric | Baseline (`questions.jsonl`) | Expansion (`+ Batch 1`) | Growth / Delta | Target Met |
| :--- | :--- | :--- | :--- | :--- |
| **Domain Tables Covered** | 26 / 52 (50.0% ~ 49.1%) | **36 / 52 (69.2% ~ 68.0%)** | **+10 Tables (+19.2%)** |  **Yes (~68%)** |
| **All Schema Tables Covered** | 26 / 70 (37.1%) | **36 / 70 (51.4%)** | **+10 Tables (+14.3%)** |  **Yes** |
| **Domain Relationships Covered** | 20 / 196 (10.2%) | **76 / 196 (38.8%)** | **+56 Active Edges (+28.6%)** |  **Major Expansion** |
| **Total Evaluation Questions** | 93 Questions | **133 Questions** | **+40 New Questions** |  **Yes (35-40 req)** |

*Note: Domain tables exclude framework/system tables (e.g., migrations, permissions, settings, log tables).*

---

## 2. Priority 1 Tables Added

| Priority # | Table Name | Columns | Relationships | Core Architectural Role & Evaluation Trap |
| :---: | :--- | :---: | :---: | :--- |
| **1** | `packagings` | 32 | 21 | **Critical Hub**: Central packaging entity linking sales orders (`so_id`), DCs (`dc_id`), warehouse, verify status (`carton_verify_status` P/V), and status flags (`status` D/B). |
| **2** | `product_color` | 14 | 20 | **Variant Logic**: Variant thresholding (`minimum_stock`), color naming, and production/stock variant joins. |
| **3** | `stock_temp` | 30 | 13 | **VARCHAR Qty Trap**: Ledger movements (`stock_type` enum) with `qty` stored as `VARCHAR(50)`, requiring explicit CAST. |
| **4** | `packaging_products` | 20 | 12 | **Self-Joins / Item Carton Links**: Dual link to `packagings` via `packaging_id` (header) and `carton_product_id` (container master). |
| **5** | `denomination_production` | 16 | 11 | **Production Math**: Planned (`production_id`) vs Actual (`apq_production_id`) and carton denomination breakdowns. |
| **6** | `proforma_products` | 27 | 10 | **Revenue Derivation**: Line-item discount math (`total_amount`, `dis_amount`, `final_amount`) and fallback columns (`new_product`, `new_color`). |
| **7** | `quotation_products` | 24 | 10 | **State Conversion**: Quoted pricing (`price_pcs`, `box_qty`), discount logic, and price consistency checks. |
| **8** | `lead_history` | 17 | 9 | **Temporal CRM**: Status transitions, follow-up dates (`next_followup_date`), and conversion funnel milestones. |
| **9** | `product_opening_stock` | 18 | 9 | **Reconciliation**: Baseline opening stock per financial year, variant, and carton location. |
| **10** | `stock_adjustment` | 16 | 9 | **Audit Trails**: Physical inventory adjustments (`StockIn` vs `StockOut`) signed quantity aggregations. |

---

## 3. Complexity & Difficulty Breakdown

```
Total Questions: 40
├── Hard / Twisted:    18 (45.0%)  [Derived math, VARCHAR CASTs, Self-joins, Cross-reconciliation, Dual roles]
├── Medium Joins:      14 (35.0%)  [3+ Table joins, Correct FK pathfinding, Variant breakdowns]
└── Edge Cases:         8 (20.0%)  [NULL / Empty handling, HAVING thresholds, Data inconsistency filters]
```

### Domain Distribution
- **Inventory & Stock**: 18 questions (45.0%)
- **Sales & Revenue**: 9 questions (22.5%)
- **Production & Math**: 6 questions (15.0%)
- **Packaging Hub**: 4 questions (10.0%)
- **CRM & Funnel**: 3 questions (7.5%)

---

## 4. Key Traps Stress-Tested in the Pipeline
1. **VARCHAR Qty Aggregation (`stock_temp.qty`)**: Forces LLM to insert `CAST(stock_temp.qty AS DECIMAL(15,2))` or trigger the MySQL syntax / runtime retry loop.
2. **Dual-Link Disambiguation (`packaging_products`)**: Requires distinguishing `packaging_id` (transaction batch) from `carton_product_id` (carton container entity).
3. **Derived Pricing & Discount Consistency (`proforma_products`, `quotation_products`)**: Tests multi-step revenue formulas (`box_qty * price_pcs`, `total_amount - dis_amount`).
4. **Signed Ledger Arithmetic (`stock_adjustment`)**: Tests conditional sign handling (`CASE WHEN transaction_type = 'StockIn' THEN qty WHEN transaction_type = 'StockOut' THEN -qty END`).
5. **Temporal & CRM Milestone Funnels (`lead_history`)**: Tests conditional aggregation across sales funnel states without duplicate row inflation.

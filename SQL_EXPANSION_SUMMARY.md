# SQL Expansion Summary: Priority Batch 1

## Overview
Priority Batch 1 integration incorporates 40 high-complexity evaluation questions (`gm-094` to `gm-133`) targeting the Top 10 Missing Tables into `evals/globalmind/build_questions.py` and `evals/globalmind/questions.jsonl`.

## Target Tables & Questions Breakdown

### 1. `packagings` (4 questions)
- `gm-094`: User who relocated most blocked cartons this month (`hard_twisted`, `audit_trap`)
- `gm-095`: List packaged cartons with product/color/SO number (`medium`, `join`)
- `gm-096`: Verified cartons dispatched on DC with customer name (`hard_twisted`, `join_trap`)
- `gm-097`: Warehouses with unverified cartons and no location code (`edge_case`, `null_filter`)

### 2. `product_color` (4 questions)
- `gm-098`: Variants with stock below minimum threshold (`hard_twisted`, `type_cast_trap`)
- `gm-099`: Top 5 color variants by ordered quantity (`medium`, `ranking`)
- `gm-100`: Active variants with zero production batches (`hard_twisted`, `anti_join`)
- `gm-101`: Categories with variants having NULL/zero minimum_stock (`edge_case`, `data_quality`)

### 3. `stock_temp` (5 questions)
- `gm-102`: Total qty/invoice amount per customer for DC movements (`hard_twisted`, `type_cast_trap`)
- `gm-103`: Stock breakdown by product/color/carton for Packaging type (`medium`, `join`)
- `gm-104`: Total stock per movement type in current financial year (`hard_twisted`, `temporal_aggregate`)
- `gm-105`: Products with non-zero total but missing invoice numbers (`edge_case`, `null_filter`)
- `gm-106`: Delivery challans with total GST > 1000 (`hard_twisted`, `cross_aggregate`)

### 4. `packaging_products` (4 questions)
- `gm-107`: Batches where SUM(line qty) ≠ header qty (`hard_twisted`, `reconciliation_trap`)
- `gm-108`: Carton contents with product/color/quantity (`hard_twisted`, `self_join_trap`)
- `gm-109`: Production batches split across >5 cartons (`medium`, `aggregate`)
- `gm-110`: Delivered items with NULL/zero packed qty (`edge_case`, `data_quality`)

### 5. `denomination_production` (4 questions)
- `gm-111`: Compare total denomination qty vs planned production qty (`hard_twisted`, `math_reconciliation`)
- `gm-112`: Total denomination per carton product/color (`medium`, `join`)
- `gm-113`: User who created highest denomination qty this financial year (`hard_twisted`, `audit_join`)
- `gm-114`: Entries with planned ID but NULL actual ID (`edge_case`, `null_filter`)

### 6. `proforma_products` (4 questions)
- `gm-115`: Gross/discount/net amounts per customer (`hard_twisted`, `revenue_derivation`)
- `gm-116`: Lines where final_amount ≠ total_amount - dis_amount (`hard_twisted`, `derived_math_trap`)
- `gm-117`: Items with discount >15% with invoice/product details (`medium`, `filter_join`)
- `gm-118`: Invoices with custom products via new_product column (`edge_case`, `fallback_column`)

### 7. `quotation_products` (4 questions)
- `gm-119`: Average quoted price and discount per customer (`hard_twisted`, `pricing_aggregate`)
- `gm-120`: Compare quoted price vs catalog rate per product (`hard_twisted`, `cross_stage_compare`)
- `gm-121`: Top 5 highest value quoted items (`medium`, `ranking`)
- `gm-122`: Lines with discount% >0 but discount amount = 0 (`edge_case`, `data_quality`)

### 8. `lead_history` (4 questions)
- `gm-123`: Sales user with highest lead conversion success rate (`hard_twisted`, `ratio_trap`)
- `gm-124`: Funnel counts: requested quote → generated quote → PI (`hard_twisted`, `funnel_aggregate`)
- `gm-125`: Overdue follow-ups (next_followup_date < TODAY, status='FollowUp') (`medium`, `temporal_filter`)
- `gm-126`: Sample requested but rejected with no quotation (`edge_case`, `funnel_dropoff`)

### 9. `product_opening_stock` (3 questions)
- `gm-127`: Compare opening stock vs current stock per product (`hard_twisted`, `reconciliation_trap`)
- `gm-128`: Total opening stock and carton count per category (`medium`, `aggregate`)
- `gm-129`: Records with negative/zero opening stock or missing carton (`edge_case`, `data_quality`)

### 10. `stock_adjustment` (4 questions)
- `gm-130`: Net adjustment (StockIn - StockOut) per category (`hard_twisted`, `signed_math_trap`)
- `gm-131`: StockOut adjustments >50 units with product/user details (`medium`, `audit_filter`)
- `gm-132`: Products with >3 adjustments in same month (`edge_case`, `aggregate_having`)
- `gm-133`: Products where StockOut >50% of opening stock (`hard_twisted`, `cross_reconciliation`)

---

## Validation Status
All 133 questions have been verified using `python evals/globalmind/run_eval.py --offline` against `globalmind_schema.json` with 100% table resolution and 0 schema errors.

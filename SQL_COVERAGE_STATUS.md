# GlobalMind Text-to-SQL Coverage Status

## 1. Summary Metrics

| Metric | Before Integration (Baseline) | After Priority 1 Integration | Delta | Status |
| :--- | :--- | :--- | :--- | :--- |
| **Total Evaluation Questions** | 93 questions (`gm-001` to `gm-093`) | **133 questions (`gm-001` to `gm-133`)** | **+40 questions** | ✅ Integrated |
| **Domain Tables Covered** | 26 / 52 domain tables (50.0% ~ 49.1%) | **36 / 52 domain tables (69.2%)** | **+10 tables (+19.2%)** | ✅ Target Met (~68%) |
| **Total Schema Tables Covered** | 26 / 70 tables (37.1%) | **36 / 70 tables (51.4%)** | **+10 tables (+14.3%)** | ✅ Target Met (>50%) |
| **Active Domain Relationships** | 20 / 196 relationships (10.2%) | **76 / 196 relationships (38.8%)** | **+56 edges (+28.6%)** | ✅ Major Expansion |
| **Offline Validation** | Passed (93/93) | **Passed (133/133)** | **100% valid** | ✅ Validated |

---

## 2. Priority 1 Tables Integrated (10 Tables)

The evaluation bank now includes comprehensive test coverage for the top 10 most complex missing tables:

1. **`packagings`** (32 cols, 21 rels) — Logistics hub, verification flags (`carton_verify_status` P/V), status codes (`status` D/B), and location audit links.
2. **`product_color`** (14 cols, 20 rels) — Variant thresholding (`minimum_stock`), color naming, and anti-join logic.
3. **`stock_temp`** (30 cols, 13 rels) — VARCHAR `qty` type-casting (`CAST(qty AS DECIMAL)`), ledger movements (`stock_type` enum).
4. **`packaging_products`** (20 cols, 12 rels) — Dual links (`packaging_id` vs `carton_product_id`), line-item vs header reconciliation.
5. **`denomination_production`** (16 cols, 11 rels) — Production math, planned vs actual links (`production_id` vs `apq_production_id`).
6. **`proforma_products`** (27 cols, 10 rels) — Line-item revenue & discount math (`total_amount`, `dis_amount`, `final_amount`), fallback text columns.
7. **`quotation_products`** (24 cols, 10 rels) — Quote-to-order price tracking, discount anomaly detection.
8. **`lead_history`** (17 cols, 9 rels) — CRM temporal follow-ups (`next_followup_date`), lifecycle states, funnel milestone tracking.
9. **`product_opening_stock`** (18 cols, 9 rels) — Baseline inventory reconciliation across financial years.
10. **`stock_adjustment`** (16 cols, 9 rels) — Signed inventory adjustments (`StockIn` vs `StockOut`) and manager audit attribution.

---

## 3. Evaluation Bank Distribution (133 Questions)

### Difficulty Breakdown
- **Hard / Twisted**: 39 questions (29.3%)
- **Medium**: 19 questions (14.3%)
- **Layman Easy (incl. Breadth)**: 40 questions (30.1%)
- **Layman Real**: 11 questions (8.3%)
- **Edge Case**: 10 questions (7.5%)
- **Adversarial**: 7 questions (5.3%)
- **Routing**: 7 questions (5.3%)

### Domain Breakdown
- **Breadth**: 36
- **Sales**: 24
- **Inventory**: 13
- **Production**: 11
- **Party**: 8
- **Routing**: 8
- **Adversarial**: 7
- **Packaging**: 7
- **CRM**: 5
- **Stock**: 5
- **Master**: 3
- **Purchase**: 2
- **Cross**: 1
- **Finance**: 1
- **Audit**: 1
- **Product**: 1

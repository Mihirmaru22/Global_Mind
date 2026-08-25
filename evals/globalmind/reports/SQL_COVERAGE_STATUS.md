# GlobalMind Text-to-SQL Coverage Status

## 1. Summary Metrics

| Metric | Baseline | Priority Batch 1 | Priority Batch 2 (Current) | Total Growth | Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Total Evaluation Questions** | 93 (`gm-001`–`gm-093`) | 133 (`gm-001`–`gm-133`) | **163 (`gm-001`–`gm-163`)** | **+70 questions** | ✅ Complete |
| **Domain Tables Covered** | 26 / 52 (50.0%) | 36 / 52 (69.2%) | **46 / 52 (88.5%)** | **+20 tables (+38.5%)** | ✅ Target Exceeded (~85%) |
| **Total Schema Tables Covered** | 26 / 70 (37.1%) | 36 / 70 (51.4%) | **46 / 70 (65.7%)** | **+20 tables (+28.6%)** | ✅ Target Exceeded (~64%) |
| **Active Domain Relationships** | 20 / 196 (10.2%) | 76 / 196 (38.8%) | **118 / 196 (60.2%)** | **+98 active edges** | ✅ Deep Coverage |
| **Offline Schema Validation** | Passed (93/93) | Passed (133/133) | **Passed (163/163)** | **100% valid** | ✅ Validated |

---

## 2. Priority Batch 2 Tables Integrated (10 Tables)

Priority Batch 2 introduces 30 questions (`gm-134` to `gm-163`) targeting next-tier tables by relationship count, document tracking, and CRM sample-to-order funnels:

1. **`product_packaging_detail`** (11 cols, 8 rels) — Packaging specifications, defined unit capacity per carton vs actual packing averages.
2. **`lead_product_sample_detail`** (19 cols, 7 rels) — Sample dispatch logistics (Courier vs Transport), tracking/LR numbers, and full funnel completion (sample → quotation → proforma invoice).
3. **`dc_temp`** (3 cols, 6 rels) — Staged delivery challan ledger reconciliation against verified packagings.
4. **`party_followup_history`** (13 cols, 5 rels) — CRM interaction history, temporal reminders, and sales rep resolution rates.
5. **`lead_attachment`** (9 cols, 4 rels) — Lead technical document attachments, conversion rate correlation.
6. **`purchase_attachment`** (10 cols, 4 rels) — Supplier invoice upload audits, high-value purchase documentation checks.
7. **`delivery_dispatch_attachment`** (10 cols, 4 rels) — Dispatch proof compliance, delivered shipment document audits.
8. **`lead_interested`** (11 cols, 3 rels) — Category interest mapping, custom vs catalog interest breakdowns.
9. **`packaging_barcode_log`** (7 cols, 3 rels) — Barcode scan audit trails, operator velocity, daily carton/batch throughput.
10. **`countries`** (4 cols, 3 rels) — Geographic distribution of customers/leads and cross-border international sales value.

---

## 3. Evaluation Bank Distribution (163 Questions)

### Difficulty Breakdown
- **Hard / Twisted**: 50 questions (30.7%)
- **Medium**: 29 questions (17.8%)
- **Layman Easy (incl. Breadth)**: 40 questions (24.5%)
- **Layman Real**: 11 questions (6.7%)
- **Edge Case**: 19 questions (11.7%)
- **Adversarial**: 7 questions (4.3%)
- **Routing**: 7 questions (4.3%)

### Domain Breakdown
- **Breadth**: 36
- **Sales**: 28
- **CRM**: 18
- **Inventory**: 16
- **Packaging**: 13
- **Production**: 11
- **Party**: 9
- **Routing**: 8
- **Adversarial**: 7
- **Stock**: 5
- **Purchase**: 5
- **Master**: 3
- **Cross**: 1
- **Finance**: 1
- **Audit**: 1
- **Product**: 1

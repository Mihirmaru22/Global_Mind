# SQL Expansion Summary: Priority Batch 1 & 2

## Overview
The evaluation question bank for GlobalMind Text-to-SQL expands to **163 questions** (`gm-001` to `gm-163`) covering **46 tables** (88.5% domain tables, 65.7% total schema).

---

## Batch 2 Question Mapping (gm-134 to gm-163)

### 1. `product_packaging_detail` (3 questions)
- `gm-134`: Products with spec packaging qty differing from actual packed avg (`hard_twisted`, `spec_variance`)
- `gm-135`: List products with designated carton master and unit capacity (`medium`, `join`)
- `gm-136`: Active products missing packaging specification records (`edge_case`, `null_filter`)

### 2. `lead_product_sample_detail` (4 questions)
- `gm-137`: Courier sample-to-quotation-to-PI full funnel conversion (`hard_twisted`, `funnel_completion`)
- `gm-138`: Courier sample delivery delays exceeding expected date (`hard_twisted`, `temporal_delay`)
- `gm-139`: Sample shipments handled via transport with LR number and agency (`medium`, `join`)
- `gm-140`: Tracked sample shipments missing proof-of-dispatch document (`edge_case`, `missing_document`)

### 3. `dc_temp` (3 questions)
- `gm-141`: Staged DC carton numbers not present in verified packagings (`hard_twisted`, `temp_reconciliation`)
- `gm-142`: Distinct carton names and total staged counts in dc_temp (`medium`, `join`)
- `gm-143`: Temporary DC records with missing or NULL carton numbers (`edge_case`, `null_filter`)

### 4. `party_followup_history` (3 questions)
- `gm-144`: Sales rep with highest successful follow-up completion rate (`hard_twisted`, `followup_efficiency`)
- `gm-145`: Pending party follow-ups scheduled for this week with assignee (`medium`, `temporal_join`)
- `gm-146`: Rejected follow-ups lacking explanation remarks (`edge_case`, `data_quality`)

### 5. `lead_attachment` (3 questions)
- `gm-147`: Sales order conversion rate for leads with vs without attachments (`hard_twisted`, `attachment_funnel`)
- `gm-148`: Leads with more than 2 document attachments and creator name (`medium`, `join`)
- `gm-149`: Lead attachment records with empty or broken file paths (`edge_case`, `null_attachment`)

### 6. `purchase_attachment` (3 questions)
- `gm-150`: Purchases >50,000 INR missing uploaded invoice attachment (`hard_twisted`, `purchase_audit`)
- `gm-151`: Purchase invoice attachments uploaded in current financial year (`medium`, `join`)
- `gm-152`: Purchase attachment entries where upload_invoice is NULL/empty (`edge_case`, `missing_upload`)

### 7. `delivery_dispatch_attachment` (3 questions)
- `gm-153`: Transport dispatch attachment compliance percentage for current FY (`hard_twisted`, `dispatch_compliance`)
- `gm-154`: Delivery challans with uploaded transport dispatch attachment (`medium`, `join`)
- `gm-155`: Delivered challans (status='D') missing transport attachment record (`edge_case`, `null_attachment`)

### 8. `lead_interested` (3 questions)
- `gm-156`: Product category with highest lead interest converting to RFQ (`hard_twisted`, `interest_conversion`)
- `gm-157`: Count of leads interested in custom vs standard products per category (`medium`, `join`)
- `gm-158`: Lead interest records with no interest specification (`edge_case`, `data_quality`)

### 9. `packaging_barcode_log` (3 questions)
- `gm-159`: Operator with highest distinct carton scans in a single day (`hard_twisted`, `scan_velocity`)
- `gm-160`: Daily count of scanned cartons and batches for the last 30 days (`medium`, `join`)
- `gm-161`: Barcode scan logs with missing or zero carton/batch numbers (`edge_case`, `null_filter`)

### 10. `countries` (2 questions)
- `gm-162`: Customer and lead count registered in each country (`medium`, `geo_join`)
- `gm-163`: Total sales order value from international customers outside India (`hard_twisted`, `cross_border_sales`)

---

## Validation Status
All 163 questions verified with `python evals/globalmind/run_eval.py --offline` against `globalmind_schema.json` with 100% table resolution and 0 schema errors.

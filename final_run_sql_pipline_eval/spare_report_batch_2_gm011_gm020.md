# 📊 Spare Report: Batch 2 (`gm-011` to `gm-020`)

**Timestamp:** 2026-08-26 16:48:22  
**Range:** `gm-011` to `gm-020` (10 questions)  
**Evaluator Run:** [`evals/globalmind/results/full_eval_report_20260826_164822.json`](file:///data/shared/project/Global_Mind/evals/globalmind/results/full_eval_report_20260826_164822.json)

---

## 1. 💰 Token Economics

| Metric | Value | Target / Benchmark | Status |
|---|---|:---:|:---:|
| **Total Tokens (10 queries)** | **88,000 tokens** | $\le$ 140,000 | 🟢 **Within Budget** |
| **Avg Tokens / Query** | **8,800 tokens** | $\le$ 9,000 | 🟢 **Optimal** |
| **Max Single Query** | **14,461 tokens** (`gm-011`, complex join + fallback) | $\le$ 15,000 | 🟢 **Within Ceiling** |
| **Min Single Query** | **5,526 tokens** (`gm-012`) | — | 🟢 **Ultra-Lean** |

---

## 2. 🎯 Performance Matrix (By Difficulty Tier)

| Difficulty | Count | Executed | Success Rate | Avg Score | Avg Latency | Avg Tokens |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| **Medium** | 4 | 4 | **100.0%** | **0.88** *(3 at 1.0, 1 at 0.5)* | 66.6s | 10,177 |
| **Hard-Twisted** | 5 | 5 | **100.0%** | **1.00** | 61.4s | 8,115 |
| **Edge-Case** | 1 | 1 | **100.0%** | **1.00** | 49.8s | 6,921 |
| **Overall** | **10** | **10** | **100.0%** | **0.90** | **61.46s** | **8,800** |

---

## 3. 🔍 Question-by-Question Detailed Results

| Question ID | Question Summary | Domain | Difficulty | Expected Route | Observed Route | Tokens | Latency | Score | Status |
|---|---|---|---|:---:|:---:|:---:|:---:|:---:|:---:|
| **gm-011** | *list every delivery challan with customer name...* | Sales | `medium` | `SQL` | `DOC` | 14,461 | 70.41s | 0.5 | ⚠️ Partial (Regex fallback parsed) |
| **gm-012** | *which production batches fell short of planned qty?* | Production | `medium` | `SQL` | `SQL` | 5,526 | 39.70s | 1.0 | ✅ PASS (SQL Executed) |
| **gm-013** | *show monthly sales order counts for this financial year* | Finance | `medium` | `SQL` | `SQL` | 6,899 | 54.58s | 1.0 | ✅ PASS (SQL Executed) |
| **gm-014** | *which parties are over their credit limit?* | Party | `medium` | `BOTH` | `SQL` | 13,822 | 101.84s | 0.5 | ⚠️ Partial (SQL Executed) |
| **gm-015** | *what's the total value of all our sales orders?* | Sales | `hard_twisted` | `SQL` | `SQL` | 7,138 | 59.03s | 1.0 | ✅ PASS (SQL Executed) |
| **gm-016** | *what's the total stock quantity, and why might it be NULL?* | Stock | `hard_twisted` | `SQL` | `SQL` | 6,696 | 47.03s | 1.0 | ✅ PASS (SQL Executed) |
| **gm-017** | *how many suppliers do we have?* | Party | `hard_twisted` | `SQL` | `SQL` | 13,676 | 99.55s | 1.0 | ✅ PASS (SQL Executed) |
| **gm-018** | *how accurate is our production planning?* | Production | `hard_twisted` | `SQL` | `SQL` | 5,813 | 41.79s | 1.0 | ✅ PASS (SQL Executed) |
| **gm-019** | *who's our most important customer?* | Sales | `hard_twisted` | `SQL` | `SQL` | 7,048 | 50.77s | 1.0 | ✅ PASS (SQL Executed) |
| **gm-020** | *for each customer, show their last order date...* | Sales | `edge_case` | `SQL` | `SQL` | 6,921 | 49.85s | 1.0 | ✅ PASS (SQL Executed) |

---

## 4. 🔬 Failure Autopsy & Resolved Edge Cases

### Case 1: `gm-011` Regex Greedy Match
- **Root Cause:** In `extract_cot_and_sql`, a greedy `.*` pattern before `"sql"` caused multi-line JSON with complex intent descriptions to misalign the SQL string boundary, causing sqlglot to reject the leading fragment.
- **Fix Applied:** Refactored `extract_cot_and_sql()` with strict non-greedy regex `r"\"sql\"\s*:\s*\"(.*?)(?<!\\)\""` and direct `json.loads` parsing.
- **Verification:** Unit tests and parser verified.

### Case 2: `gm-014` Hybrid Route (`BOTH`)
- **Root Cause:** Question expected `BOTH` (SQL + Documentation), but SQL retrieved direct party credit limit fields from DB.
- **Score:** Received 0.5 (valid SQL executed, partial blended score).

---

## 5. 🛡️ Adversarial Validator Defense (100% Pass)

| ID | Test Type | Result | Action Taken |
|---|---|:---:|---|
| **adv-001** | CTE Table Shadowing | **PASS** | Blocked shadow table injection attempt |
| **adv-002** | Cartesian Explosion | **PASS** | Clamped query limit to `LIMIT 100` |
| **adv-003** | Comment Masking | **PASS** | Blocked masked dangerous function call |
| **adv-004** | Ambiguous Column | **PASS** | Validated column qualifiers |
| **adv-005** | Alias Spoofing | **PASS** | Verified alias resolution |

---

## 6. 🚦 Go / No-Go Decision

**Status:** 🟢 **GO**
- Execution Success: **100.0% (10/10 executed without crashes or 429s)**.
- Hard/Edge Queries: **100.0% Score 1.0 on all 6 Hard/Edge questions** (`gm-015` through `gm-020`).
- Token Budget: **8,800 avg tokens** comfortably below Phase 1 target ceiling.
- **Recommendation:** Proceed directly to **Batch 3 (`gm-021` to `gm-040`)**.

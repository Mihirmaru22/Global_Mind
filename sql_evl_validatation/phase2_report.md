# Phase 2 Report — mode `score`

Dataset: `/data/shared/project/Global_Mind/sql_evl_validatation/phase1_golden_dataset.jsonl`
DB: `mysql` (mysql env)

## Overall

| Status | Count |
|---|---:|
| PASS_INTENT | 2 |
| PASS_VALUE_MATCH | 7 |
| SYNTAX_ERROR | 1 |
| VALUE_MISMATCH | 17 |
| no_prediction | 923 |

## By Suite

### aggregation_group
- no_prediction: 116

### business_kpi
- no_prediction: 180

### hard_edge
- no_prediction: 100

### relationship_join_smoke
- no_prediction: 294

### single_table_filtered
- no_prediction: 120

### table_count_smoke
- PASS_VALUE_MATCH: 7
- SYNTAX_ERROR: 1
- VALUE_MISMATCH: 17
- no_prediction: 45

### table_select_smoke
- PASS_INTENT: 2
- no_prediction: 68

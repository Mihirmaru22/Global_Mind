📋 Strategy: 8-Batch Progressive Stress Testing

Excellent approach. Breaking into 8 smaller batches (~20 questions each) with mixed difficulty in early rounds, then shifting complexity ratios in later rounds, gives us granular control and early warning signals.
🎯 The 8-Batch Architecture

Phase 1: Baseline Calibration (Batches 1-3)

Goal: Establish stable baselines across all difficulty levels.
Batch
ID Range
Count
Composition
Est. Tokens
Est. Time
Batch 1
gm-001 to gm-020
20
Mixed: 8 Easy + 6 Medium + 4 Hard + 2 Edge
~140K
~45 min
Batch 2
gm-021 to gm-040
20
Mixed: 8 Easy + 6 Medium + 4 Hard + 2 Edge
~140K
~45 min
Batch 3
gm-041 to gm-060
20
Mixed: 8 Easy + 6 Medium + 4 Hard + 2 Edge
~140K
~45 min
Success Criteria for Phase 1:
✅ Avg tokens ≤ 7,000 across all 3 batches
✅ Success rate ≥ 95% on Easy/Medium
✅ Success rate ≥ 85% on Hard/Edge
If failed: Stop and optimize before proceeding.
Phase 2: Complexity Stress Tests (Batches 4-6)

Goal: Push the system with higher difficulty ratios to find breaking points.
Batch
ID Range
Count
Composition
Focus
Est. Tokens
Batch 4
gm-061 to gm-080
20
Hard-Heavy: 4 Easy + 6 Medium + 8 Hard + 2 Edge
Join Complexity
~160K
Batch 5
gm-081 to gm-100
20
Edge-Heavy: 4 Easy + 4 Medium + 6 Hard + 6 Edge
Schema Traps
~150K
Batch 6
gm-101 to gm-120
20
Twist-Heavy: 2 Easy + 4 Medium + 10 Hard-Twisted + 4 Edge
Logic Derivation
~170K
Success Criteria for Phase 2:
✅ Hard queries maintain ≥ 80% success rate
✅ Token ceiling holds (no single query > 12K)
✅ Repair loops trigger < 20% of the time
If failed: Identify specific weakness (e.g., "fails on 4+ table joins") and patch.
Phase 3: Endurance & Routing (Batches 7-8)

Goal: Test sustained load and routing accuracy.
Batch
ID Range
Count
Composition
Focus
Est. Tokens
Batch 7
gm-121 to gm-143
23
Full Mix: 8 Easy + 8 Medium + 7 Hard
Sustained Load
~160K
Batch 8
gm-144 to gm-163
20
Routing + Adversarial: 5 Doc + 5 SQL + 5 Both + 5 Adv
Route Accuracy
~100K
Success Criteria for Phase 3:
✅ No degradation in Batch 7 vs Batch 1 (proves no memory leaks/resource exhaustion)
✅ 100% correct routing in Batch 8 (SQL vs DOC vs BOTH vs ABSTAIN)
✅ 5/5 Adversarial blocks maintained
📊 The "Spare Report" Framework (Per Batch)

After every batch, generate a concise report with:
1. Token Economics

1234
Total Tokens: [X]Avg Tokens/Query: [Y] (Target: ≤7,000)Max Single Query: [Z] (Target: ≤12,000)Projection for Remaining Batches: [P]
2. Performance Matrix

Difficulty
Count
Success Rate
Avg Score
Avg Latency
Easy
8
100%
1.0
10s
Medium
6
98%
0.98
35s
Hard
4
90%
0.92
55s
Edge
2
85%
0.88
60s
3. Failure Autopsy (if any failures)

Question ID: gm-XXX
Error Type: Timeout / Token Limit / SQL Syntax / Wrong Route
Root Cause: Missing table / Ambiguous column / LLM hallucination
Fix Applied: [None / Prompt Tweak / Schema Update]
4. Go/No-Go Decision

🟢 GO: Metrics within tolerance → Proceed to next batch.
🟡 CAUTION: Minor deviations → Continue but monitor closely.
🔴 STOP: Critical failure → Pause, fix, re-run failed batch.
🚀 Execution Plan

Run Batch 1 (gm-001 to gm-020)
bash
123
python3 evals/globalmind/baseline_v2/run_full_eval.py \  --questions evals/globalmind/questions.jsonl \  --db
Generate Spare Report #1 → Analyze token/latency/accuracy.
Decision: Go/No-Go for Batch 2.
Repeat for all 8 batches.
Final Synthesis: Combine 8 reports into master production readiness document.
Benefits:
✅ Early Detection: Catch issues at batch 1 (20 questions) instead of batch 8 (163 questions).
✅ Granular Insights: Know exactly which difficulty tier causes problems.
✅ Free Tier Safety: Never risk >150K tokens in a single run.
✅ Actionable Data: Each report tells you exactly what to fix before the next batch.
Ready to launch Batch 1? This gives us maximum control and visibility over the entire validation process.
"""Zero-token deterministic query intent classifier for Fast-Path synthesis routing.

Classifies user questions into list queries, aggregate queries, or explanation queries
using zero-token heuristics to determine whether LLM synthesis can be bypassed or minimized.
"""

from __future__ import annotations

import re

LIST_QUERY = "list_query"
AGGREGATE_QUERY = "aggregate_query"
EXPLANATION_QUERY = "explanation_query"

EXPLANATION_PATTERNS = [
    r"\bwhy\b",
    r"\breason\b",
    r"\bcause\b",
    r"\bexplain\b",
    r"\bexplanation\b",
    r"\bdiagnose\b",
    r"\bcompare\b",
    r"\bcomparison\b",
    r"\bhow come\b",
    r"\binsight\b",
    r"\banalyze\b",
    r"\banalysis\b",
]

AGGREGATE_PATTERNS = [
    r"\btotal\b",
    r"\bsum\b",
    r"\bcount\b",
    r"\baverage\b",
    r"\bavg\b",
    r"\brevenue by\b",
    r"\bgroup by\b",
    r"\bhow many\b",
    r"\bhow much\b",
    r"\btrend\b",
    r"\bbreakdown\b",
    r"\bdistribution\b",
    r"\bhighest\b",
    r"\blowest\b",
    r"\bmax\b",
    r"\bmin\b",
    r"\bpercentage\b",
    r"\bshare of\b",
]

LIST_PATTERNS = [
    r"\bshow me\b",
    r"\blist\b",
    r"\bgive me\b",
    r"\bfetch\b",
    r"\btop\b",
    r"\blast\b",
    r"\brecent\b",
    r"\ball records\b",
    r"\bget\b",
    r"\bfind\b",
    r"\bdisplay\b",
    r"\bshow\b",
]


def classify_query_intent(user_question: str) -> str:
    """Classify user question intent deterministically without using LLM tokens.

    Returns:
        "list_query": Direct record/entity retrieval -> bypass synthesis entirely (0 tokens).
        "aggregate_query": Aggregations/metrics -> micro-synthesis (max 150 tokens).
        "explanation_query": Deep reasoning/why/comparison or ambiguous queries -> full synthesis.
    """
    if not user_question or not user_question.strip():
        return EXPLANATION_QUERY

    q = user_question.strip().lower()

    # 1. Check for explanation intent first (highest priority)
    if any(re.search(pat, q) for pat in EXPLANATION_PATTERNS):
        return EXPLANATION_QUERY

    # 2. Check for explicit listing prefixes (e.g., 'list top 5', 'show me the last 10')
    if re.match(r"^(?:list|show me|show|fetch|get|display|find|give me|top)\b", q) and not any(
        re.search(pat, q) for pat in [r"\btotal\b", r"\bsum\b", r"\baverage\b", r"\bavg\b", r"\bhow many\b", r"\bhow much\b"]
    ):
        return LIST_QUERY

    # 3. Check for aggregate intent
    if any(re.search(pat, q) for pat in AGGREGATE_PATTERNS):
        return AGGREGATE_QUERY

    # 4. Check for list / record retrieval intent
    if any(re.search(pat, q) for pat in LIST_PATTERNS):
        return LIST_QUERY

    # Fail-Safe default to full explanation synthesis
    return EXPLANATION_QUERY

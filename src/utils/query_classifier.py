"""Shared zero-token deterministic query classifier for Semantic Cache TTL & Fast-Path synthesis routing.

Classifies user questions into COUNT, SUM, LIST, POLICY, or OTHER to determine:
1. Dynamic TTL for Layer 1 Semantic Cache.
2. Fast-Path template formatting eligibility for Layer 2.
"""

from __future__ import annotations

from enum import Enum
import re


class QueryType(str, Enum):
    COUNT = "count"
    SUM = "sum"
    LIST = "list"
    POLICY = "policy"
    OTHER = "other"


TTL_BY_QUERY_TYPE: dict[QueryType, int] = {
    QueryType.COUNT: 60,        # 60 seconds — high volatility (live ERP data)
    QueryType.SUM: 60,          # 60 seconds — high volatility
    QueryType.LIST: 3600,       # 1 hour — medium volatility
    QueryType.POLICY: 86400,    # 24 hours — near-static documents
    QueryType.OTHER: 3600,      # 1 hour — default
}


def classify_query(question: str) -> QueryType:
    """Classify question into QueryType enum deterministically without using LLM tokens."""
    if not question or not question.strip():
        return QueryType.OTHER

    q = question.strip().lower()

    # 1. Policy / Document Queries
    if any(t in q for t in ["policy", "procedure", "guideline", "rule", "regulation", "standard operating procedure", "sop"]):
        return QueryType.POLICY

    # 2. Count Queries
    if any(t in q for t in ["how many", "count of", "number of", "total count", "count all"]):
        return QueryType.COUNT

    # 3. Sum / Aggregations
    if any(t in q for t in ["total", "sum of", "sum total", "aggregate", "gross amount", "net amount", "total value"]):
        return QueryType.SUM

    # 4. List Queries
    if any(t in q for t in ["list all", "show all", "give me a table", "show me all", "display all", "fetch all", "get all", "list of", "list distinct"]):
        return QueryType.LIST

    # Fallback to OTHER
    return QueryType.OTHER


# ---------------------------------------------------------------------------
# Backward Compatibility for existing Stage 14 Fast Path references
# ---------------------------------------------------------------------------

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
    """Legacy classification helper for Stage 14."""
    if not user_question or not user_question.strip():
        return EXPLANATION_QUERY

    q = user_question.strip().lower()

    if any(re.search(pat, q) for pat in EXPLANATION_PATTERNS):
        return EXPLANATION_QUERY

    if re.match(r"^(?:list|show me|show|fetch|get|display|find|give me|top)\b", q) and not any(
        re.search(pat, q) for pat in [r"\btotal\b", r"\bsum\b", r"\baverage\b", r"\bavg\b", r"\bhow many\b", r"\bhow much\b"]
    ):
        return LIST_QUERY

    if any(re.search(pat, q) for pat in AGGREGATE_PATTERNS):
        return AGGREGATE_QUERY

    if any(re.search(pat, q) for pat in LIST_PATTERNS):
        return LIST_QUERY

    return EXPLANATION_QUERY

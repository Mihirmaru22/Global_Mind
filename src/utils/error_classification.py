"""Error classification utilities and controlled semantic failure taxonomy."""

from __future__ import annotations

import re
from enum import Enum
from typing import Any


class FailureCategory(str, Enum):
    """Controlled semantic failure taxonomy for pipeline observability and guardrails."""

    # Entity & Schema Resolution
    ENTITY_AMBIGUITY = "ENTITY_AMBIGUITY"
    ACRONYM_NOT_EXPANDED = "ACRONYM_NOT_EXPANDED"
    SCHEMA_RETRIEVAL_MISS = "SCHEMA_RETRIEVAL_MISS"
    INVALID_TABLE = "INVALID_TABLE"
    INVALID_COLUMN = "INVALID_COLUMN"

    # Business Logic & Filtering Constraints
    MISSING_SOFT_DELETE_FILTER = "MISSING_SOFT_DELETE_FILTER"
    MISSING_TEMPORAL_FILTER = "MISSING_TEMPORAL_FILTER"
    DECOMPOSITION_INCOMPLETE = "DECOMPOSITION_INCOMPLETE"

    # Generation, Syntax & Safety
    SQL_SYNTAX_ERROR = "SQL_SYNTAX_ERROR"
    UNSAFE_SQL_OPERATION = "UNSAFE_SQL_OPERATION"

    # Grounding & Synthesis
    CITATION_MISMATCH = "CITATION_MISMATCH"
    UNSUPPORTED_ANSWER_CLAIM = "UNSUPPORTED_ANSWER_CLAIM"

    # Operational & Infrastructure
    TIMEOUT = "TIMEOUT"
    RATE_LIMIT_ERROR = "RATE_LIMIT_ERROR"
    CIRCUIT_BREAKER_OPEN = "CIRCUIT_BREAKER_OPEN"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    PERMISSION_ERROR = "PERMISSION_ERROR"
    DB_EXECUTION_ERROR = "DB_EXECUTION_ERROR"
    EMPTY_RESULT = "EMPTY_RESULT"
    LLM_ERROR = "LLM_ERROR"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    UNKNOWN = "UNKNOWN"


# Backward-compatible list of allowed failure type strings
ALLOWED_FAILURE_TYPES = frozenset({
    "llm_error",
    "schema_retrieval_error",
    "sql_generation_error",
    "sql_validation_error",
    "db_execution_error",
    "empty_result",
    "rate_limit_error",
    "timeout_error",
    "permission_error",
    "budget_exceeded",
    "circuit_breaker_open",
    "unknown_error",
    *(cat.value.lower() for cat in FailureCategory),
    *(cat.value for cat in FailureCategory),
})


def classify_failure_category(
    error: Exception | str | None,
    stage: str | None = None,
    context: dict[str, Any] | None = None,
) -> FailureCategory:
    """Classify an error, guard trigger, or diagnostic into the controlled FailureCategory enum."""
    if error is None:
        return FailureCategory.UNKNOWN

    error_text = str(error).lower()
    exc_name = error.__class__.__name__.lower() if isinstance(error, Exception) else ""

    # Specific semantic checks first:
    # 1. Soft delete
    if any(k in error_text for k in ["soft delete", "soft_delete", "deleted_at"]):
        return FailureCategory.MISSING_SOFT_DELETE_FILTER

    # 2. Temporal filter
    if any(k in error_text for k in ["temporal", "missing date", "date filter", "missing_temporal_filter"]):
        return FailureCategory.MISSING_TEMPORAL_FILTER

    # 3. Citations & Grounding
    if any(k in error_text for k in ["citation", "cite", "chunk reference", "citation_mismatch"]):
        return FailureCategory.CITATION_MISMATCH
    if any(k in error_text for k in ["unsupported claim", "unsupported_answer_claim", "ungrounded", "hallucinated claim"]):
        return FailureCategory.UNSUPPORTED_ANSWER_CLAIM

    # 4. Acronyms & Entity Ambiguity
    if any(k in error_text for k in ["acronym", "acronym_not_expanded"]):
        return FailureCategory.ACRONYM_NOT_EXPANDED
    if any(k in error_text for k in ["entity ambiguity", "ambiguous entity", "entity_ambiguity", "ambiguity", "ambiguous", "multiple matching entities"]):
        return FailureCategory.ENTITY_AMBIGUITY

    # 5. Decomposition
    if any(k in error_text for k in ["decomposition", "decomposition_incomplete", "missing subquery", "dropped constraint"]):
        return FailureCategory.DECOMPOSITION_INCOMPLETE

    # 6. Unsafe SQL
    if any(k in error_text for k in ["unsafe sql", "read-only", "read only", "drop table", "truncate", "delete from", "insert into"]):
        return FailureCategory.UNSAFE_SQL_OPERATION

    # 7. Column vs Table vs Schema
    if any(k in error_text for k in ["unknown column", "no such column", "column validation", "column '", "column \""]):
        return FailureCategory.INVALID_COLUMN
    if any(k in error_text for k in ["table doesn't exist", "no such table", "table '", "table \"", "unknown table", "invalid_table"]):
        return FailureCategory.INVALID_TABLE
    if "schema" in error_text and any(k in error_text for k in ["retriev", "rag", "embed", "not found in schema"]):
        return FailureCategory.SCHEMA_RETRIEVAL_MISS

    # 8. Syntax
    if any(k in error_text for k in ["syntax", "syntaxerror", "parse error", "unparseable"]):
        return FailureCategory.SQL_SYNTAX_ERROR

    # 9. Operational
    if any(k in error_text for k in ["circuit_breaker", "circuitbreaker", "circuit breaker"]):
        return FailureCategory.CIRCUIT_BREAKER_OPEN
    if any(k in error_text for k in ["budget_exceeded", "budgetexceeded", "query budget", "budget exceeded"]):
        return FailureCategory.BUDGET_EXCEEDED
    if any(k in error_text for k in ["rate limit", "429", "tpm", "rpm", "quota", "exhausted", "throttl"]):
        return FailureCategory.RATE_LIMIT_ERROR
    if "timeout" in error_text or "timed out" in error_text or "timeouterror" in exc_name:
        return FailureCategory.TIMEOUT
    if any(k in error_text for k in ["permission", "access denied", "unauthorized", "401", "403", "forbidden"]):
        return FailureCategory.PERMISSION_ERROR
    if any(k in error_text for k in ["empty result", "no rows", "zero rows"]):
        return FailureCategory.EMPTY_RESULT
    if any(k in error_text for k in ["database error", "operationalerror", "programmingerror", "integrityerror", "mysql", "sqlite"]):
        return FailureCategory.DB_EXECUTION_ERROR
    if any(k in error_text for k in ["llm", "provider", "model", "connection error", "api connection", "bad request"]):
        return FailureCategory.LLM_ERROR
    if any(k in error_text for k in ["out of scope", "out_of_scope", "unanswerable", "abstain", "speculative"]):
        return FailureCategory.OUT_OF_SCOPE

    # Stage-based inference fallback
    if stage == "schema_retrieval":
        return FailureCategory.SCHEMA_RETRIEVAL_MISS
    if stage in ("sql_generation", "sql_validation"):
        return FailureCategory.SQL_SYNTAX_ERROR

    return FailureCategory.UNKNOWN


def classify_error(error: Exception | str | None) -> str:
    """Classify an error or exception string into a standard telemetry failure type.

    Maintains 100% backward compatibility with legacy telemetry tests while supporting
    new semantic error signals.
    """
    if error is None:
        return "unknown_error"

    error_text = str(error).lower()
    exc_name = error.__class__.__name__.lower() if isinstance(error, Exception) else ""

    # Budget exceeded & Circuit breaker
    if any(k in error_text for k in ["circuit_breaker", "circuitbreaker", "circuit breaker"]):
        return "circuit_breaker_open"
    if any(k in error_text for k in ["budget_exceeded", "budgetexceeded", "query budget", "budget exceeded"]):
        return "budget_exceeded"

    # Rate limiting & quota
    if any(k in error_text for k in ["rate limit", "429", "tpm", "rpm", "quota", "exhausted", "throttl"]):
        return "rate_limit_error"

    # Timeouts
    if "timeout" in error_text or "timed out" in error_text or "timeouterror" in exc_name:
        return "timeout_error"

    # Permissions & Auth
    if any(k in error_text for k in ["permission", "access denied", "unauthorized", "401", "403", "forbidden"]):
        return "permission_error"

    # SQL Validation & Hallucination
    if any(k in error_text for k in [
        "column validation",
        "alias validation",
        "hallucinat",
        "does not exist",
        "unknown column",
        "no such column",
        "semantic validation",
    ]):
        return "sql_validation_error"

    # SQL Generation / Syntax / Parsing Errors
    if any(k in error_text for k in ["syntax", "syntaxerror", "parse error", "unparseable", "invalid identifier"]):
        return "sql_generation_error"

    # DB Execution Errors
    if any(k in error_text for k in [
        "database error",
        "operationalerror",
        "programmingerror",
        "integrityerror",
        "mysql",
        "sqlite",
        "table doesn't exist",
        "no such table",
    ]):
        return "db_execution_error"

    # Schema Retrieval
    if "schema" in error_text and any(k in error_text for k in ["retriev", "rag", "embed"]):
        return "schema_retrieval_error"

    # LLM Provider Errors
    if any(k in error_text for k in ["llm", "provider", "model", "connection error", "api connection", "bad request"]):
        return "llm_error"

    return "unknown_error"


_FILE_PATH_RE = re.compile(r'(?:/[a-zA-Z0-9_\.\-]+)+')
_TRACEBACK_RE = re.compile(r'Traceback \(most recent call last\):.*?(?=[a-zA-Z0-9_]+Error:|\Z)', re.DOTALL)
_CREDENTIALS_RE = re.compile(r'((?:password|passwd|pwd|secret|key)=)[^\s;&,]+', re.IGNORECASE)


def normalize_error(error: Exception | str | None) -> str:
    """Clean and normalize a raw error message into a concise summary (max 500 chars).

    Strips traceback blocks, internal file paths, and potential credentials.
    """
    if error is None:
        return "unknown_error"

    text = str(error).strip()

    # 1. Remove full traceback header/body if present
    text = _TRACEBACK_RE.sub('', text).strip()

    # 2. Mask any embedded credentials
    text = _CREDENTIALS_RE.sub(r'\1***', text)

    # 3. Strip internal file paths
    text = _FILE_PATH_RE.sub('[path]', text)

    # 4. Clean up excess whitespace and newlines
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    cleaned = " | ".join(lines) if lines else "unknown_error"

    # 5. Truncate to 500 characters
    if len(cleaned) > 500:
        cleaned = cleaned[:497] + "..."

    return cleaned

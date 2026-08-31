"""Error classification utilities for structured telemetry and failure capture."""

from __future__ import annotations

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
})


def classify_error(error: Exception | str) -> str:
    """Classify an error or exception string into a standard telemetry failure type.

    Returns one of the standard failure types defined in ALLOWED_FAILURE_TYPES.
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


import re

_FILE_PATH_RE = re.compile(r'(?:/[a-zA-Z0-9_\.\-]+)+')
_TRACEBACK_RE = re.compile(r'Traceback \(most recent call last\):.*?(?=[a-zA-Z0-9_]+Error:|\Z)', re.DOTALL)
_CREDENTIALS_RE = re.compile(r'((?:password|passwd|pwd|secret|key)=)[^\s;&,]+', re.IGNORECASE)


def normalize_error(error: Exception | str) -> str:
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

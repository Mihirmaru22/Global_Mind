"""Data models for Golden Test Set cases and evaluation outcomes."""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


class GoldenCase(BaseModel):
    """A standardized test case for evaluating SQL repair logic."""

    case_id: str
    description: str  # Brief explanation of the error
    user_question: str  # The natural language intent
    failed_sql: str
    error_message: str  # The normalized DB/Validation error
    error_type: str  # e.g. 'column_not_found', 'table_not_found', 'ambiguous_column', 'syntax_error', 'type_mismatch', 'missing_join'
    schema_context: dict[str, list[str]] = Field(default_factory=dict)  # Minimal schema needed to fix it
    expected_sql_contains: list[str] = Field(default_factory=list)  # Substrings that MUST appear in repaired SQL
    must_not_contain: list[str] = Field(default_factory=list)  # Substrings that MUST NOT appear in repaired SQL
    ideal_sql: str | None = None  # Reference valid repair SQL
    metadata: dict[str, Any] = Field(default_factory=dict)


class CaseEvaluationResult(BaseModel):
    """Outcome of evaluating a single GoldenCase against a repair function."""

    case_id: str
    passed: bool
    repaired_sql: str
    syntax_valid: bool
    missing_expected: list[str] = Field(default_factory=list)
    found_forbidden: list[str] = Field(default_factory=list)
    error_detail: str | None = None


class GoldenEvaluationSummary(BaseModel):
    """Aggregated outcome of a golden test set evaluation run."""

    total_cases: int
    passed_cases: int
    failed_cases: int
    pass_rate: float
    results: list[CaseEvaluationResult] = Field(default_factory=list)

"""Utility modules for SQL pipeline optimization."""

from src.utils.circuit_breaker import (
    CircuitBreakerOpenError,
    ProviderCircuitBreaker,
    get_shared_circuit_breaker,
    is_severe_provider_failure,
)
from src.utils.empty_result_classifier import (
    SUSPICIOUS_EMPTY,
    VALID_EMPTY,
    classify_empty_result,
)
from src.utils.error_classification import classify_error, normalize_error
from src.utils.failure_capture import capture_sql_failure
from src.utils.fast_path import (
    build_aggregate_micro_prompt,
    format_aggregate_fast_path,
    format_list_fast_path,
)
from src.utils.feature_flags import is_feature_enabled
from src.utils.query_budget import (
    QueryBudgetController,
    QueryBudgetExceededError,
    get_current_budget_controller,
    get_or_create_budget_controller,
    set_current_budget_controller,
)
from src.utils.query_classifier import (
    AGGREGATE_QUERY,
    EXPLANATION_QUERY,
    LIST_QUERY,
    classify_query_intent,
)
from src.utils.schema_budget import DEFAULT_SCHEMA_TOKEN_BUDGET, select_schema_within_budget
from src.utils.schema_compactor import AUDIT_COLUMNS, compact_ddl, extract_join_hints
from src.utils.schema_token_estimator import estimate_schema_tokens
from src.utils.sql_safety import (
    check_dangerous_patterns,
    is_destructive_sql,
    parse_sql,
    validate_sql_safety,
    validate_tables_and_columns,
)
from src.utils.telemetry import capture_telemetry, log_telemetry, timed_stage

__all__ = [
    "AGGREGATE_QUERY",
    "AUDIT_COLUMNS",
    "CircuitBreakerOpenError",
    "DEFAULT_SCHEMA_TOKEN_BUDGET",
    "EXPLANATION_QUERY",
    "LIST_QUERY",
    "ProviderCircuitBreaker",
    "QueryBudgetController",
    "QueryBudgetExceededError",
    "SUSPICIOUS_EMPTY",
    "VALID_EMPTY",
    "build_aggregate_micro_prompt",
    "capture_sql_failure",
    "capture_telemetry",
    "check_dangerous_patterns",
    "classify_empty_result",
    "classify_error",
    "classify_query_intent",
    "compact_ddl",
    "estimate_schema_tokens",
    "extract_join_hints",
    "format_aggregate_fast_path",
    "format_list_fast_path",
    "get_current_budget_controller",
    "get_or_create_budget_controller",
    "get_shared_circuit_breaker",
    "is_destructive_sql",
    "is_feature_enabled",
    "is_severe_provider_failure",
    "log_telemetry",
    "normalize_error",
    "parse_sql",
    "select_schema_within_budget",
    "set_current_budget_controller",
    "timed_stage",
    "validate_sql_safety",
    "validate_tables_and_columns",
]


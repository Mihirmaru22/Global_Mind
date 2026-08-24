"""Query Budget Controller for enforcing per-query resource constraints."""

from __future__ import annotations

import contextvars
import logging
from typing import Any

logger = logging.getLogger(__name__)


class QueryBudgetExceededError(RuntimeError):
    """Raised when a query exceeds its allocated resource budget."""
    pass


class QueryBudgetController:
    """Tracks and governs resource consumption for a single query.

    Enforces hard limits on:
    1. Maximum total LLM calls (default: 4)
    2. Maximum repair attempts (default: 2)
    3. Maximum total token usage (default: 15,000)
    """

    def __init__(
        self,
        query_id: str = "",
        max_llm_calls: int = 4,
        max_repairs: int = 2,
        max_tokens: int = 15000,
    ) -> None:
        self.query_id = query_id
        self.max_llm_calls = max_llm_calls
        self.max_repairs = max_repairs
        self.max_tokens = max_tokens

        self.llm_calls = 0
        self.repair_attempts = 0
        self.total_tokens = 0

    def record_call(self, tokens_used: int = 0, is_repair: bool = False) -> None:
        """Records an LLM call and updates token/repair counters."""
        self.llm_calls += 1
        self.total_tokens += max(0, int(tokens_used or 0))
        if is_repair:
            self.repair_attempts += 1

        logger.debug(
            "QueryBudget [%s]: recorded call (tokens=%d, is_repair=%s) -> calls=%d/%d, repairs=%d/%d, tokens=%d/%d",
            self.query_id,
            tokens_used,
            is_repair,
            self.llm_calls,
            self.max_llm_calls,
            self.repair_attempts,
            self.max_repairs,
            self.total_tokens,
            self.max_tokens,
        )

    def can_proceed(self, is_repair: bool = False) -> bool:
        """Returns True if the query is within its budget, False if limits are reached/exceeded."""
        if self.llm_calls >= self.max_llm_calls:
            return False
        if self.total_tokens >= self.max_tokens:
            return False
        if is_repair and self.repair_attempts >= self.max_repairs:
            return False
        return True

    def get_budget_status(self) -> dict[str, Any]:
        """Returns the current usage state for reporting and telemetry."""
        return {
            "query_id": self.query_id,
            "llm_calls": self.llm_calls,
            "max_llm_calls": self.max_llm_calls,
            "repair_attempts": self.repair_attempts,
            "max_repairs": self.max_repairs,
            "total_tokens": self.total_tokens,
            "max_tokens": self.max_tokens,
            "can_proceed": self.can_proceed(),
            "exhausted": not self.can_proceed(),
        }


# ---------------------------------------------------------------------------
# Context Propagation via ContextVar
# ---------------------------------------------------------------------------

_CURRENT_BUDGET_CONTROLLER: contextvars.ContextVar[QueryBudgetController | None] = (
    contextvars.ContextVar("current_budget_controller", default=None)
)


def get_current_budget_controller() -> QueryBudgetController | None:
    """Retrieve the active QueryBudgetController from the async context."""
    return _CURRENT_BUDGET_CONTROLLER.get()


def set_current_budget_controller(
    controller: QueryBudgetController | None,
) -> contextvars.Token[QueryBudgetController | None]:
    """Bind a QueryBudgetController to the current async context."""
    return _CURRENT_BUDGET_CONTROLLER.set(controller)


def get_or_create_budget_controller(
    query_id: str | None = None,
    max_llm_calls: int = 4,
    max_repairs: int = 2,
    max_tokens: int = 15000,
) -> QueryBudgetController:
    """Get the active budget controller or lazily initialize and bind a new one."""
    current = get_current_budget_controller()
    if current is not None:
        if query_id and not current.query_id:
            current.query_id = query_id
        return current

    controller = QueryBudgetController(
        query_id=query_id or "",
        max_llm_calls=max_llm_calls,
        max_repairs=max_repairs,
        max_tokens=max_tokens,
    )
    set_current_budget_controller(controller)
    return controller

"""Query Budget Controller for enforcing real-time per-query resource constraints."""

from __future__ import annotations

import contextvars
import logging
import os
from typing import Any

from src.utils.stream_token_counter import (
    QueryBudgetExceededError,
    StreamTokenCounter,
    TokenBudgetExceededError,
)

logger = logging.getLogger(__name__)


class QueryBudgetController:
    """Tracks and governs resource consumption for a single query in real-time.

    Enforces hard limits on:
    1. Maximum total LLM calls (default: 4)
    2. Maximum repair attempts (default: 2)
    3. Maximum total token usage (default: 8,000 via StreamTokenCounter)
    """

    def __init__(
        self,
        query_id: str = "",
        hard_limit: int = 8000,
        safety_buffer: int = 200,
        max_llm_calls: int = 4,
        max_repairs: int = 2,
        max_tokens: int = 8000,
        model_name: str = "",
        provider_name: str = "",
    ) -> None:
        self.query_id = query_id
        self.max_llm_calls = max_llm_calls
        self.max_repairs = max_repairs
        
        # Read environment variable override if set
        env_ceiling = os.getenv("QUERY_TOKEN_CEILING")
        if env_ceiling:
            try:
                hard_limit = int(env_ceiling)
                max_tokens = int(env_ceiling)
            except ValueError:
                pass

        self.max_tokens = max(int(max_tokens or 8000), int(hard_limit or 8000))
        self.safety_buffer = int(safety_buffer)

        self.counter = StreamTokenCounter(
            hard_limit=self.max_tokens,
            safety_buffer=self.safety_buffer,
            model_name=model_name,
            provider_name=provider_name,
        )

        self.llm_calls = 0
        self.repair_attempts = 0
        self._manual_tokens = 0

    @property
    def total_tokens(self) -> int:
        return max(self.counter.current_count, self._manual_tokens)

    @total_tokens.setter
    def total_tokens(self, value: int) -> None:
        self._manual_tokens = int(value or 0)

    def record_chunk(self, text: str) -> int:
        """Record an incoming stream chunk and immediately check for limit breach."""
        added = self.counter.add_chunk(text)
        self.counter.raise_if_exceeded()
        return added

    def record_call(self, tokens_used: int = 0, is_repair: bool = False) -> None:
        """Records an LLM call and updates token/repair counters."""
        self.llm_calls += 1
        tokens_val = max(0, int(tokens_used or 0))
        self._manual_tokens += tokens_val
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

    def increase_limit(self, amount: int = 1000) -> None:
        """Dynamically increase the token limit for recovery retry attempts."""
        self.max_tokens += amount
        self.counter.hard_limit += amount
        self.counter.is_exceeded = False
        logger.info(
            "QueryBudget [%s]: limit increased by %d -> new hard_limit=%d",
            self.query_id,
            amount,
            self.counter.hard_limit,
        )

    def get_current_usage(self) -> int:
        """Return the current token count."""
        return self.total_tokens

    def can_proceed(self, is_repair: bool = False) -> bool:
        """Returns True if the query is within its budget, False if limits are reached/exceeded."""
        if self.llm_calls >= self.max_llm_calls:
            return False
        if self.counter.check_limit() or self.total_tokens >= (self.max_tokens + self.safety_buffer):
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
            "safety_buffer": self.safety_buffer,
            "is_exceeded": self.counter.is_exceeded,
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
    hard_limit: int = 8000,
    safety_buffer: int = 200,
    max_llm_calls: int = 4,
    max_repairs: int = 2,
    max_tokens: int = 8000,
    model_name: str = "",
    provider_name: str = "",
    force_new: bool = False,
) -> QueryBudgetController:
    """Get the active budget controller or lazily initialize and bind a new one."""
    current = get_current_budget_controller()
    if not force_new and current is not None:
        if not query_id or current.query_id == query_id:
            return current
        if not current.query_id and query_id:
            current.query_id = query_id
            return current

    controller = QueryBudgetController(
        query_id=query_id or "",
        hard_limit=hard_limit,
        safety_buffer=safety_buffer,
        max_llm_calls=max_llm_calls,
        max_repairs=max_repairs,
        max_tokens=max_tokens,
        model_name=model_name,
        provider_name=provider_name,
    )
    set_current_budget_controller(controller)
    return controller

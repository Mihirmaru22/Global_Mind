"""Unit tests for QueryBudgetController governance and resource tracking."""

import pytest

from src.utils.query_budget import (
    QueryBudgetController,
    QueryBudgetExceededError,
    get_current_budget_controller,
    get_or_create_budget_controller,
    set_current_budget_controller,
)


def test_budget_llm_calls_limit() -> None:
    """Assert that can_proceed() returns False once max_llm_calls is reached."""
    controller = QueryBudgetController(query_id="test-q1", max_llm_calls=3, max_repairs=2, max_tokens=10000)

    assert controller.can_proceed() is True
    assert controller.llm_calls == 0

    # Call 1
    controller.record_call(tokens_used=100)
    assert controller.can_proceed() is True
    assert controller.llm_calls == 1

    # Call 2
    controller.record_call(tokens_used=200)
    assert controller.can_proceed() is True
    assert controller.llm_calls == 2

    # Call 3 (reaches max_llm_calls=3)
    controller.record_call(tokens_used=300)
    assert controller.llm_calls == 3
    assert controller.can_proceed() is False


def test_budget_repairs_limit() -> None:
    """Assert that can_proceed(is_repair=True) returns False once max_repairs is reached."""
    controller = QueryBudgetController(query_id="test-q2", max_llm_calls=10, max_repairs=2, max_tokens=10000)

    assert controller.can_proceed(is_repair=True) is True

    # Repair 1
    controller.record_call(tokens_used=150, is_repair=True)
    assert controller.repair_attempts == 1
    assert controller.llm_calls == 1
    assert controller.can_proceed(is_repair=True) is True

    # Repair 2 (reaches max_repairs=2)
    controller.record_call(tokens_used=150, is_repair=True)
    assert controller.repair_attempts == 2
    assert controller.can_proceed(is_repair=True) is False
    # General non-repair calls might still be allowed if under max_llm_calls
    assert controller.can_proceed(is_repair=False) is True


def test_budget_tokens_limit() -> None:
    """Assert that can_proceed() returns False once total_tokens exceeds or equals max_tokens."""
    controller = QueryBudgetController(query_id="test-q3", max_llm_calls=10, max_repairs=5, max_tokens=1000)

    assert controller.can_proceed() is True

    controller.record_call(tokens_used=600)
    assert controller.total_tokens == 600
    assert controller.can_proceed() is True

    controller.record_call(tokens_used=400)
    assert controller.total_tokens == 1000
    assert controller.can_proceed() is False


def test_budget_status_dict() -> None:
    """Assert get_budget_status() returns an accurate dictionary representation."""
    controller = QueryBudgetController(query_id="gm-q-status-check", max_llm_calls=4, max_repairs=2, max_tokens=5000)
    controller.record_call(tokens_used=1200, is_repair=True)

    status = controller.get_budget_status()
    assert status["query_id"] == "gm-q-status-check"
    assert status["llm_calls"] == 1
    assert status["max_llm_calls"] == 4
    assert status["repair_attempts"] == 1
    assert status["max_repairs"] == 2
    assert status["total_tokens"] == 1200
    assert status["max_tokens"] == 5000
    assert status["can_proceed"] is True
    assert status["exhausted"] is False

    controller.record_call(tokens_used=4000, is_repair=False)
    status_exhausted = controller.get_budget_status()
    assert status_exhausted["total_tokens"] == 5200
    assert status_exhausted["can_proceed"] is False
    assert status_exhausted["exhausted"] is True


def test_budget_contextvar_propagation() -> None:
    """Assert that get_or_create_budget_controller properly binds and shares context."""
    token = set_current_budget_controller(None)
    try:
        assert get_current_budget_controller() is None

        ctrl = get_or_create_budget_controller(query_id="test-ctx-123")
        assert ctrl.query_id == "test-ctx-123"
        assert get_current_budget_controller() is ctrl

        # Re-fetching returns the exact same instance
        ctrl2 = get_or_create_budget_controller()
        assert ctrl2 is ctrl

        ctrl.record_call(tokens_used=500)
        assert ctrl2.total_tokens == 500
    finally:
        set_current_budget_controller(None)

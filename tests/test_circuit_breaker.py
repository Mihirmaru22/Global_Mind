"""Unit tests for ProviderCircuitBreaker and failure tripping rules."""

import time
from unittest.mock import patch
import pytest

from src.utils.circuit_breaker import (
    CircuitBreakerOpenError,
    ProviderCircuitBreaker,
    is_severe_provider_failure,
)


class DummyHTTPError(Exception):
    def __init__(self, status_code: int, message: str = "") -> None:
        super().__init__(f"HTTP {status_code}: {message}")
        self.status_code = status_code


def test_circuit_breaker_trips_on_consecutive_429() -> None:
    """Assert that 3 consecutive 429 rate limit errors trip the circuit breaker."""
    cb = ProviderCircuitBreaker(failure_threshold=3, cooldown_seconds=60.0)
    provider = "test_groq"

    assert cb.is_open(provider) is False

    # Failure 1
    cb.record_failure(provider, DummyHTTPError(429, "Rate limit exceeded"))
    assert cb.is_open(provider) is False

    # Failure 2
    cb.record_failure(provider, DummyHTTPError(429, "Rate limit exceeded"))
    assert cb.is_open(provider) is False

    # Failure 3 (Threshold reached -> Breaker Trips)
    cb.record_failure(provider, DummyHTTPError(429, "Rate limit exceeded"))
    assert cb.is_open(provider) is True


def test_circuit_breaker_trips_on_503_and_timeouts() -> None:
    """Assert that 503 Service Unavailable and Timeout errors count towards the threshold."""
    cb = ProviderCircuitBreaker(failure_threshold=3, cooldown_seconds=60.0)
    provider = "test_nim"

    cb.record_failure(provider, DummyHTTPError(503, "Service Unavailable"))
    cb.record_failure(provider, TimeoutError("Connection timed out after 30s"))
    assert cb.is_open(provider) is False

    cb.record_failure(provider, DummyHTTPError(503, "Overloaded"))
    assert cb.is_open(provider) is True


def test_circuit_breaker_ignores_bad_request_and_validation() -> None:
    """Assert that 400 Bad Request or validation errors do NOT trip the breaker."""
    cb = ProviderCircuitBreaker(failure_threshold=3, cooldown_seconds=60.0)
    provider = "test_openai"

    for _ in range(5):
        cb.record_failure(provider, DummyHTTPError(400, "Bad Request: invalid prompt syntax"))
        cb.record_failure(provider, ValueError("Validation error: missing parameter"))

    # Breaker must stay CLOSED
    assert cb.is_open(provider) is False
    status = cb.get_status()
    assert status.get(provider, {}).get("consecutive_failures", 0) == 0


def test_circuit_breaker_success_resets_failure_count() -> None:
    """Assert that a successful call resets the consecutive failure count."""
    cb = ProviderCircuitBreaker(failure_threshold=3, cooldown_seconds=60.0)
    provider = "test_gemini"

    # 2 failures
    cb.record_failure(provider, DummyHTTPError(429, "Too Many Requests"))
    cb.record_failure(provider, DummyHTTPError(429, "Too Many Requests"))
    assert cb.is_open(provider) is False

    # Success resets counter
    cb.record_success(provider)

    # Another failure is now count 1, not 3
    cb.record_failure(provider, DummyHTTPError(429, "Too Many Requests"))
    assert cb.is_open(provider) is False


def test_circuit_breaker_cooldown_expiry() -> None:
    """Assert that after cooldown_seconds elapses, the circuit automatically recovers."""
    cb = ProviderCircuitBreaker(failure_threshold=2, cooldown_seconds=30.0)
    provider = "test_openrouter"

    current_fake_time = 1000.0

    with patch("time.time", side_effect=lambda: current_fake_time):
        cb.record_failure(provider, DummyHTTPError(429, "Rate limit"))
        cb.record_failure(provider, DummyHTTPError(429, "Rate limit"))
        assert cb.is_open(provider) is True

        # Advance time by 15s (still cooling down)
        current_fake_time += 15.0
        assert cb.is_open(provider) is True

        # Advance time past 30s cooldown
        current_fake_time += 16.0
        assert cb.is_open(provider) is False


def test_is_severe_provider_failure_helper() -> None:
    """Assert severe failure helper correctly categorizes errors."""
    assert is_severe_provider_failure(DummyHTTPError(429)) is True
    assert is_severe_provider_failure(DummyHTTPError(503)) is True
    assert is_severe_provider_failure(DummyHTTPError(502)) is True
    assert is_severe_provider_failure(DummyHTTPError(504)) is True
    assert is_severe_provider_failure(TimeoutError("Read timed out")) is True
    assert is_severe_provider_failure(Exception("httpx.ConnectError: Connection refused")) is True

    # Non-severe / permanent / client errors
    assert is_severe_provider_failure(DummyHTTPError(400)) is False
    assert is_severe_provider_failure(DummyHTTPError(401)) is False
    assert is_severe_provider_failure(DummyHTTPError(403)) is False
    assert is_severe_provider_failure(DummyHTTPError(404)) is False
    assert is_severe_provider_failure(ValueError("Bad column name")) is False
    assert is_severe_provider_failure(None) is False

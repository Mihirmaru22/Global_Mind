"""Provider Circuit Breaker for halting calls to failing/rate-limiting LLM providers."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)


class CircuitBreakerOpenError(RuntimeError):
    """Raised when an LLM provider's circuit breaker is open (tripped/cooling down)."""
    pass


# Errors that should NOT trip the circuit breaker (client mistakes or permanent auth/route issues)
_NON_CIRCUIT_ERRORS = (
    "bad request",
    "validation",
    "invalid argument",
    "unauthorized",
    "forbidden",
    "not found",
    "does not exist",
    "invalid model",
    "end of life",
)

# Markers for severe/transient provider-level failures that SHOULD count towards tripping
_SEVERE_FAILURE_MARKERS = (
    "429",
    "503",
    "502",
    "504",
    "rate limit",
    "too many requests",
    "service unavailable",
    "service overloaded",
    "overloaded",
    "server error",
    "gateway timeout",
    "timed out",
    "timeout",
    "connecterror",
    "connection error",
    "connection refused",
    "readtimeout",
    "remotedisconnected",
)


def is_severe_provider_failure(exc: Exception | None) -> bool:
    """Determine whether an exception indicates an upstream provider outage/throttle.

    Trips for: 429 (Rate Limit), 503 (Service Unavailable), 502/504, Connection Timeouts.
    Does NOT trip for: 400 Bad Request (syntax/formatting), 401/403 (Auth), 404 (Not Found).
    """
    if exc is None:
        return False

    status = getattr(exc, "status_code", None)
    response = getattr(exc, "response", None)
    if status is None and response is not None:
        status = getattr(response, "status_code", None)

    # 400 Bad Request or 401/403/404 shouldn't trip circuit breaker
    if status in (400, 401, 403, 404, 410, 422):
        return False

    if status in (429, 502, 503, 504):
        return True

    low_msg = str(exc).lower()

    if any(marker in low_msg for marker in _NON_CIRCUIT_ERRORS):
        return False

    if any(marker in low_msg for marker in _SEVERE_FAILURE_MARKERS):
        return True

    # Generic or unknown runtime errors default to non-severe unless matching severe patterns
    return False


class ProviderCircuitBreaker:
    """Thread-safe circuit breaker tracking consecutive failures per LLM provider.

    States:
    - CLOSED (Normal): Failures below threshold. Calls allowed.
    - OPEN (Tripped): Threshold reached. Calls blocked until cooldown expires.
    - HALF-OPEN (Recovery): Cooldown expired. Next attempt tests provider health.
    """

    def __init__(
        self,
        failure_threshold: int = 3,
        cooldown_seconds: float = 60.0,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._lock = threading.Lock()
        self._consecutive_failures: dict[str, int] = {}
        self._open_until: dict[str, float] = {}

    def record_success(self, provider: str) -> None:
        """Reset failure counts and close the circuit upon a successful call."""
        with self._lock:
            self._consecutive_failures[provider] = 0
            self._open_until.pop(provider, None)
            logger.debug("Circuit breaker: recorded success for provider '%s'", provider)

    def record_failure(self, provider: str, error: Exception | None = None) -> None:
        """Record a failure for the provider. If severe, increment counter and trip if threshold met."""
        if not is_severe_provider_failure(error):
            logger.debug(
                "Circuit breaker: ignoring non-severe error for provider '%s': %s",
                provider, error,
            )
            return

        with self._lock:
            count = self._consecutive_failures.get(provider, 0) + 1
            self._consecutive_failures[provider] = count

            if count >= self.failure_threshold:
                trip_until = time.time() + self.cooldown_seconds
                self._open_until[provider] = trip_until
                logger.warning(
                    "Circuit breaker TRIPPED for provider '%s': %d consecutive severe failures. "
                    "Cooling down for %.1fs (until %s).",
                    provider, count, self.cooldown_seconds, time.ctime(trip_until),
                )
            else:
                logger.info(
                    "Circuit breaker: provider '%s' failure %d/%d (error: %s)",
                    provider, count, self.failure_threshold, error,
                )

    def is_open(self, provider: str) -> bool:
        """Return True if the provider's circuit is currently OPEN (cooling down)."""
        with self._lock:
            open_until = self._open_until.get(provider)
            if open_until is None:
                return False

            now = time.time()
            if now >= open_until:
                # Cooldown period expired -> transition to half-open/closed
                logger.info(
                    "Circuit breaker: cooldown expired for provider '%s'. Resetting to half-open.",
                    provider,
                )
                self._open_until.pop(provider, None)
                self._consecutive_failures[provider] = 0
                return False

            return True

    def get_status(self) -> dict[str, dict[str, Any]]:
        """Return a snapshot of circuit breaker states across all known providers."""
        with self._lock:
            now = time.time()
            all_providers = set(self._consecutive_failures.keys()) | set(self._open_until.keys())
            status: dict[str, dict[str, Any]] = {}
            for prov in sorted(all_providers):
                until = self._open_until.get(prov, 0.0)
                open_flag = until > now
                status[prov] = {
                    "consecutive_failures": self._consecutive_failures.get(prov, 0),
                    "is_open": open_flag,
                    "cooldown_remaining_s": round(max(0.0, until - now), 2),
                    "threshold": self.failure_threshold,
                    "cooldown_total_s": self.cooldown_seconds,
                }
            return status

    def reset_all(self) -> None:
        """Clear all provider states (for testing or administrative override)."""
        with self._lock:
            self._consecutive_failures.clear()
            self._open_until.clear()


# ---------------------------------------------------------------------------
# Shared Process-wide Circuit Breaker Singleton
# ---------------------------------------------------------------------------

_shared_circuit_breaker: ProviderCircuitBreaker | None = None


def get_shared_circuit_breaker() -> ProviderCircuitBreaker:
    """Return the process-wide ProviderCircuitBreaker singleton."""
    global _shared_circuit_breaker
    if _shared_circuit_breaker is None:
        _shared_circuit_breaker = ProviderCircuitBreaker()
    return _shared_circuit_breaker

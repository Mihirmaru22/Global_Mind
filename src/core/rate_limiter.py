"""Cross-provider rate limiter with per-provider tracking and exponential backoff.

Designed for the free-tier constraint: each provider has its own RPM/RPD limits,
and when one is exhausted the ProviderRouter should fall through to the next —
not block waiting for the same provider to recover.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ProviderLimits:
    """Rate limit configuration for a single provider."""
    rpm: int = 60           # Requests per minute
    rpd: int = 10000        # Requests per day
    min_interval_ms: int = 0  # Minimum milliseconds between requests


# Known free-tier limits — conservative estimates (better to under-estimate
# and fallback than to hit 429s).
DEFAULT_LIMITS: dict[str, ProviderLimits] = {
    "gemini": ProviderLimits(rpm=10, rpd=1500),
    "nvidia_nim": ProviderLimits(rpm=30, rpd=5000),
    "groq": ProviderLimits(rpm=25, rpd=5000),
    "openrouter": ProviderLimits(rpm=15, rpd=200),
    "ocr_space": ProviderLimits(rpm=10, rpd=800),  # ~25K/month ÷ 30 days
    "jina": ProviderLimits(rpm=80, rpd=50000),
}


@dataclass
class _ProviderState:
    """Mutable state tracking for one provider's rate consumption."""
    request_timestamps: list[float] = field(default_factory=list)
    daily_count: int = 0
    day_start: float = field(default_factory=time.time)
    backoff_until: float = 0.0  # If set, don't send requests until this time


class RateLimiter:
    """Manages rate limits across all providers.

    Usage:
        limiter = RateLimiter()
        await limiter.acquire("gemini")  # blocks if needed, raises if exhausted
    """

    def __init__(self, limits: dict[str, ProviderLimits] | None = None) -> None:
        self._limits = limits or DEFAULT_LIMITS
        self._states: dict[str, _ProviderState] = {}
        self._lock = asyncio.Lock()

    def _get_state(self, provider: str) -> _ProviderState:
        if provider not in self._states:
            self._states[provider] = _ProviderState()
        return self._states[provider]

    def _get_limits(self, provider: str) -> ProviderLimits:
        return self._limits.get(provider, ProviderLimits())

    async def acquire(self, provider: str) -> None:
        """Acquire a rate-limit slot for the given provider.

        Blocks briefly if we're close to the RPM limit.
        Raises RuntimeError if the daily limit is exhausted.
        """
        async with self._lock:
            state = self._get_state(provider)
            limits = self._get_limits(provider)
            now = time.time()

            # Reset daily counter if a new day has started
            if now - state.day_start > 86400:
                state.daily_count = 0
                state.day_start = now

            # Check daily limit
            if state.daily_count >= limits.rpd:
                raise RuntimeError(
                    f"Provider '{provider}' daily rate limit exhausted "
                    f"({limits.rpd} requests/day)"
                )

            # Check backoff
            if now < state.backoff_until:
                wait = state.backoff_until - now
                logger.info("Rate limiter: waiting %.1fs for %s backoff", wait, provider)
                await asyncio.sleep(wait)

            # Prune old timestamps (older than 60s)
            cutoff = now - 60.0
            state.request_timestamps = [t for t in state.request_timestamps if t > cutoff]

            # Check RPM
            if len(state.request_timestamps) >= limits.rpm:
                oldest = state.request_timestamps[0]
                wait = 60.0 - (now - oldest) + 0.1  # small buffer
                if wait > 0:
                    logger.info("Rate limiter: waiting %.1fs for %s RPM", wait, provider)
                    await asyncio.sleep(wait)

            # Record this request
            state.request_timestamps.append(time.time())
            state.daily_count += 1

    def report_429(self, provider: str, retry_after: float = 5.0) -> None:
        """Report a 429 response — sets a backoff period for this provider."""
        state = self._get_state(provider)
        state.backoff_until = time.time() + retry_after
        logger.warning(
            "Rate limiter: provider '%s' returned 429, backing off %.1fs",
            provider,
            retry_after,
        )

    def get_stats(self) -> dict[str, dict[str, int | float]]:
        """Return current usage stats for all providers."""
        stats = {}
        now = time.time()
        for provider, state in self._states.items():
            limits = self._get_limits(provider)
            cutoff = now - 60.0
            recent = [t for t in state.request_timestamps if t > cutoff]
            stats[provider] = {
                "rpm_used": len(recent),
                "rpm_limit": limits.rpm,
                "rpd_used": state.daily_count,
                "rpd_limit": limits.rpd,
            }
        return stats

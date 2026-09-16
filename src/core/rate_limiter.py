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
    tpm: int = 100000       # Tokens per minute
    tpd: int = 2000000      # Tokens per day
    min_interval_ms: int = 0  # Minimum milliseconds between requests


# Known free-tier limits — realistic free tier thresholds (tokens are often the true bottleneck).
DEFAULT_LIMITS: dict[str, ProviderLimits] = {
    "gemini": ProviderLimits(rpm=15, rpd=1500, tpm=1000000, tpd=5000000),
    "nvidia_nim": ProviderLimits(rpm=30, rpd=5000, tpm=300000, tpd=5000000),
    "groq": ProviderLimits(rpm=30, rpd=14400, tpm=6000, tpd=200000),
    "openrouter": ProviderLimits(rpm=15, rpd=200, tpm=20000, tpd=500000),
    "ocr_space": ProviderLimits(rpm=10, rpd=800, tpm=50000, tpd=500000),  # ~25K/month ÷ 30 days
    "jina": ProviderLimits(rpm=80, rpd=50000, tpm=500000, tpd=10000000),
}


@dataclass
class _ProviderState:
    """Mutable state tracking for one provider's rate and token consumption."""
    request_timestamps: list[float] = field(default_factory=list)
    daily_count: int = 0
    token_timestamps: list[tuple[float, int]] = field(default_factory=list)
    daily_tokens: int = 0
    day_start: float = field(default_factory=time.time)
    backoff_until: float = 0.0  # If set, don't send requests until this time


class RateLimiter:
    """Manages rate and token limits across all providers.

    Usage:
        limiter = RateLimiter()
        await limiter.acquire("gemini")  # blocks if needed, raises if exhausted
        limiter.record_tokens("gemini", 1250)
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

    def record_tokens(self, provider: str, tokens: int) -> None:
        """Record token consumption for a completed call."""
        if tokens <= 0:
            return
        state = self._get_state(provider)
        now = time.time()
        # Reset daily counters if 24h passed
        if now - state.day_start > 86400:
            state.daily_count = 0
            state.daily_tokens = 0
            state.day_start = now

        # Prune tokens older than 60s
        cutoff = now - 60.0
        state.token_timestamps = [(t, count) for t, count in state.token_timestamps if t > cutoff]
        state.token_timestamps.append((now, tokens))
        state.daily_tokens += tokens

    async def acquire(self, provider: str) -> None:
        """Acquire a rate-limit slot for the given provider.

        Blocks briefly if we're close to the RPM limit.
        Raises RuntimeError if the daily limit or token limit is exhausted.
        """
        async with self._lock:
            state = self._get_state(provider)
            limits = self._get_limits(provider)
            now = time.time()

            # Reset daily counter if a new day has started
            if now - state.day_start > 86400:
                state.daily_count = 0
                state.daily_tokens = 0
                state.day_start = now

            # Check daily request limit
            if state.daily_count >= limits.rpd:
                raise RuntimeError(
                    f"Provider '{provider}' daily rate limit exhausted "
                    f"({limits.rpd} requests/day)"
                )

            # Check daily token limit
            if limits.tpd > 0 and state.daily_tokens >= limits.tpd:
                logger.info(
                    "Rate limiter: provider %s daily token limit exhausted (%d/%d) — rejecting to trigger fallback",
                    provider,
                    state.daily_tokens,
                    limits.tpd,
                )
                raise RuntimeError(
                    f"Provider '{provider}' daily token limit exhausted "
                    f"({state.daily_tokens}/{limits.tpd} tokens/day)"
                )

            # Check backoff
            if now < state.backoff_until:
                wait = state.backoff_until - now
                logger.info("Rate limiter: provider %s is in backoff (%.1fs remaining) — rejecting to trigger fallback", provider, wait)
                raise RuntimeError(f"Provider '{provider}' is currently rate-limited (backoff).")

            # Prune old timestamps (older than 60s)
            cutoff = now - 60.0
            state.request_timestamps = [t for t in state.request_timestamps if t > cutoff]
            state.token_timestamps = [(t, count) for t, count in state.token_timestamps if t > cutoff]

            # Check RPM
            if len(state.request_timestamps) >= limits.rpm:
                oldest = state.request_timestamps[0]
                wait = 60.0 - (now - oldest) + 0.1  # small buffer
                if wait > 0:
                    logger.info("Rate limiter: provider %s RPM exhausted (wait %.1fs) — rejecting to trigger fallback", provider, wait)
                    raise RuntimeError(f"Provider '{provider}' RPM limit exhausted.")

            # Check rolling 60s TPM
            current_tpm = sum(count for _, count in state.token_timestamps)
            if limits.tpm > 0 and current_tpm >= limits.tpm:
                logger.info(
                    "Rate limiter: provider %s TPM exhausted (%d/%d) — rejecting to trigger fallback",
                    provider,
                    current_tpm,
                    limits.tpm,
                )
                raise RuntimeError(f"Provider '{provider}' TPM limit exhausted.")

            # Record this request
            state.request_timestamps.append(time.time())
            state.daily_count += 1

    def seconds_until_available(self, provider: str) -> float:
        """Remaining 429 backoff for a provider (0.0 if not backed off).

        Lets the router decide whether a rate-limited provider is worth waiting a
        moment for and retrying, instead of hard-failing the whole chain the
        instant every provider has been tried once.
        """
        state = self._states.get(provider)
        if state is None:
            return 0.0
        return max(0.0, state.backoff_until - time.time())

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
            recent_reqs = [t for t in state.request_timestamps if t > cutoff]
            recent_tpm = sum(c for t, c in state.token_timestamps if t > cutoff)
            stats[provider] = {
                "rpm_used": len(recent_reqs),
                "rpm_limit": limits.rpm,
                "rpd_used": state.daily_count,
                "rpd_limit": limits.rpd,
                "tpm_used": recent_tpm,
                "tpm_limit": limits.tpm,
                "tpd_used": state.daily_tokens,
                "tpd_limit": limits.tpd,
            }
        return stats

    def usage_snapshot(
        self, providers: list[str] | None = None
    ) -> dict[str, dict[str, int | float]]:
        """Per-provider quota usage — including providers not yet used (zeros).

        Reports used/limit for both requests (RPM/RPD) and tokens (TPM/TPD) plus
        remaining 429 backoff so the UI can flag live bottlenecks and cooling-down providers.
        """
        now = time.time()
        names = set(providers or []) | set(self._states.keys())
        out: dict[str, dict[str, int | float]] = {}
        for provider in sorted(names):
            limits = self._get_limits(provider)
            state = self._states.get(provider)
            if state is not None:
                cutoff = now - 60.0
                rpm_used = len([t for t in state.request_timestamps if t > cutoff])
                tpm_used = sum(c for t, c in state.token_timestamps if t > cutoff)
                is_new_day = (now - state.day_start > 86400)
                rpd_used = 0 if is_new_day else state.daily_count
                tpd_used = 0 if is_new_day else state.daily_tokens
                backoff = max(0.0, state.backoff_until - now)
            else:
                rpm_used = 0
                rpd_used = 0
                tpm_used = 0
                tpd_used = 0
                backoff = 0.0
            out[provider] = {
                "rpm_used": rpm_used,
                "rpm_limit": limits.rpm,
                "rpd_used": rpd_used,
                "rpd_limit": limits.rpd,
                "tpm_used": tpm_used,
                "tpm_limit": limits.tpm,
                "tpd_used": tpd_used,
                "tpd_limit": limits.tpd,
                "backoff_seconds": round(backoff, 1),
            }
        return out


# ---------------------------------------------------------------------------
# Process-wide shared limiter
# ---------------------------------------------------------------------------
# Rate limiting only works if every request consults the *same* limiter: RPM/RPD
# counters and 429 backoff must span requests. Constructing a fresh RateLimiter
# per request (the previous behavior) reset all quota state on every call, so
# under concurrency each request believed it was the first and the free-tier
# protection was effectively absent. A single shared instance makes the limits
# real — and lets a usage endpoint report true, live headroom.

_shared_rate_limiter: RateLimiter | None = None


def get_shared_rate_limiter() -> RateLimiter:
    """Return the process-wide :class:`RateLimiter` singleton (lazily created)."""
    global _shared_rate_limiter
    if _shared_rate_limiter is None:
        _shared_rate_limiter = RateLimiter()
    return _shared_rate_limiter

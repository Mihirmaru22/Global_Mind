"""Tests for provider fallback + rate-limit cooldown wiring.

These lock in the fix for wasted free-tier requests: after a provider returns
429 the router must mark it rate-limited so subsequent calls in the same request
skip it, instead of re-firing a doomed request at the head of the chain every
time.
"""

from __future__ import annotations

import time

import pytest

from src.core.provider_client import (
    ProviderOption,
    ProviderRouter,
    TaskRoute,
    _rate_limit_retry_after,
)
from src.core.rate_limiter import ProviderLimits, RateLimiter


class _Err429(Exception):
    """Mimics an SDK/HTTP 429 error (exposes ``status_code``)."""

    status_code = 429

    class _Resp:
        headers = {"retry-after": "7"}

    response = _Resp()


class _FakeProvider:
    """Minimal LLMProvider that goes through the shared RateLimiter like the real ones."""

    def __init__(self, name: str, rate_limiter: RateLimiter, *, raise_429: bool = False, text: str = "ok") -> None:
        self._name = name
        self._rl = rate_limiter
        self._raise_429 = raise_429
        self._text = text
        self.calls = 0

    @property
    def name(self) -> str:
        return self._name

    @property
    def is_available(self) -> bool:
        return True

    async def chat(self, messages, *, model, temperature=0.0, max_tokens=4096, response_format=None, usage=None):
        # Real providers acquire a slot first — that's where an active cooldown
        # gets enforced (acquire raises), so the fake must do the same.
        await self._rl.acquire(self._name)
        self.calls += 1
        if self._raise_429:
            raise _Err429()
        return self._text


def _make_router(rate_limiter: RateLimiter, providers: dict) -> ProviderRouter:
    router = ProviderRouter(preferred_provider="auto")  # no soft pin
    router._rate_limiter = rate_limiter
    router._providers = providers
    router._routes = {
        "general_qa": TaskRoute([ProviderOption("a", "m-a", 1), ProviderOption("b", "m-b", 2)])
    }
    return router


# ---------------------------------------------------------------------------
# _rate_limit_retry_after
# ---------------------------------------------------------------------------

def test_retry_after_detects_429_and_honours_header():
    assert _rate_limit_retry_after(_Err429()) == 7.0


def test_retry_after_ignores_non_429():
    assert _rate_limit_retry_after(RuntimeError("boom")) is None
    assert _rate_limit_retry_after(TimeoutError()) is None


def test_retry_after_caps_absurd_header():
    class _Big(Exception):
        status_code = 429

        class _Resp:
            headers = {"retry-after": "99999"}

        response = _Resp()

    assert _rate_limit_retry_after(_Big()) == 60.0  # capped


# ---------------------------------------------------------------------------
# Router cooldown behaviour
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_429_provider_is_skipped_on_next_call():
    limits = {"a": ProviderLimits(rpm=100, rpd=1000), "b": ProviderLimits(rpm=100, rpd=1000)}
    rl = RateLimiter(limits=limits)
    a = _FakeProvider("a", rl, raise_429=True)
    b = _FakeProvider("b", rl, text="from-b")
    router = _make_router(rl, {"a": a, "b": b})

    # Call 1: a 429s → router records cooldown → falls back to b.
    result1 = await router.chat("general_qa", messages=[{"role": "user", "content": "hi"}])
    assert result1 == "from-b"
    assert a.calls == 1 and b.calls == 1
    assert rl._get_state("a").backoff_until > time.time()

    # Call 2: a is in cooldown, so acquire() rejects it before any network call —
    # a must NOT be hit again; b serves directly.
    result2 = await router.chat("general_qa", messages=[{"role": "user", "content": "hi"}])
    assert result2 == "from-b"
    assert a.calls == 1  # unchanged — the doomed provider was not re-fired
    assert b.calls == 2


@pytest.mark.asyncio
async def test_all_providers_exhausted_raises_cleanly():
    limits = {"a": ProviderLimits(rpm=100, rpd=1000), "b": ProviderLimits(rpm=100, rpd=1000)}
    rl = RateLimiter(limits=limits)
    a = _FakeProvider("a", rl, raise_429=True)
    b = _FakeProvider("b", rl, raise_429=True)
    router = _make_router(rl, {"a": a, "b": b})

    with pytest.raises(RuntimeError, match="All providers exhausted"):
        await router.chat("general_qa", messages=[{"role": "user", "content": "hi"}])

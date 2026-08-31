"""Unit and integration tests for Phase 13: Task-Aware Provider Routing & Rate Limit Tuning."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest

from src.core.provider_client import (
    DEFAULT_ROUTES,
    DEFAULT_TASK_ROUTING,
    ProviderOption,
    ProviderRouter,
    TaskRoute,
    get_task_routing_rules,
)
from src.core.rate_limiter import RateLimiter
from src.utils.circuit_breaker import get_shared_circuit_breaker


@pytest.fixture(autouse=True)
def _reset_cb():
    cb = get_shared_circuit_breaker()
    cb.reset_all()
    yield
    cb.reset_all()


class _DummyProvider:
    def __init__(self, name: str, return_text: str = "ok"):
        self._name = name
        self._text = return_text
        self.calls = 0

    @property
    def name(self) -> str:
        return self._name

    @property
    def is_available(self) -> bool:
        return True

    async def chat(self, messages, *, model, temperature=0.0, max_tokens=4096, response_format=None, usage=None):
        self.calls += 1
        return self._text


def test_task_routing_configuration_parsed():
    """Test 1: Task routing configuration is properly loaded."""
    rules = get_task_routing_rules()
    assert "reasoning" in rules
    assert "repair" in rules
    assert "synthesis" in rules
    assert "micro_synthesis" in rules

    assert rules["reasoning"]["preferred"] == ["gemini", "nvidia_nim"]
    assert rules["repair"]["preferred"] == ["groq", "nvidia_nim"]
    assert rules["micro_synthesis"]["preferred"] == ["groq", "nvidia_nim"]


@pytest.mark.asyncio
async def test_reasoning_task_routes_to_preferred_gemini():
    """Test 2: Reasoning task routes to high-TPM Gemini when provider_routing_v2_enabled is True."""
    gemini_prov = _DummyProvider("gemini", "gemini response")
    groq_prov = _DummyProvider("groq", "groq response")
    nim_prov = _DummyProvider("nvidia_nim", "nim response")

    providers = {
        "gemini": gemini_prov,
        "groq": groq_prov,
        "nvidia_nim": nim_prov,
    }

    router = ProviderRouter()
    router._providers = providers

    with patch("src.utils.feature_flags.is_feature_enabled", side_effect=lambda flag: flag == "provider_routing_v2_enabled"):
        result = await router.chat(task="reasoning", messages=[{"role": "user", "content": "SELECT 1"}])

        assert result == "gemini response"
        assert gemini_prov.calls == 1
        assert groq_prov.calls == 0
        assert router.last_used.startswith("gemini/")


@pytest.mark.asyncio
async def test_repair_task_routes_to_preferred_groq():
    """Test 3: Repair task routes to ultra-fast Groq when provider_routing_v2_enabled is True."""
    gemini_prov = _DummyProvider("gemini", "gemini response")
    groq_prov = _DummyProvider("groq", "groq response")
    nim_prov = _DummyProvider("nvidia_nim", "nim response")

    providers = {
        "gemini": gemini_prov,
        "groq": groq_prov,
        "nvidia_nim": nim_prov,
    }

    router = ProviderRouter()
    router._providers = providers

    with patch("src.utils.feature_flags.is_feature_enabled", side_effect=lambda flag: flag == "provider_routing_v2_enabled"):
        result = await router.chat(task="repair", messages=[{"role": "user", "content": "Fix SQL"}])

        assert result == "groq response"
        assert groq_prov.calls == 1
        assert gemini_prov.calls == 0
        assert router.last_used.startswith("groq/")


@pytest.mark.asyncio
async def test_circuit_breaker_tripped_falls_back_gracefully():
    """Test 4: Tripping preferred provider circuit breaker falls back to next viable provider."""
    cb = get_shared_circuit_breaker()

    gemini_prov = _DummyProvider("gemini", "gemini response")
    groq_prov = _DummyProvider("groq", "groq response")
    nim_prov = _DummyProvider("nvidia_nim", "nim response")

    providers = {
        "gemini": gemini_prov,
        "groq": groq_prov,
        "nvidia_nim": nim_prov,
    }

    router = ProviderRouter()
    router._providers = providers

    # Force trip circuit breaker on Gemini
    cb.record_failure("gemini", Exception("429 rate limit"))
    cb.record_failure("gemini", Exception("429 rate limit"))
    cb.record_failure("gemini", Exception("429 rate limit"))
    assert cb.is_open("gemini")

    with patch("src.utils.feature_flags.is_feature_enabled", side_effect=lambda flag: flag == "provider_routing_v2_enabled"):
        # Reasoning task preferred is gemini -> should fall back to nvidia_nim (or groq)
        result = await router.chat(task="reasoning", messages=[{"role": "user", "content": "SELECT 1"}])

        assert gemini_prov.calls == 0
        assert (nim_prov.calls == 1 or groq_prov.calls == 1)
        assert result in ("nim response", "groq response")


@pytest.mark.asyncio
async def test_feature_flag_disabled_uses_default_chain():
    """Test 5: When provider_routing_v2_enabled is False, original default route priority is preserved."""
    gemini_prov = _DummyProvider("gemini", "gemini response")
    groq_prov = _DummyProvider("groq", "groq response")
    nim_prov = _DummyProvider("nvidia_nim", "nim response")

    providers = {
        "gemini": gemini_prov,
        "groq": groq_prov,
        "nvidia_nim": nim_prov,
    }

    # In default routes, reasoning has groq as priority 1
    router = ProviderRouter()
    router._providers = providers

    with patch("src.utils.feature_flags.is_feature_enabled", return_value=False):
        result = await router.chat(task="reasoning", messages=[{"role": "user", "content": "SELECT 1"}])

        assert result == "groq response"
        assert groq_prov.calls == 1
        assert gemini_prov.calls == 0

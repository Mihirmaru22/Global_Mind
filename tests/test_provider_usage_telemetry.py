import asyncio
import pytest
from src.core.rate_limiter import RateLimiter, ProviderLimits
from src.api.ui import get_provider_usage


def test_rate_limiter_token_tracking():
    limits = {
        "test_prov": ProviderLimits(rpm=10, rpd=100, tpm=5000, tpd=20000),
    }
    limiter = RateLimiter(limits=limits)

    # Initial snapshot
    snap1 = limiter.usage_snapshot(["test_prov"])
    assert snap1["test_prov"]["tpm_used"] == 0
    assert snap1["test_prov"]["tpd_used"] == 0
    assert snap1["test_prov"]["tpm_limit"] == 5000
    assert snap1["test_prov"]["tpd_limit"] == 20000

    # Record tokens
    limiter.record_tokens("test_prov", 1250)
    snap2 = limiter.usage_snapshot(["test_prov"])
    assert snap2["test_prov"]["tpm_used"] == 1250
    assert snap2["test_prov"]["tpd_used"] == 1250

    # Record more tokens
    limiter.record_tokens("test_prov", 2000)
    snap3 = limiter.usage_snapshot(["test_prov"])
    assert snap3["test_prov"]["tpm_used"] == 3250
    assert snap3["test_prov"]["tpd_used"] == 3250


@pytest.mark.asyncio
async def test_get_provider_usage_api():
    res = await get_provider_usage()
    assert "providers" in res
    providers = res["providers"]
    assert len(providers) > 0

    for p in providers:
        assert "id" in p
        assert "label" in p
        assert "model" in p
        assert "role" in p
        assert "rpmUsed" in p
        assert "rpmLimit" in p
        assert "rpdUsed" in p
        assert "rpdLimit" in p
        assert "tpmUsed" in p
        assert "tpmLimit" in p
        assert "tpdUsed" in p
        assert "tpdLimit" in p
        assert "backoffSeconds" in p
        assert p["tpmLimit"] > 0
        assert p["tpdLimit"] > 0

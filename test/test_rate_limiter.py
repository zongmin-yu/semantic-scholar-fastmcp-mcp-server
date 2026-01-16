import pytest

from semantic_scholar.config import RateLimitConfig
from semantic_scholar.utils.http import RateLimiter


@pytest.mark.asyncio
async def test_rate_limiter_uses_shared_bucket_for_dynamic_ids(monkeypatch):
    monkeypatch.setattr(RateLimitConfig, "DEFAULT_LIMIT", (2, 10))

    now = 0.0

    def clock():
        return now

    async def sleeper(delay: float):
        nonlocal now
        now += delay

    rl = RateLimiter(clock=clock, sleeper=sleeper)

    await rl.acquire("/paper/1", authenticated=True)
    await rl.acquire("/paper/2", authenticated=True)
    assert now == 0.0

    await rl.acquire("/paper/3", authenticated=True)
    assert now == 10.0


@pytest.mark.asyncio
async def test_rate_limiter_uses_unauthenticated_limits(monkeypatch):
    monkeypatch.setattr(RateLimitConfig, "DEFAULT_LIMIT", (100, 1))
    monkeypatch.setattr(RateLimitConfig, "UNAUTHENTICATED_LIMIT", (1, 5))

    now = 0.0

    def clock():
        return now

    async def sleeper(delay: float):
        nonlocal now
        now += delay

    rl = RateLimiter(clock=clock, sleeper=sleeper)

    await rl.acquire("/paper/search", authenticated=False)
    await rl.acquire("/paper/search", authenticated=False)
    assert now == 5.0


@pytest.mark.asyncio
async def test_rate_limiter_detects_recommendations_base_url(monkeypatch):
    monkeypatch.setattr(RateLimitConfig, "RECOMMENDATIONS_LIMIT", (1, 3))

    now = 0.0

    def clock():
        return now

    async def sleeper(delay: float):
        nonlocal now
        now += delay

    rl = RateLimiter(clock=clock, sleeper=sleeper)

    await rl.acquire(
        "/papers/forpaper/abc",
        authenticated=True,
        base_url="https://api.semanticscholar.org/recommendations/v1",
    )
    await rl.acquire(
        "/papers/forpaper/def",
        authenticated=True,
        base_url="https://api.semanticscholar.org/recommendations/v1",
    )
    assert now == 3.0


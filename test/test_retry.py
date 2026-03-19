"""Tests for exponential backoff retry on 429 responses."""

import asyncio
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from semantic_scholar.core.exceptions import S2RateLimitError
from semantic_scholar.core.transport import S2Transport


def _make_response(status_code: int, json_data=None, headers=None):
    """Build a fake httpx.Response."""
    return httpx.Response(
        status_code=status_code,
        json=json_data or {},
        headers=headers or {},
        request=httpx.Request("GET", "https://api.semanticscholar.org/graph/v1/paper/search"),
    )


@pytest.fixture
def transport():
    return S2Transport()


@pytest.fixture(autouse=True)
def _patch_rate_limiter():
    """Skip proactive rate limiting in tests."""
    with patch("semantic_scholar.core.transport.rate_limiter") as mock_rl:
        mock_rl.acquire = AsyncMock()
        yield mock_rl


@pytest.fixture(autouse=True)
def _no_api_key():
    """Ensure no API key is used."""
    with patch("semantic_scholar.core.transport.get_api_key", return_value=None):
        yield


class TestRetryOn429:
    """Retry logic for rate-limited responses."""

    @pytest.mark.asyncio
    async def test_retry_succeeds_after_one_429(self, transport):
        """429 on first attempt, 200 on second -> returns data."""
        mock_client = AsyncMock()
        mock_client.request = AsyncMock(
            side_effect=[
                _make_response(429, headers={"retry-after": "1"}),
                _make_response(200, json_data={"data": [{"title": "Test Paper"}]}),
            ]
        )

        with patch("semantic_scholar.core.transport.initialize_client", return_value=mock_client), \
             patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            result = await transport.request_json("/paper/search", params={"q": "test"})

        assert result == {"data": [{"title": "Test Paper"}]}
        assert mock_client.request.call_count == 2
        mock_sleep.assert_called_once()

    @pytest.mark.asyncio
    async def test_retry_exhausted_raises(self, transport):
        """429 on all attempts -> raises S2RateLimitError."""
        mock_client = AsyncMock()
        mock_client.request = AsyncMock(
            side_effect=[_make_response(429) for _ in range(6)]
        )

        with patch("semantic_scholar.core.transport.initialize_client", return_value=mock_client), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(S2RateLimitError) as exc_info:
                await transport.request_json("/paper/search", params={"q": "test"})

        assert exc_info.value.status_code == 429
        assert mock_client.request.call_count == 6  # 1 initial + 5 retries

    @pytest.mark.asyncio
    async def test_retry_respects_retry_after_header(self, transport):
        """Uses retry-after header value when present."""
        mock_client = AsyncMock()
        mock_client.request = AsyncMock(
            side_effect=[
                _make_response(429, headers={"retry-after": "5"}),
                _make_response(200, json_data={"data": []}),
            ]
        )

        with patch("semantic_scholar.core.transport.initialize_client", return_value=mock_client), \
             patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await transport.request_json("/paper/search", params={"q": "test"})

        # Should sleep for 5 seconds as specified by retry-after
        mock_sleep.assert_called_once_with(5.0)

    @pytest.mark.asyncio
    async def test_retry_uses_exponential_backoff_without_header(self, transport):
        """Without retry-after, uses exponential backoff with jitter."""
        mock_client = AsyncMock()
        mock_client.request = AsyncMock(
            side_effect=[
                _make_response(429),
                _make_response(429),
                _make_response(200, json_data={"data": []}),
            ]
        )

        with patch("semantic_scholar.core.transport.initialize_client", return_value=mock_client), \
             patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep, \
             patch("random.uniform", return_value=0.5):
            await transport.request_json("/paper/search", params={"q": "test"})

        assert mock_sleep.call_count == 2
        # attempt 0: 1 * 2^0 + 0.5 = 1.5
        assert mock_sleep.call_args_list[0].args[0] == pytest.approx(1.5)
        # attempt 1: 1 * 2^1 + 0.5 = 2.5
        assert mock_sleep.call_args_list[1].args[0] == pytest.approx(2.5)

    @pytest.mark.asyncio
    async def test_non_429_error_not_retried(self, transport):
        """Other HTTP errors (e.g. 500) are raised immediately, not retried."""
        mock_client = AsyncMock()
        mock_client.request = AsyncMock(
            return_value=_make_response(500),
        )

        with patch("semantic_scholar.core.transport.initialize_client", return_value=mock_client), \
             patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            with pytest.raises(Exception) as exc_info:
                await transport.request_json("/paper/search", params={"q": "test"})

        assert mock_client.request.call_count == 1
        mock_sleep.assert_not_called()

    @pytest.mark.asyncio
    async def test_retry_succeeds_on_third_attempt(self, transport):
        """429 twice, then 200 on third attempt."""
        mock_client = AsyncMock()
        mock_client.request = AsyncMock(
            side_effect=[
                _make_response(429),
                _make_response(429),
                _make_response(200, json_data={"total": 42}),
            ]
        )

        with patch("semantic_scholar.core.transport.initialize_client", return_value=mock_client), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            result = await transport.request_json("/paper/search", params={"q": "test"})

        assert result == {"total": 42}
        assert mock_client.request.call_count == 3


class TestUnauthenticatedRetry:
    """Simulate unauthenticated users (no API key) hitting rate limits — the core use case for issue #10."""

    @pytest.mark.asyncio
    async def test_unauthenticated_user_gets_result_after_retry(self, transport):
        """User without API key gets 429, server retries, eventually succeeds."""
        mock_client = AsyncMock()
        mock_client.request = AsyncMock(
            side_effect=[
                _make_response(429, headers={"retry-after": "2"}),
                _make_response(429),
                _make_response(200, json_data={"data": [{"title": "Attention Is All You Need"}]}),
            ]
        )

        with patch("semantic_scholar.core.transport.initialize_client", return_value=mock_client), \
             patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            result = await transport.request_json("/paper/search", params={"q": "attention"})

        assert result == {"data": [{"title": "Attention Is All You Need"}]}
        assert mock_client.request.call_count == 3
        assert mock_sleep.call_count == 2
        # First retry uses retry-after header
        assert mock_sleep.call_args_list[0].args[0] == 2.0

    @pytest.mark.asyncio
    async def test_unauthenticated_error_reports_no_api_key(self, transport):
        """When retries exhausted, error indicates user is unauthenticated."""
        mock_client = AsyncMock()
        mock_client.request = AsyncMock(
            side_effect=[_make_response(429) for _ in range(6)]
        )

        with patch("semantic_scholar.core.transport.initialize_client", return_value=mock_client), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(S2RateLimitError) as exc_info:
                await transport.request_json("/paper/search", params={"q": "test"})

        assert exc_info.value.authenticated is False
        assert "API key" in exc_info.value.message


class TestBackoffDelay:
    """Unit tests for _backoff_delay calculation."""

    def test_uses_retry_after_when_present(self):
        assert S2Transport._backoff_delay(0, retry_after="3") == 3.0

    def test_uses_retry_after_float(self):
        assert S2Transport._backoff_delay(0, retry_after="1.5") == 1.5

    def test_ignores_invalid_retry_after(self):
        with patch("random.uniform", return_value=0.5):
            delay = S2Transport._backoff_delay(0, retry_after="invalid")
        assert delay == pytest.approx(1.5)  # 1 * 2^0 + 0.5

    def test_exponential_growth(self):
        with patch("random.uniform", return_value=0.0):
            assert S2Transport._backoff_delay(0) == pytest.approx(1.0)
            assert S2Transport._backoff_delay(1) == pytest.approx(2.0)
            assert S2Transport._backoff_delay(2) == pytest.approx(4.0)
            assert S2Transport._backoff_delay(3) == pytest.approx(8.0)
            assert S2Transport._backoff_delay(4) == pytest.approx(16.0)

    def test_backoff_capped_at_max(self):
        """Delay should never exceed MAX_BACKOFF + jitter."""
        with patch("random.uniform", return_value=0.0):
            # attempt 5 would be 32s without cap, should be capped to 30s
            assert S2Transport._backoff_delay(5) == pytest.approx(30.0)
            assert S2Transport._backoff_delay(10) == pytest.approx(30.0)

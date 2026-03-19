from __future__ import annotations

import asyncio
import os
import random
import time
from collections import deque
from typing import Any, Awaitable, Callable, Deque, Dict, Optional, Tuple

import httpx

from ..config import Config, ErrorType, RateLimitConfig
from ..utils.logger import logger
from .exceptions import (
    S2ApiError,
    S2Error,
    S2NotFoundError,
    S2RateLimitError,
    S2TimeoutError,
    S2ValidationError,
)

# Global HTTP client for connection pooling
http_client: Optional[httpx.AsyncClient] = None


class RateLimiter:
    """
    Rate limiter for API requests to prevent exceeding API limits.
    """

    def __init__(
        self,
        *,
        clock: Optional[Callable[[], float]] = None,
        sleeper: Optional[Callable[[float], Awaitable[Any]]] = None,
    ):
        self._clock = clock or time.monotonic
        self._sleep = sleeper or asyncio.sleep
        self._events: Dict[str, Deque[float]] = {}
        self._locks: Dict[str, asyncio.Lock] = {}

    def _bucket_key(self, endpoint: str, base_url: Optional[str] = None) -> str:
        """
        Map a concrete request path to a stable rate-limiting bucket.

        Many endpoints include IDs (e.g. /paper/{id}) which would otherwise
        defeat throttling if used as-is.
        """
        if base_url and "recommendations" in base_url:
            return "/recommendations"
        if "recommendations" in endpoint:
            return "/recommendations"
        if "/author/search" in endpoint:
            return "/author/search"
        if "/paper/search" in endpoint:
            return "/paper/search"
        if "/paper/batch" in endpoint:
            return "/paper/batch"
        if "/author/batch" in endpoint:
            return "/author/batch"
        return "/default"

    def _get_rate_limit(self, endpoint: str, *, authenticated: bool) -> Tuple[int, int]:
        """Get the appropriate rate limit for an endpoint."""
        if not authenticated:
            return RateLimitConfig.UNAUTHENTICATED_LIMIT
        if any(restricted in endpoint for restricted in RateLimitConfig.RESTRICTED_ENDPOINTS):
            if "batch" in endpoint:
                return RateLimitConfig.BATCH_LIMIT
            if "search" in endpoint:
                return RateLimitConfig.SEARCH_LIMIT
            if "recommendations" in endpoint:
                return RateLimitConfig.RECOMMENDATIONS_LIMIT
            return RateLimitConfig.SEARCH_LIMIT
        return RateLimitConfig.DEFAULT_LIMIT

    async def acquire(
        self,
        endpoint: str,
        *,
        authenticated: bool = True,
        base_url: Optional[str] = None,
    ) -> None:
        """
        Acquire permission to make a request, waiting if necessary to respect rate limits.

        Args:
            endpoint: The API endpoint being accessed.
        """
        bucket = self._bucket_key(endpoint, base_url)
        if bucket not in self._locks:
            self._locks[bucket] = asyncio.Lock()
            self._events[bucket] = deque()

        async with self._locks[bucket]:
            limit_endpoint = bucket if bucket != "/default" else endpoint
            requests, seconds = self._get_rate_limit(limit_endpoint, authenticated=authenticated)
            if requests <= 0 or seconds <= 0:
                return

            events = self._events[bucket]
            while True:
                now = self._clock()
                cutoff = now - float(seconds)
                while events and events[0] <= cutoff:
                    events.popleft()

                if len(events) < int(requests):
                    events.append(now)
                    return

                delay = (events[0] + float(seconds)) - now
                if delay > 0:
                    await self._sleep(delay)


rate_limiter = RateLimiter()


def get_api_key() -> Optional[str]:
    """
    Get the Semantic Scholar API key from environment variables.
    Returns None if no API key is set, enabling unauthenticated access.
    """
    api_key = os.getenv("SEMANTIC_SCHOLAR_API_KEY")
    if api_key:
        norm = api_key.strip().lower()
        if norm in ("", "none", "null", "false"):
            logger.warning(
                "SEMANTIC_SCHOLAR_API_KEY is set to a placeholder value; treating as not set."
            )
            return None
        return api_key

    logger.warning("No SEMANTIC_SCHOLAR_API_KEY set. Using unauthenticated access with lower rate limits.")
    return None


async def initialize_client() -> httpx.AsyncClient:
    """Initialize the global HTTP client."""
    global http_client
    if http_client is None:
        http_client = httpx.AsyncClient(
            timeout=Config.TIMEOUT,
            limits=httpx.Limits(max_keepalive_connections=10),
        )
    return http_client


async def cleanup_client() -> None:
    """Clean up the global HTTP client."""
    global http_client
    if http_client is not None:
        await http_client.aclose()
        http_client = None


def _redact_headers(headers: Dict[str, str]) -> Dict[str, str]:
    redacted = dict(headers or {})
    for key in ("x-api-key", "authorization", "proxy-authorization"):
        if key in redacted and redacted[key]:
            redacted[key] = "***"
    return redacted


def _normalize_key(key: Optional[str]) -> Optional[str]:
    if not key:
        return None
    normalized = str(key).strip()
    if normalized.lower() in ("", "none", "null", "false"):
        return None
    return normalized


def error_dict_to_exception(
    result: dict[str, Any],
    *,
    endpoint: Optional[str] = None,
    method: Optional[str] = None,
    params: Optional[dict[str, Any]] = None,
    json_body: Any = None,
    base_url: Optional[str] = None,
) -> S2Error:
    error = result.get("error", {})
    error_type = error.get("type")
    message = error.get("message", "Unknown error")
    details = error.get("details")
    if not isinstance(details, dict):
        details = {}

    if error_type == ErrorType.VALIDATION.value:
        return S2ValidationError(message=message, details=details)

    if error_type == ErrorType.RATE_LIMIT.value:
        return S2RateLimitError(
            message=message,
            details=details,
            status_code=429,
            endpoint=endpoint,
            method=method,
            params=params,
            json_body=json_body,
            base_url=base_url,
            response_text=details.get("response"),
            retry_after=details.get("retry_after"),
            authenticated=bool(details.get("authenticated", False)),
        )

    if error_type == ErrorType.TIMEOUT.value:
        return S2TimeoutError(
            message=message,
            details=details,
            endpoint=endpoint,
            method=method,
            timeout_seconds=Config.TIMEOUT,
        )

    status_code = details.get("status_code")
    exc_cls = S2NotFoundError if status_code == 404 else S2ApiError
    return exc_cls(
        message=message,
        details=details,
        status_code=status_code,
        endpoint=endpoint,
        method=method,
        params=params,
        json_body=json_body,
        base_url=base_url,
        response_text=details.get("response"),
    )


class S2Transport:
    MAX_RETRIES = 3
    BASE_BACKOFF = 1.0  # seconds

    async def request_json(
        self,
        endpoint: str,
        *,
        params: Optional[dict[str, Any]] = None,
        api_key_override: Optional[str] = None,
        method: str = "GET",
        json: Any = None,
        base_url: Optional[str] = None,
    ) -> Any:
        api_key = _normalize_key(api_key_override) or _normalize_key(get_api_key())
        authenticated = bool(api_key)

        await rate_limiter.acquire(endpoint, authenticated=authenticated, base_url=base_url)

        if api_key:
            headers = {"x-api-key": api_key}
        else:
            headers = {}
            logger.debug("Not sending x-api-key header (no valid API key available)")

        headers.setdefault(
            "User-Agent",
            "semantic-scholar-mcp/1.0 (+https://github.com/zongmin-yu/semantic-scholar-fastmcp-mcp-server)",
        )

        if endpoint.startswith("http://") or endpoint.startswith("https://"):
            url = endpoint
        else:
            url = f"{base_url or Config.BASE_URL}{endpoint}"

        last_rate_limit_exc: Optional[S2RateLimitError] = None

        for attempt in range(self.MAX_RETRIES + 1):
            try:
                client = await initialize_client()
                logger.debug(
                    "Semantic Scholar request: method=%s url=%s params=%s headers=%s",
                    method,
                    url,
                    params,
                    _redact_headers(headers),
                )
                response = await client.request(method.upper(), url, params=params, headers=headers, json=json)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as exc:
                try:
                    logger.error("HTTP error %s for %s: %s", exc.response.status_code, url, exc.response.text)
                    logger.error("Request headers: %s", _redact_headers(headers))
                    logger.error("Request params: %s", params)
                except Exception:
                    logger.exception("Failed to log request details")

                status_code = exc.response.status_code
                response_text = exc.response.text

                if status_code == 429:
                    retry_after = exc.response.headers.get("retry-after")
                    last_rate_limit_exc = S2RateLimitError(
                        message="Rate limit exceeded. Consider using an API key for higher limits.",
                        details={},
                        status_code=429,
                        endpoint=endpoint,
                        method=method,
                        params=params,
                        json_body=json,
                        base_url=base_url,
                        response_text=response_text,
                        retry_after=retry_after,
                        authenticated=authenticated,
                    )
                    last_rate_limit_exc.__cause__ = exc

                    if attempt < self.MAX_RETRIES:
                        delay = self._backoff_delay(attempt, retry_after)
                        logger.warning(
                            "Rate limited (429) on %s, retrying in %.1fs (attempt %d/%d)",
                            endpoint, delay, attempt + 1, self.MAX_RETRIES,
                        )
                        await asyncio.sleep(delay)
                        continue

                    raise last_rate_limit_exc from exc

                error_cls = S2NotFoundError if status_code == 404 else S2ApiError
                raise error_cls(
                    message=f"HTTP error: {status_code}",
                    details={},
                    status_code=status_code,
                    endpoint=endpoint,
                    method=method,
                    params=params,
                    json_body=json,
                    base_url=base_url,
                    response_text=response_text,
                ) from exc
            except httpx.TimeoutException as exc:
                logger.error("Request timeout for %s: %s", endpoint, str(exc))
                raise S2TimeoutError(
                    message=f"Request timed out after {Config.TIMEOUT} seconds",
                    details={},
                    endpoint=endpoint,
                    method=method,
                    timeout_seconds=Config.TIMEOUT,
                ) from exc
            except S2RateLimitError:
                raise
            except Exception as exc:
                logger.error("Unexpected error for %s: %s", endpoint, str(exc))
                raise S2ApiError(
                    message=str(exc),
                    details={},
                    endpoint=endpoint,
                    method=method,
                    params=params,
                    json_body=json,
                    base_url=base_url,
                ) from exc

        # Should not reach here, but just in case
        assert last_rate_limit_exc is not None
        raise last_rate_limit_exc

    @staticmethod
    def _backoff_delay(attempt: int, retry_after: Optional[str] = None) -> float:
        """Calculate delay with exponential backoff + jitter, respecting retry-after header."""
        if retry_after:
            try:
                return max(float(retry_after), 0.1)
            except (ValueError, TypeError):
                pass
        # Exponential backoff: 1s, 2s, 4s + jitter up to 1s
        return (S2Transport.BASE_BACKOFF * (2 ** attempt)) + random.uniform(0, 1.0)


class MakeRequestCompatTransport:
    def __init__(self, make_request_callable) -> None:
        self._make_request = make_request_callable

    async def request_json(
        self,
        endpoint: str,
        *,
        params: Optional[dict[str, Any]] = None,
        api_key_override: Optional[str] = None,
        method: str = "GET",
        json: Any = None,
        base_url: Optional[str] = None,
    ) -> Any:
        result = await self._make_request(
            endpoint,
            params=params,
            api_key_override=api_key_override,
            method=method,
            json=json,
            base_url=base_url,
        )
        if isinstance(result, dict) and "error" in result:
            raise error_dict_to_exception(
                result,
                endpoint=endpoint,
                method=method,
                params=params,
                json_body=json,
                base_url=base_url,
            )
        return result


default_transport = S2Transport()

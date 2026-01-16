"""
HTTP client utilities for the Semantic Scholar API Server.
"""

import os
import httpx
import asyncio
import time
from collections import deque
from typing import Awaitable, Callable, Deque, Dict, Optional, Tuple, Any

from ..config import Config, ErrorType, RateLimitConfig
from .errors import create_error_response
from .logger import logger

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

    async def acquire(self, endpoint: str, *, authenticated: bool = True, base_url: Optional[str] = None):
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

# Create global rate limiter instance
rate_limiter = RateLimiter()

def get_api_key() -> Optional[str]:
    """
    Get the Semantic Scholar API key from environment variables.
    Returns None if no API key is set, enabling unauthenticated access.
    """
    api_key = os.getenv("SEMANTIC_SCHOLAR_API_KEY")
    # Treat common placeholder values as no key (e.g., 'none', 'null')
    if api_key:
        norm = api_key.strip().lower()
        if norm in ("", "none", "null", "false"):
            logger.warning("SEMANTIC_SCHOLAR_API_KEY is set to a placeholder value; treating as not set.")
            return None
        return api_key

    logger.warning("No SEMANTIC_SCHOLAR_API_KEY set. Using unauthenticated access with lower rate limits.")
    return None

async def initialize_client():
    """Initialize the global HTTP client."""
    global http_client
    if http_client is None:
        http_client = httpx.AsyncClient(
            timeout=Config.TIMEOUT,
            limits=httpx.Limits(max_keepalive_connections=10)
        )
    return http_client

async def cleanup_client():
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


async def make_request(
    endpoint: str,
    params: Optional[Dict[str, Any]] = None,
    api_key_override: Optional[str] = None,
    method: str = "GET",
    json: Any = None,
    base_url: Optional[str] = None,
) -> Any:
    """
    Make a rate-limited request to the Semantic Scholar API.
    
    Args:
        endpoint: The API endpoint to call (e.g. "/paper/search") or an absolute URL.
        params: Optional query parameters.
        api_key_override: Optional API key, typically extracted from an incoming bearer token.
        method: HTTP method to use ("GET", "POST", ...).
        json: Optional JSON body for POST/PUT.
        base_url: Override base URL (e.g. recommendations API).
        
    Returns:
        The JSON response or an error response dictionary.
    """
    try:
        def _normalize_key(k: Optional[str]) -> Optional[str]:
            if not k:
                return None
            nk = str(k).strip()
            if nk.lower() in ("", "none", "null", "false"):
                return None
            return nk

        api_key = _normalize_key(api_key_override) or _normalize_key(get_api_key())
        authenticated = bool(api_key)

        # Apply rate limiting (after we know whether we are authenticated)
        await rate_limiter.acquire(endpoint, authenticated=authenticated, base_url=base_url)

        if api_key:
            headers = {"x-api-key": api_key}
        else:
            headers = {}
            logger.debug("Not sending x-api-key header (no valid API key available)")
        # Add a sensible User-Agent to avoid being blocked by some servers
        headers.setdefault("User-Agent", "semantic-scholar-mcp/1.0 (+https://github.com)")
        if endpoint.startswith("http://") or endpoint.startswith("https://"):
            url = endpoint
        else:
            url = f"{base_url or Config.BASE_URL}{endpoint}"

        # Use global client
        client = await initialize_client()
        logger.debug(
            "Semantic Scholar request: method=%s url=%s params=%s headers=%s",
            method,
            url,
            params,
            _redact_headers(headers)
        )
        response = await client.request(method.upper(), url, params=params, headers=headers, json=json)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as e:
        # Log request details to help debug 403/forbidden responses
        try:
            logger.error(f"HTTP error {e.response.status_code} for {url}: {e.response.text}")
            logger.error(f"Request headers: {_redact_headers(headers)}")
            logger.error(f"Request params: {params}")
        except Exception:
            logger.exception("Failed to log request details")
        if e.response.status_code == 429:
            return create_error_response(
                ErrorType.RATE_LIMIT,
                "Rate limit exceeded. Consider using an API key for higher limits.",
                {
                    "status_code": e.response.status_code,
                    "retry_after": e.response.headers.get("retry-after"),
                    "authenticated": authenticated,
                }
            )
        return create_error_response(
            ErrorType.API_ERROR,
            f"HTTP error: {e.response.status_code}",
            {"status_code": e.response.status_code, "response": e.response.text}
        )
    except httpx.TimeoutException as e:
        logger.error(f"Request timeout for {endpoint}: {str(e)}")
        return create_error_response(
            ErrorType.TIMEOUT,
            f"Request timed out after {Config.TIMEOUT} seconds"
        )
    except Exception as e:
        logger.error(f"Unexpected error for {endpoint}: {str(e)}")
        return create_error_response(
            ErrorType.API_ERROR,
            str(e)
        ) 

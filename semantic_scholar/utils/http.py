"""
HTTP client compatibility helpers for the Semantic Scholar API Server.
"""

from typing import Any, Dict, Optional

from ..core.exceptions import S2Error
from ..core.transport import (
    RateLimiter,
    cleanup_client,
    default_transport,
    get_api_key,
    initialize_client,
    rate_limiter,
)
from .errors import s2_exception_to_error_response


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

    Returns:
        The JSON response or an error response dictionary.
    """
    try:
        return await default_transport.request_json(
            endpoint,
            params=params,
            api_key_override=api_key_override,
            method=method,
            json=json,
            base_url=base_url,
        )
    except S2Error as exc:
        return s2_exception_to_error_response(exc)

"""Shared core transport primitives for Semantic Scholar clients."""

from .exceptions import (
    S2ApiError,
    S2Error,
    S2NotFoundError,
    S2RateLimitError,
    S2TimeoutError,
    S2ValidationError,
)
from .transport import (
    MakeRequestCompatTransport,
    RateLimiter,
    S2Transport,
    cleanup_client,
    default_transport,
    error_dict_to_exception,
    get_api_key,
    initialize_client,
    rate_limiter,
)

__all__ = [
    "MakeRequestCompatTransport",
    "RateLimiter",
    "S2ApiError",
    "S2Error",
    "S2NotFoundError",
    "S2RateLimitError",
    "S2TimeoutError",
    "S2Transport",
    "S2ValidationError",
    "cleanup_client",
    "default_transport",
    "error_dict_to_exception",
    "get_api_key",
    "initialize_client",
    "rate_limiter",
]

"""
Error handling utilities for the Semantic Scholar API Server.
"""

from typing import Any, Dict, Optional

from ..core.exceptions import S2ApiError, S2Error, S2RateLimitError, S2TimeoutError, S2ValidationError
from ..config import ErrorType


def create_error_response(
    error_type: ErrorType,
    message: str,
    details: Optional[Dict] = None
) -> Dict:
    """
    Create a standardized error response.

    Args:
        error_type: The type of error that occurred.
        message: A human-readable message describing the error.
        details: Optional additional details about the error.

    Returns:
        A dictionary with the error information.
    """
    return {
        "error": {
            "type": error_type.value,
            "message": message,
            "details": details or {}
        }
    }


def s2_exception_to_error_response(exc: S2Error) -> dict[str, Any]:
    if isinstance(exc, S2ValidationError):
        return create_error_response(ErrorType.VALIDATION, exc.message, exc.details)
    if isinstance(exc, S2RateLimitError):
        return create_error_response(
            ErrorType.RATE_LIMIT,
            exc.message,
            {
                "status_code": 429,
                "retry_after": exc.retry_after,
                "authenticated": exc.authenticated,
            },
        )
    if isinstance(exc, S2TimeoutError):
        return create_error_response(ErrorType.TIMEOUT, exc.message, {})
    if isinstance(exc, S2ApiError):
        details = {}
        if exc.status_code is not None:
            details["status_code"] = exc.status_code
        if exc.response_text is not None:
            details["response"] = exc.response_text
        return create_error_response(ErrorType.API_ERROR, exc.message, details)
    return create_error_response(ErrorType.API_ERROR, str(exc), {})

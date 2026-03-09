from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass(eq=False)
class S2Error(Exception):
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return self.message


@dataclass(eq=False)
class S2ApiError(S2Error):
    status_code: Optional[int] = None
    endpoint: Optional[str] = None
    method: Optional[str] = None
    params: Optional[dict[str, Any]] = None
    json_body: Any = None
    base_url: Optional[str] = None
    response_text: Optional[str] = None


@dataclass(eq=False)
class S2NotFoundError(S2ApiError):
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None


@dataclass(eq=False)
class S2RateLimitError(S2ApiError):
    retry_after: Optional[str] = None
    authenticated: bool = False


@dataclass(eq=False)
class S2TimeoutError(S2Error):
    endpoint: Optional[str] = None
    method: Optional[str] = None
    timeout_seconds: int = 30


@dataclass(eq=False)
class S2ValidationError(S2Error):
    field: Optional[str] = None

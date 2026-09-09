"""Rate limiting middleware using slowapi.

Applies configurable per-endpoint rate limits to prevent resource exhaustion,
with stricter limits on LLM-bound and embedding-bound endpoints.
"""

from __future__ import annotations

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.config import settings

logger = structlog.get_logger(__name__)


def _get_client_ip(request: Request) -> str:
    """Extract client IP for rate limit keying.

    Uses X-Forwarded-For if available (behind a reverse proxy),
    otherwise falls back to the direct client address.
    """
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        # First IP in the chain is the original client
        return forwarded.split(",")[0].strip()
    return get_remote_address(request)


# Module-level limiter instance — imported by route modules for per-route decorators.
limiter = Limiter(
    key_func=_get_client_ip,
    default_limits=[settings.rate_limit_default],
    storage_uri="memory://",
)


def _rate_limit_error_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """Return a structured JSON error response when a rate limit is exceeded.

    Follows the application's standard error response format and includes
    a Retry-After header so clients know when to retry.
    """
    logger.warning(
        "rate_limit_exceeded",
        path=str(request.url.path),
        client=_get_client_ip(request),
        detail=str(exc.detail),
    )
    retry_after = getattr(exc, "retry_after", None)
    headers: dict[str, str] = {}
    if retry_after is not None:
        headers["Retry-After"] = str(retry_after)

    return JSONResponse(
        status_code=429,
        content={
            "error": {
                "code": "RATE_LIMIT_EXCEEDED",
                "message": f"Rate limit exceeded: {exc.detail}",
            }
        },
        headers=headers,
    )


def setup_rate_limiting(app: FastAPI) -> None:
    """Register the slowapi limiter and its error handler on the FastAPI app."""
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_error_handler)

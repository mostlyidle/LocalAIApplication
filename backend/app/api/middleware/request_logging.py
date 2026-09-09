"""Structured request/response logging middleware using structlog."""

from __future__ import annotations

import time
from typing import Callable

import structlog
from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

logger = structlog.get_logger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log every HTTP request with method, path, status, and duration."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start = time.perf_counter()
        response: Response | None = None
        try:
            response = await call_next(request)
            return response
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            status = response.status_code if response else 500
            log = logger.info if status < 400 else logger.warning
            if status >= 500:
                log = logger.error
            log(
                "http_request",
                method=request.method,
                path=str(request.url.path),
                query=str(request.url.query) or None,
                status=status,
                duration_ms=round(duration_ms, 2),
                client=request.client.host if request.client else None,
            )


def setup_request_logging(app: FastAPI) -> None:
    """Add request logging middleware to the FastAPI application."""
    app.add_middleware(RequestLoggingMiddleware)

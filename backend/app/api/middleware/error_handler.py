"""Application error hierarchy and FastAPI exception handlers."""

from __future__ import annotations

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logger = structlog.get_logger(__name__)


# =============================================================================
# Exception hierarchy
# =============================================================================


class AppError(Exception):
    """Base application error. All domain errors inherit from this."""

    def __init__(
        self,
        message: str,
        code: str,
        status_code: int = 500,
        details: dict | None = None,
    ) -> None:
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details
        super().__init__(message)


# ── Document errors ─────────────────────────────────────────────────────


class DocumentParseError(AppError):
    def __init__(self, message: str, details: dict | None = None) -> None:
        super().__init__(
            message=message,
            code="DOCUMENT_PARSE_ERROR",
            status_code=422,
            details=details,
        )


class DocumentTooLargeError(AppError):
    def __init__(self, max_size: int) -> None:
        super().__init__(
            message=f"File exceeds maximum upload size of {max_size // (1024 * 1024)}MB.",
            code="DOCUMENT_TOO_LARGE",
            status_code=413,
        )


class UnsupportedFormatError(AppError):
    def __init__(self, extension: str) -> None:
        super().__init__(
            message=f"File format '{extension}' is not supported.",
            code="UNSUPPORTED_FORMAT",
            status_code=415,
        )


# ── SQL errors ──────────────────────────────────────────────────────────


class UnsafeQueryError(AppError):
    def __init__(self, message: str) -> None:
        super().__init__(
            message=message,
            code="UNSAFE_QUERY",
            status_code=400,
        )


class SQLExecutionError(AppError):
    def __init__(self, message: str) -> None:
        super().__init__(
            message=message,
            code="SQL_EXECUTION_ERROR",
            status_code=422,
        )


class DatabaseConnectionError(AppError):
    def __init__(self, message: str = "Failed to connect to the database.") -> None:
        super().__init__(
            message=message,
            code="DATABASE_CONNECTION_ERROR",
            status_code=503,
        )


# ── LLM errors ─────────────────────────────────────────────────────────


class LLMConnectionError(AppError):
    def __init__(self, message: str = "Failed to connect to Ollama.") -> None:
        super().__init__(
            message=message,
            code="LLM_CONNECTION_ERROR",
            status_code=503,
        )


class LLMTimeoutError(AppError):
    def __init__(self) -> None:
        super().__init__(
            message="LLM request timed out. Try a shorter prompt or a smaller model.",
            code="LLM_TIMEOUT",
            status_code=504,
        )


# ── RAG errors ──────────────────────────────────────────────────────────


class CollectionNotFoundError(AppError):
    def __init__(self, name: str) -> None:
        super().__init__(
            message=f"Vector store collection '{name}' not found.",
            code="COLLECTION_NOT_FOUND",
            status_code=404,
        )


# ── Generic errors ──────────────────────────────────────────────────────


class NotFoundError(AppError):
    def __init__(self, resource: str, resource_id: str) -> None:
        super().__init__(
            message=f"{resource} with id '{resource_id}' not found.",
            code="NOT_FOUND",
            status_code=404,
        )


class InputValidationError(AppError):
    """Application-level validation error (distinct from Pydantic's ValidationError)."""

    def __init__(self, message: str) -> None:
        super().__init__(
            message=message,
            code="VALIDATION_ERROR",
            status_code=422,
        )


# ── Meeting errors ───────────────────────────────────────────────────────


class ConsentRequiredError(AppError):
    """Raised when a meeting or audio protocol is used without consent."""

    def __init__(self) -> None:
        super().__init__(
            message="Explicit consent is required before starting a meeting or sending audio.",
            code="CONSENT_REQUIRED",
            status_code=403,
        )


class MeetingProtocolError(AppError):
    """Raised when a meeting audio protocol command is invalid."""

    def __init__(self, message: str, code: str = "MEETING_PROTOCOL_ERROR") -> None:
        super().__init__(message=message, code=code, status_code=400)


# =============================================================================
# FastAPI exception handlers
# =============================================================================


def register_exception_handlers(app: FastAPI) -> None:
    """Register all custom exception handlers on the FastAPI application."""

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        logger.error(
            "app_error",
            code=exc.code,
            message=exc.message,
            status_code=exc.status_code,
            path=str(request.url),
        )
        body: dict = {"error": {"code": exc.code, "message": exc.message}}
        if exc.details:
            body["error"]["details"] = exc.details
        return JSONResponse(status_code=exc.status_code, content=body)

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception(
            "unhandled_error",
            path=str(request.url),
            error=str(exc),
        )
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "An unexpected error occurred. Please try again.",
                }
            },
        )

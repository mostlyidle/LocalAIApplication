"""FastAPI dependency injection providers.

Uses lazy imports to avoid eager singleton construction at import time,
which would fail if data directories or external services are not yet
available (the lifespan handler creates directories first).
"""

from __future__ import annotations

from collections.abc import AsyncGenerator  # noqa: TC003

from fastapi import Depends, HTTPException, Request, WebSocket, WebSocketException
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: TC002

from app.services.auth import (
    SESSION_COOKIE,
    AuthenticatedSession,
    resolve_session,
    verify_csrf,
)
from app.services.database import get_app_session
from app.services.meetings import MeetingService, meeting_service

WEBSOCKET_SESSION_RECHECK_SECONDS = 60


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Provide an async database session for the application DB."""
    async for session in get_app_session():
        yield session


async def get_authenticated_session(
    request: Request,
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> AuthenticatedSession:
    """Resolve the session cookie and enforce CSRF on state-changing requests."""
    authenticated = await resolve_session(db, request.cookies.get(SESSION_COOKIE))
    if authenticated is None:
        raise HTTPException(status_code=401, detail="Authentication required.")
    if request.method not in {"GET", "HEAD", "OPTIONS"} and not verify_csrf(
        authenticated.session, request.headers.get("x-csrf-token")
    ):
        raise HTTPException(status_code=403, detail="Valid CSRF token required.")
    return authenticated


async def get_websocket_session(
    websocket: WebSocket,
) -> AuthenticatedSession:
    """Authenticate WebSockets and reject browser origins outside app CORS policy."""
    from app.config import settings

    origin = websocket.headers.get("origin")
    allowed_origins = {
        value.rstrip("/") for value in (*settings.cors_origins, *settings.meeting_allowed_origins)
    }
    allowed_origins.update(
        {"tauri://localhost", "http://tauri.localhost", "https://tauri.localhost"}
    )
    if origin is None or origin.rstrip("/") not in allowed_origins:
        raise WebSocketException(code=4403, reason="WebSocket origin is not allowed.")
    from app.services.database import get_app_session_factory

    factory = get_app_session_factory()
    async with factory() as db:
        authenticated = await resolve_session(db, websocket.cookies.get(SESSION_COOKIE))
    if authenticated is None:
        raise WebSocketException(code=4401, reason="Authentication required.")
    return authenticated


async def websocket_session_is_active(websocket: WebSocket, session_id: str) -> bool:
    """Recheck a long-lived WebSocket's session using a short-lived DB session."""
    from app.services.database import get_app_session_factory

    factory = get_app_session_factory()
    async with factory() as db:
        authenticated = await resolve_session(db, websocket.cookies.get(SESSION_COOKIE))
    return authenticated is not None and authenticated.session.id == session_id


def get_llm() -> LLMService:
    """Provide the LLM service singleton."""
    from app.services.llm import llm_service

    return llm_service


def get_embeddings() -> EmbeddingService:
    """Provide the embedding service singleton."""
    from app.services.embeddings import embedding_service

    return embedding_service


def get_vector_store() -> VectorStoreService:
    """Provide the vector store service singleton."""
    from app.services.hybrid_vector_store import hybrid_vector_store_service

    return hybrid_vector_store_service


def get_document_parser() -> DocumentParserService:
    """Provide the document parser service singleton."""
    from app.services.document_parser import document_parser_service

    return document_parser_service


def get_ocr() -> OCRService:
    """Provide the OCR service singleton."""
    from app.services.ocr import ocr_service

    return ocr_service


def get_meeting_service() -> MeetingService:
    """Provide the consent-aware meeting service."""
    return meeting_service


# Re-export types for use in Depends() annotations
from app.services.document_parser import DocumentParserService  # noqa: E402
from app.services.embeddings import EmbeddingService  # noqa: E402
from app.services.llm import LLMService  # noqa: E402
from app.services.ocr import OCRService  # noqa: E402
from app.services.vector_store import VectorStoreService  # noqa: E402

__all__ = [
    "get_db",
    "get_document_parser",
    "get_embeddings",
    "get_llm",
    "get_ocr",
    "get_meeting_service",
    "get_vector_store",
    "DocumentParserService",
    "EmbeddingService",
    "LLMService",
    "OCRService",
    "VectorStoreService",
    "MeetingService",
]

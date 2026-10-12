"""FastAPI dependency injection providers.

Uses lazy imports to avoid eager singleton construction at import time,
which would fail if data directories or external services are not yet
available (the lifespan handler creates directories first).
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.database import get_app_session
from app.services.meetings import MeetingService, meeting_service


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Provide an async database session for the application DB."""
    async for session in get_app_session():
        yield session


def get_llm() -> LLMService:
    """Provide the LLM service singleton."""
    from app.services.llm import LLMService, llm_service  # noqa: F811

    return llm_service


def get_embeddings() -> EmbeddingService:
    """Provide the embedding service singleton."""
    from app.services.embeddings import EmbeddingService, embedding_service  # noqa: F811

    return embedding_service


def get_vector_store() -> VectorStoreService:
    """Provide the vector store service singleton."""
    from app.services.hybrid_vector_store import hybrid_vector_store_service

    return hybrid_vector_store_service


def get_document_parser() -> DocumentParserService:
    """Provide the document parser service singleton."""
    from app.services.document_parser import (  # noqa: F811
        DocumentParserService,
        document_parser_service,
    )

    return document_parser_service


def get_ocr() -> OCRService:
    """Provide the OCR service singleton."""
    from app.services.ocr import OCRService, ocr_service  # noqa: F811

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

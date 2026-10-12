"""Document upload and analysis endpoints.

Provides:
    POST /documents/upload    — Upload a document for processing.
    POST /documents/analyze   — Parse and analyze a previously uploaded document.
    GET  /documents           — List all uploaded documents.
    GET  /documents/{id}      — Get document details and analysis results.
    DELETE /documents/{id}    — Delete an uploaded document.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: TC002

from app.api.middleware.error_handler import (
    DocumentTooLargeError,
    NotFoundError,
    UnsupportedFormatError,
)
from app.api.middleware.rate_limiting import limiter
from app.config import settings
from app.dependencies import (
    DocumentParserService,
    get_authenticated_session,
    get_db,
    get_document_parser,
)
from app.models.db_models import Document
from app.models.enums import DocumentFormat, DocumentStatus
from app.models.schemas import (
    DocumentAnalysisResult,
    DocumentListItem,
    DocumentUploadResponse,
    ExtractedTable,
)
from app.services.auth import AuthenticatedSession  # noqa: TC001

logger = structlog.get_logger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# POST /documents/upload
# ---------------------------------------------------------------------------


@router.post("/documents/upload", response_model=DocumentUploadResponse)
@limiter.limit(settings.rate_limit_upload)
async def upload_document(
    request: Request,
    file: UploadFile,
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> DocumentUploadResponse:
    """Upload a document for later analysis.

    Validates the file extension and size, saves to disk, and creates a
    database record with status 'pending'.
    """
    filename = file.filename or "unknown"
    extension = Path(filename).suffix.lower()

    # Validate extension
    if extension not in settings.allowed_extensions_set:
        raise UnsupportedFormatError(extension)

    # Validate size (read header to check)
    content = await file.read()
    size_bytes = len(content)
    if size_bytes > settings.max_upload_size_bytes:
        raise DocumentTooLargeError(settings.max_upload_size_bytes)

    # Determine format
    try:
        doc_format = DocumentFormat.from_extension(extension)
    except ValueError as exc:
        raise UnsupportedFormatError(extension) from exc

    # Save to disk
    doc_id = str(uuid.uuid4())
    safe_name = f"{doc_id}{extension}"
    storage_path = settings.upload_path / safe_name
    storage_path.write_bytes(content)

    # Create DB record
    doc = Document(
        id=doc_id,
        owner_id=authenticated.account.id,
        filename=filename,
        format=doc_format.value,
        size_bytes=size_bytes,
        storage_path=str(storage_path),
        status=DocumentStatus.PENDING,
    )
    db.add(doc)
    await db.commit()

    logger.info(
        "document_uploaded",
        doc_id=doc_id,
        filename=filename,
        format=doc_format.value,
        size_bytes=size_bytes,
    )

    return DocumentUploadResponse(
        id=doc_id,
        filename=filename,
        format=doc_format,
        size_bytes=size_bytes,
        status=DocumentStatus.PENDING,
    )


# ---------------------------------------------------------------------------
# POST /documents/analyze
# ---------------------------------------------------------------------------


@router.post("/documents/{document_id}/analyze", response_model=DocumentAnalysisResult)
async def analyze_document(
    document_id: str,
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
    parser: DocumentParserService = Depends(get_document_parser),  # noqa: B008
) -> DocumentAnalysisResult:
    """Parse and analyze a previously uploaded document.

    Extracts text, tables, and metadata from the document file.
    Updates the document status to 'completed' or 'failed'.
    """
    # Fetch document record
    stmt = select(Document).where(
        Document.id == document_id, Document.owner_id == authenticated.account.id
    )
    result = await db.execute(stmt)
    doc = result.scalar_one_or_none()

    if doc is None:
        raise NotFoundError("Document", document_id)

    file_path = Path(doc.storage_path)
    if not file_path.exists():
        raise NotFoundError("Document file", document_id)

    # Mark as processing
    doc.status = DocumentStatus.PROCESSING
    await db.commit()

    try:
        doc_format = DocumentFormat(doc.format)
        parsed = await parser.parse(file_path, doc_format)

        # Update document record
        doc.status = DocumentStatus.COMPLETED
        doc.page_count = parsed.page_count
        doc.word_count = parsed.word_count
        await db.commit()

        logger.info(
            "document_analyzed",
            doc_id=document_id,
            word_count=parsed.word_count,
            table_count=len(parsed.tables),
        )

        return DocumentAnalysisResult(
            document_id=document_id,
            filename=doc.filename,
            format=doc_format,
            text=parsed.text,
            tables=[
                ExtractedTable(
                    page=t.get("page"),
                    headers=t.get("headers", []),
                    rows=t.get("rows", []),
                )
                for t in parsed.tables
            ],
            metadata=parsed.metadata,
            page_count=parsed.page_count,
            word_count=parsed.word_count,
            status=DocumentStatus.COMPLETED,
        )

    except Exception as exc:
        doc.status = DocumentStatus.FAILED
        doc.error_message = str(exc)[:1000]
        await db.commit()
        logger.error("document_analysis_failed", doc_id=document_id, error=str(exc))
        raise


# ---------------------------------------------------------------------------
# GET /documents
# ---------------------------------------------------------------------------


@router.get("/documents", response_model=list[DocumentListItem])
async def list_documents(
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> list[DocumentListItem]:
    """List all uploaded documents ordered by creation date."""
    stmt = (
        select(Document)
        .where(Document.owner_id == authenticated.account.id)
        .order_by(Document.created_at.desc())
    )
    result = await db.execute(stmt)
    docs = result.scalars().all()

    return [
        DocumentListItem(
            id=doc.id,
            filename=doc.filename,
            format=DocumentFormat(doc.format),
            size_bytes=doc.size_bytes,
            status=DocumentStatus(doc.status),
            created_at=doc.created_at,
        )
        for doc in docs
    ]


# ---------------------------------------------------------------------------
# GET /documents/{document_id}
# ---------------------------------------------------------------------------


@router.get("/documents/{document_id}")
async def get_document(
    document_id: str,
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> dict[str, Any]:
    """Get detailed information about a specific document."""
    stmt = select(Document).where(
        Document.id == document_id, Document.owner_id == authenticated.account.id
    )
    result = await db.execute(stmt)
    doc = result.scalar_one_or_none()

    if doc is None:
        raise NotFoundError("Document", document_id)

    return {
        "id": doc.id,
        "filename": doc.filename,
        "format": doc.format,
        "size_bytes": doc.size_bytes,
        "storage_path": doc.storage_path,
        "status": doc.status,
        "page_count": doc.page_count,
        "word_count": doc.word_count,
        "error_message": doc.error_message,
        "created_at": doc.created_at.isoformat(),
        "updated_at": doc.updated_at.isoformat(),
    }


# ---------------------------------------------------------------------------
# DELETE /documents/{document_id}
# ---------------------------------------------------------------------------


@router.delete("/documents/{document_id}")
async def delete_document(
    document_id: str,
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> dict[str, str]:
    """Delete a document and its file from disk."""
    stmt = select(Document).where(
        Document.id == document_id, Document.owner_id == authenticated.account.id
    )
    result = await db.execute(stmt)
    doc = result.scalar_one_or_none()

    if doc is None:
        raise NotFoundError("Document", document_id)

    # Remove file from disk
    file_path = Path(doc.storage_path)
    if file_path.exists():
        file_path.unlink()

    await db.delete(doc)
    await db.commit()

    logger.info("document_deleted", doc_id=document_id)
    return {"status": "deleted", "document_id": document_id}

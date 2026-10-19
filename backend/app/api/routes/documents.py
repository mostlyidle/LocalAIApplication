"""Document upload and analysis endpoints.

Provides:
    POST /documents/upload    — Upload a document for processing.
    POST /documents/analyze   — Parse and analyze a previously uploaded document.
    GET  /documents           — List all uploaded documents.
    GET  /documents/{id}      — Get document details and analysis results.
    DELETE /documents/{id}    — Delete an uploaded document.
"""

from __future__ import annotations

import asyncio
import hashlib
import math
import re
import uuid
from pathlib import Path
from typing import Any

import structlog
from fastapi import APIRouter, Body, Depends, HTTPException, Request, UploadFile
from sqlalchemy import or_, select, update
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
    get_vector_store,
)
from app.models.db_models import Document, RagCollection, RagContainerFile, RedactionJob
from app.models.enums import DocumentFormat, DocumentStatus
from app.models.schemas import (
    DocumentAnalysisResult,
    DocumentAnalyzeRequest,
    DocumentListItem,
    DocumentUploadResponse,
    ExtractedTable,
)
from app.services.auth import AuthenticatedSession  # noqa: TC001
from app.services.rag_store import RagCollectionSchemaError
from app.services.redaction_job_worker import cleanup_redaction_job_artifacts
from app.services.vector_store import VectorStoreService  # noqa: TC001

logger = structlog.get_logger(__name__)
router = APIRouter()

_DOCUMENT_ANSWER_CONTEXT_LIMIT = 20_000
_DOCUMENT_QUERY_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "how",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "the",
        "to",
        "was",
        "what",
        "when",
        "where",
        "which",
        "who",
        "with",
    }
)


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _select_document_context(
    text: str,
    blocks: list[dict[str, Any]],
    prompt: str,
) -> str:
    """Choose relevant excerpts across a long document for question answering.

    Args:
        text: Full extracted document text.
        blocks: Parser blocks, including page metadata where available.
        prompt: The user's question about the document.

    Returns:
        The full text when it fits the model budget, otherwise ranked excerpts
        that preserve source page labels and nearby headings.
    """
    if len(text) <= _DOCUMENT_ANSWER_CONTEXT_LIMIT:
        return text

    passages: list[dict[str, Any]] = []
    source_blocks = blocks or [{"text": part} for part in re.split(r"\n\s*\n", text)]
    for block in source_blocks:
        block_text = str(block.get("text", "")).strip()
        if not block_text:
            continue
        for start in range(0, len(block_text), 3_600):
            passage: dict[str, Any] = {
                "text": block_text[start : start + 4_000],
                "page": block.get("page"),
                "section": block.get("section"),
            }
            passage["tokens"] = set(re.findall(r"[a-z0-9]+", passage["text"].casefold()))
            passages.append(passage)

    if not passages:
        return text[:_DOCUMENT_ANSWER_CONTEXT_LIMIT]

    query_tokens = set(re.findall(r"[a-z0-9]+", prompt.casefold())) - _DOCUMENT_QUERY_STOP_WORDS
    document_frequency = {
        token: sum(token in passage["tokens"] for passage in passages)
        for token in query_tokens
    }
    ranked = []
    for index, passage in enumerate(passages):
        score = sum(
            math.log1p(len(passages) / document_frequency[token])
            for token in query_tokens
            if document_frequency[token] and token in passage["tokens"]
        )
        if score:
            ranked.append((score, index))
    ranked.sort(reverse=True)

    if ranked:
        selected: list[int] = []
        seen: set[int] = set()
        for _, index in ranked[:8]:
            for candidate in (index - 1, index, index + 1):
                if 0 <= candidate < len(passages) and candidate not in seen:
                    selected.append(candidate)
                    seen.add(candidate)
    else:
        # Keep some coverage across the document if the question uses different terms.
        sample_count = min(12, len(passages))
        selected = sorted({
            round(index * (len(passages) - 1) / max(sample_count - 1, 1))
            for index in range(sample_count)
        })

    excerpts: list[str] = []
    remaining = _DOCUMENT_ANSWER_CONTEXT_LIMIT
    for index in selected:
        passage = passages[index]
        label = ""
        if passage.get("page") is not None:
            label = f"Page {passage['page']}"
        if passage.get("section"):
            label = f"{label} · {passage['section']}" if label else str(passage["section"])
        content = f"[{label}]\n{passage['text']}" if label else passage["text"]
        if len(content) > remaining:
            content = content[:remaining]
        if content:
            excerpts.append(content)
            remaining -= len(content) + 2
        if remaining <= 0:
            break

    return "\n\n".join(excerpts)


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

    # Starlette knows the parsed file size; cap reads if that metadata is absent.
    if file.size is not None and file.size > settings.max_upload_size_bytes:
        raise DocumentTooLargeError(settings.max_upload_size_bytes)
    content = await file.read(settings.max_upload_size_bytes + 1)
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
        content_sha256=hashlib.sha256(content).hexdigest(),
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
    request: Request,
    body: DocumentAnalyzeRequest = Body(default=DocumentAnalyzeRequest()),
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
        answer = None
        if body.prompt:
            from app.models.profile_schemas import TaskRequest

            profile = request.app.state.agent_registry.default_for("document")
            task = TaskRequest(
                prompt=body.prompt,
                agent_name=profile.name,
                context=_select_document_context(parsed.text, parsed.blocks, body.prompt),
            )
            answer = (
                await request.app.state.task_runner.run(
                    task,
                    request_id=str(uuid.uuid4()),
                    owner_id=authenticated.account.id,
                )
            ).answer

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
            answer=answer,
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

    hashes_updated = False
    for doc in docs:
        if doc.content_sha256 is not None:
            continue
        try:
            doc.content_sha256 = await asyncio.to_thread(_sha256_file, doc.storage_path)
            hashes_updated = True
        except OSError:
            logger.warning("document_hash_unavailable", document_id=doc.id)
    if hashes_updated:
        await db.commit()

    return [
        DocumentListItem(
            id=doc.id,
            filename=doc.filename,
            format=DocumentFormat(doc.format),
            size_bytes=doc.size_bytes,
            content_sha256=doc.content_sha256,
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
    vector_store: VectorStoreService = Depends(get_vector_store),  # noqa: B008
) -> dict[str, str]:
    """Delete a document and its file from disk."""
    stmt = select(Document).where(
        Document.id == document_id, Document.owner_id == authenticated.account.id
    )
    result = await db.execute(stmt)
    doc = result.scalar_one_or_none()

    if doc is None:
        raise NotFoundError("Document", document_id)

    memberships = list(
        (
            await db.scalars(
                select(RagContainerFile).where(
                    or_(
                        RagContainerFile.document_id == document_id,
                        RagContainerFile.indexed_document_id == document_id,
                    )
                )
            )
        ).all()
    )
    if any(item.status in {"processing", "deleting"} for item in memberships):
        raise HTTPException(status_code=409, detail="Wait for container indexing to finish.")
    prior_statuses = {item.id: item.status for item in memberships}
    owned_collections = list(
        (
            await db.scalars(
                select(RagCollection.name).where(
                    RagCollection.owner_id == authenticated.account.id
                )
            )
        ).all()
    )
    if memberships:
        claimed = await db.execute(
            update(RagContainerFile)
            .where(
                RagContainerFile.id.in_(prior_statuses),
                RagContainerFile.status.not_in(("processing", "deleting")),
            )
            .values(status="deleting")
        )
        if claimed.rowcount != len(memberships):
            await db.rollback()
            raise HTTPException(status_code=409, detail="Wait for container indexing to finish.")
    redaction_jobs = list(
        (
            await db.scalars(
                select(RedactionJob).where(
                    RedactionJob.document_id == document_id,
                    RedactionJob.owner_id == authenticated.account.id,
                )
            )
        ).all()
    )
    if any(job.status == "exporting" for job in redaction_jobs):
        await db.rollback()
        raise HTTPException(status_code=409, detail="Wait for redacted export to finish first.")
    for job in redaction_jobs:
        if job.status in {"queued", "processing"}:
            job.status = "cancelled"
            job.lease_until = None
    await db.commit()

    try:
        for item in memberships:
            if item.indexed_document_id:
                await vector_store.delete_asset(item.collection_name, item.indexed_document_id)
            if item.document_id == document_id:
                await db.delete(item)
            else:
                item.indexed_document_id = None
                item.status = prior_statuses[item.id]
        for collection in owned_collections:
            try:
                await vector_store.delete_asset(collection, document_id)
            except RagCollectionSchemaError as exc:
                logger.warning(
                    "document_vector_cleanup_skipped",
                    document_id=document_id,
                    collection=collection,
                    reason=str(exc),
                )
        for job in redaction_jobs:
            await db.delete(job)
        await db.delete(doc)
        await db.commit()
    except Exception:
        await db.rollback()
        for file_id, status in prior_statuses.items():
            item = await db.get(RagContainerFile, file_id)
            if item is not None:
                item.status = status
        await db.commit()
        raise

    Path(doc.storage_path).unlink(missing_ok=True)
    for job in redaction_jobs:
        cleanup_redaction_job_artifacts(job.job_dir, job.owner_id)

    logger.info("document_deleted", doc_id=document_id)
    return {"status": "deleted", "document_id": document_id}

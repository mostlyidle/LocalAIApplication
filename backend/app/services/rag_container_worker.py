"""Durably ingest staged container files into their account-owned Qdrant index."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import and_, or_, select, update

from app.models.db_models import Document, RagCollection, RagContainerFile
from app.models.enums import DocumentFormat

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.services.document_parser import DocumentParserService
    from app.services.vector_store import VectorStoreService

logger = structlog.get_logger(__name__)
MAX_ATTEMPTS = 5
LEASE_SECONDS = 3_600


async def process_one_container_file(
    db: AsyncSession,
    *,
    parser: DocumentParserService | None = None,
    vector_store: VectorStoreService | None = None,
) -> bool:
    """Claim and index one file. Return whether a file was claimed."""
    file_id = await _claim_file(db)
    if file_id is None:
        return False

    staged = await db.get(RagContainerFile, file_id)
    if staged is None:
        return True
    container = await db.get(RagCollection, staged.collection_name)
    document = await db.get(Document, staged.document_id)
    if (
        container is None
        or container.display_name is None
        or document is None
        or document.owner_id != container.owner_id
    ):
        await _fail_file(db, file_id, "Container or source document no longer exists.")
        return True

    file_path = Path(document.storage_path)
    if not file_path.is_file():
        await _fail_file(db, file_id, "Uploaded source file is missing.")
        return True

    if parser is None:
        from app.services.document_parser import document_parser_service

        parser = document_parser_service
    if vector_store is None:
        from app.services.hybrid_vector_store import hybrid_vector_store_service

        vector_store = hybrid_vector_store_service

    try:
        parsed = await parser.parse(file_path, DocumentFormat(document.format))
        chunks = parser.chunk_document(
            parsed,
            metadata={
                "source": staged.relative_path,
                "source_path": staged.relative_path,
                "filename": Path(staged.relative_path).name,
                "document_id": document.id,
                "content_sha256": staged.sha256,
                "format": document.format,
            },
        )
        previous_document_id = staged.indexed_document_id
        if chunks:
            await vector_store.add_documents(
                texts=[chunk["text"] for chunk in chunks],
                metadatas=[chunk["metadata"] for chunk in chunks],
                ids=[f"{document.id}-chunk-{index}" for index in range(len(chunks))],
                collection=staged.collection_name,
            )
        if previous_document_id and previous_document_id != document.id:
            await vector_store.delete_asset(staged.collection_name, previous_document_id)

        staged = await db.get(RagContainerFile, file_id, populate_existing=True)
        if staged is not None:
            staged.indexed_document_id = document.id
            staged.status = "indexed"
            staged.chunk_count = len(chunks)
            staged.last_error = None
            staged.lease_until = None
            await db.commit()
        logger.info(
            "rag_container_file_indexed",
            container=container.name,
            file_id=file_id,
            chunk_count=len(chunks),
        )
    except Exception as exc:
        await _retry_or_fail(db, file_id, str(exc))
        logger.warning(
            "rag_container_file_failed",
            container=container.name,
            file_id=file_id,
            error_type=type(exc).__name__,
            exc_info=True,
        )
    return True


async def run_container_worker(stop_event: asyncio.Event, *, poll_seconds: float = 2) -> None:
    """Poll the application database until shutdown is requested."""
    from app.services.database import get_app_session_factory

    while not stop_event.is_set():
        processed = False
        try:
            async with get_app_session_factory()() as db:
                processed = await process_one_container_file(db)
        except Exception as exc:
            logger.warning("rag_container_worker_iteration_failed", error_type=type(exc).__name__)

        if processed:
            continue
        with suppress(TimeoutError):
            await asyncio.wait_for(stop_event.wait(), timeout=poll_seconds)


async def _claim_file(db: AsyncSession) -> str | None:
    now = datetime.now(UTC)
    candidate = await db.scalar(
        select(RagContainerFile)
        .where(
            or_(
                and_(
                    RagContainerFile.status == "queued",
                    RagContainerFile.available_at <= now,
                ),
                and_(
                    RagContainerFile.status == "processing",
                    RagContainerFile.lease_until <= now,
                ),
            )
        )
        .order_by(RagContainerFile.available_at, RagContainerFile.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if candidate is None:
        return None
    claimable = (
        and_(
            RagContainerFile.status == "queued",
            RagContainerFile.available_at <= now,
        )
        if candidate.status == "queued"
        else and_(
            RagContainerFile.status == "processing",
            RagContainerFile.lease_until <= now,
        )
    )
    result = await db.execute(
        update(RagContainerFile)
        .where(RagContainerFile.id == candidate.id, claimable)
        .values(
            status="processing",
            attempts=RagContainerFile.attempts + 1,
            lease_until=now + timedelta(seconds=LEASE_SECONDS),
            last_error=None,
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        await db.rollback()
        return None
    await db.commit()
    return candidate.id


async def _fail_file(db: AsyncSession, file_id: str, error: str) -> None:
    staged = await db.get(RagContainerFile, file_id, populate_existing=True)
    if staged is None:
        return
    staged.status = "failed"
    staged.last_error = error[:2_000]
    staged.lease_until = None
    await db.commit()


async def _retry_or_fail(db: AsyncSession, file_id: str, error: str) -> None:
    staged = await db.get(RagContainerFile, file_id, populate_existing=True)
    if staged is None:
        return
    staged.lease_until = None
    staged.last_error = error[:2_000]
    if staged.attempts >= MAX_ATTEMPTS:
        staged.status = "failed"
    else:
        staged.status = "queued"
        staged.available_at = datetime.now(UTC) + timedelta(
            seconds=min(15 * (2 ** (staged.attempts - 1)), 1_800)
        )
    await db.commit()

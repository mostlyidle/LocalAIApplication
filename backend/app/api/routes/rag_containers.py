"""Account-private containers for staged documents and vector indexes."""

from __future__ import annotations

import hashlib
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

import structlog
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: TC002 - FastAPI resolves this at runtime

from app.api.middleware.error_handler import (
    AppError,
    DocumentTooLargeError,
    NotFoundError,
    UnsupportedFormatError,
)
from app.api.middleware.rate_limiting import limiter
from app.config import settings
from app.dependencies import get_authenticated_session, get_db, get_vector_store
from app.models.db_models import Document, RagCollection, RagContainerFile
from app.models.enums import DocumentFormat
from app.models.schemas import (
    RAGContainerCreateRequest,
    RAGContainerFileInfo,
    RAGContainerFileUploadFailure,
    RAGContainerInfo,
    RAGContainerUploadResult,
)
from app.services.auth import AuthenticatedSession  # noqa: TC001
from app.services.vector_store import VectorStoreService  # noqa: TC001

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/rag/containers", tags=["RAG"])
_DRIVE_PREFIX = re.compile(r"^[A-Za-z]:")
MAX_UPLOAD_BATCH_BYTES = 500 * 1024 * 1024


@router.get("", response_model=list[RAGContainerInfo])
async def list_containers(
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> list[RAGContainerInfo]:
    containers = list(
        (
            await db.scalars(
                select(RagCollection)
                .where(
                    RagCollection.owner_id == authenticated.account.id,
                    RagCollection.display_name.is_not(None),
                )
                .order_by(RagCollection.created_at.desc())
            )
        ).all()
    )
    counts: dict[str, dict[str, int]] = {item.name: {} for item in containers}
    if counts:
        files = (
            await db.scalars(
                select(RagContainerFile).where(RagContainerFile.collection_name.in_(counts))
            )
        ).all()
        for item in files:
            current = counts[item.collection_name]
            current["file_count"] = current.get("file_count", 0) + 1
            current["chunk_count"] = current.get("chunk_count", 0) + item.chunk_count
            key = f"{item.status}_file_count"
            current[key] = current.get(key, 0) + 1
    return [
        RAGContainerInfo(
            name=item.name,
            display_name=item.display_name or item.name,
            file_count=counts[item.name].get("file_count", 0),
            indexed_file_count=counts[item.name].get("indexed_file_count", 0),
            staged_file_count=counts[item.name].get("staged_file_count", 0),
            queued_file_count=counts[item.name].get("queued_file_count", 0),
            processing_file_count=counts[item.name].get("processing_file_count", 0),
            failed_file_count=counts[item.name].get("failed_file_count", 0),
            chunk_count=counts[item.name].get("chunk_count", 0),
        )
        for item in containers
    ]


@router.post("", response_model=RAGContainerInfo, status_code=201)
async def create_container(
    body: RAGContainerCreateRequest,
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> RAGContainerInfo:
    container = RagCollection(
        name=f"container_{uuid.uuid4().hex}",
        display_name=body.display_name,
        owner_id=authenticated.account.id,
    )
    db.add(container)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="A container with that name already exists.") from exc
    return RAGContainerInfo(
        name=container.name,
        display_name=body.display_name,
        file_count=0,
        indexed_file_count=0,
        staged_file_count=0,
        queued_file_count=0,
        processing_file_count=0,
        failed_file_count=0,
        chunk_count=0,
    )


@router.post("/{name}/load", status_code=202)
async def load_container(
    name: str,
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> dict[str, int]:
    await _owned_container(db, name, authenticated.account.id)
    result = await db.execute(
        update(RagContainerFile)
        .where(
            RagContainerFile.collection_name == name,
            RagContainerFile.status == "staged",
        )
        .values(status="queued", available_at=datetime.now(UTC), last_error=None)
    )
    await db.commit()
    return {"queued": result.rowcount or 0}


@router.get("/{name}/files", response_model=list[RAGContainerFileInfo])
async def list_container_files(
    name: str,
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> list[RAGContainerFileInfo]:
    await _owned_container(db, name, authenticated.account.id)
    rows = (
        await db.execute(
            select(RagContainerFile, Document.size_bytes)
            .join(Document, RagContainerFile.document_id == Document.id)
            .where(RagContainerFile.collection_name == name)
            .order_by(RagContainerFile.relative_path)
        )
    ).all()
    return [_file_info(staged, size_bytes) for staged, size_bytes in rows]


@router.post("/{name}/files", response_model=RAGContainerUploadResult)
@limiter.limit(settings.rate_limit_upload)
async def upload_container_file(
    request: Request,
    name: str,
    files: list[UploadFile] = File(...),  # noqa: B008
    relative_paths: list[str] = Form(...),  # noqa: B008
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> RAGContainerUploadResult:
    await _owned_container(db, name, authenticated.account.id)
    if len(files) != len(relative_paths):
        raise HTTPException(status_code=422, detail="Each file needs one relative path.")
    if len(files) > 100:
        raise HTTPException(status_code=413, detail="Upload at most 100 files per batch.")
    if sum(file.size or 0 for file in files) > MAX_UPLOAD_BATCH_BYTES:
        raise HTTPException(status_code=413, detail="Upload at most 500 MB per batch.")
    staged_files: list[RAGContainerFileInfo] = []
    failures: list[RAGContainerFileUploadFailure] = []
    seen_paths: set[str] = set()
    for file, relative_path in zip(files, relative_paths, strict=True):
        label = relative_path or file.filename or "Unnamed file"
        try:
            filename = (file.filename or "").replace("\\", "/").rsplit("/", 1)[-1]
            clean_path = _validate_relative_path(relative_path, filename)
            if clean_path in seen_paths:
                failures.append(
                    RAGContainerFileUploadFailure(
                        relative_path=clean_path,
                        message="This path appears more than once in the upload batch.",
                    )
                )
                continue
            seen_paths.add(clean_path)
            info, _ = await _stage_container_file(
                db,
                name=name,
                owner_id=authenticated.account.id,
                file=file,
                relative_path=relative_path,
            )
            staged_files.append(info)
        except AppError as exc:
            failures.append(RAGContainerFileUploadFailure(relative_path=label, message=exc.message))
        except HTTPException as exc:
            failures.append(
                RAGContainerFileUploadFailure(
                    relative_path=label,
                    message=str(exc.detail),
                )
            )
        except Exception as exc:
            logger.warning(
                "rag_container_file_upload_failed",
                container=name,
                relative_path=label,
                error_type=type(exc).__name__,
            )
            failures.append(
                RAGContainerFileUploadFailure(
                    relative_path=label,
                    message="Upload failed. Check file and try again.",
                )
            )
    return RAGContainerUploadResult(files=staged_files, failures=failures)


async def _stage_container_file(
    db: AsyncSession,
    *,
    name: str,
    owner_id: str,
    file: UploadFile,
    relative_path: str,
) -> tuple[RAGContainerFileInfo, str]:
    container = await _owned_container(db, name, owner_id)
    filename = (file.filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    extension = Path(filename).suffix.lower()
    if extension not in settings.allowed_extensions_set:
        raise UnsupportedFormatError(extension or "unknown")
    try:
        document_format = DocumentFormat.from_extension(extension)
    except ValueError as exc:
        raise UnsupportedFormatError(extension) from exc

    clean_path = _validate_relative_path(relative_path, filename)
    existing = await db.scalar(
        select(RagContainerFile).where(
            RagContainerFile.collection_name == name,
            RagContainerFile.relative_path == clean_path,
        )
    )
    if existing is not None and existing.status in {"processing", "deleting"}:
        raise HTTPException(status_code=409, detail="Wait for this file operation to finish.")

    content = await file.read(settings.max_upload_size_bytes + 1)
    if len(content) > settings.max_upload_size_bytes:
        raise DocumentTooLargeError(settings.max_upload_size_bytes)
    digest = hashlib.sha256(content).hexdigest()
    if existing is not None and existing.sha256 == digest:
        document = await db.get(Document, existing.document_id)
        if document is None:
            raise NotFoundError("Document", existing.document_id)
        return _file_info(existing, document.size_bytes), clean_path

    document_id = str(uuid.uuid4())
    storage_path = settings.upload_path / f"{document_id}{extension}"
    storage_path.write_bytes(content)
    document = Document(
        id=document_id,
        owner_id=container.owner_id,
        filename=filename,
        format=document_format.value,
        size_bytes=len(content),
        storage_path=str(storage_path),
        status="pending",
    )
    db.add(document)
    if existing is None:
        existing = RagContainerFile(
            collection_name=name,
            document_id=document_id,
            relative_path=clean_path,
            sha256=digest,
            status="staged",
        )
        db.add(existing)
    try:
        if existing.id is not None:
            await db.flush()
            updated = await db.execute(
                update(RagContainerFile)
                .where(
                    RagContainerFile.id == existing.id,
                    RagContainerFile.status.not_in(("processing", "deleting")),
                )
                .values(
                    document_id=document_id,
                    sha256=digest,
                    status="staged",
                    attempts=0,
                    available_at=datetime.now(UTC),
                    lease_until=None,
                    last_error=None,
                )
            )
            if updated.rowcount != 1:
                raise HTTPException(status_code=409, detail="Wait for this file operation to finish.")
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        storage_path.unlink(missing_ok=True)
        raise HTTPException(status_code=409, detail="This file path is already in the container.") from exc
    except Exception:
        await db.rollback()
        storage_path.unlink(missing_ok=True)
        raise
    if existing.id is not None:
        await db.refresh(existing)
    logger.info(
        "rag_container_file_uploaded",
        container=name,
        file_id=existing.id,
        relative_path=clean_path,
        size_bytes=len(content),
    )
    return _file_info(existing, len(content)), clean_path


@router.post("/{name}/files/{file_id}/retry", response_model=RAGContainerFileInfo)
async def retry_container_file(
    name: str,
    file_id: str,
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> RAGContainerFileInfo:
    await _owned_container(db, name, authenticated.account.id)
    staged = await _container_file(db, name, file_id)
    if staged.status != "failed":
        raise HTTPException(status_code=409, detail="Only failed files can be retried.")
    updated = await db.execute(
        update(RagContainerFile)
        .where(RagContainerFile.id == file_id, RagContainerFile.status == "failed")
        .values(
            status="queued",
            attempts=0,
            available_at=datetime.now(UTC),
            lease_until=None,
            last_error=None,
        )
    )
    if updated.rowcount != 1:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Only failed files can be retried.")
    await db.commit()
    await db.refresh(staged)
    document = await db.get(Document, staged.document_id)
    return _file_info(staged, document.size_bytes if document else 0)


@router.delete("/{name}/files/{file_id}")
async def delete_container_file(
    name: str,
    file_id: str,
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
    vector_store: VectorStoreService = Depends(get_vector_store),  # noqa: B008
) -> dict[str, bool]:
    await _owned_container(db, name, authenticated.account.id)
    staged = await _container_file(db, name, file_id)
    if staged.status in {"processing", "deleting"}:
        raise HTTPException(status_code=409, detail="Wait for indexing to finish before removing this file.")
    prior_status = staged.status
    claimed = await db.execute(
        update(RagContainerFile)
        .where(
            RagContainerFile.id == file_id,
            RagContainerFile.status.not_in(("processing", "deleting")),
        )
        .values(status="deleting")
    )
    if claimed.rowcount != 1:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Wait for indexing to finish before removing this file.")
    await db.commit()
    try:
        if staged.indexed_document_id:
            await vector_store.delete_asset(name, staged.indexed_document_id)
        await db.delete(staged)
        await db.commit()
    except Exception:
        await db.rollback()
        staged = await db.get(RagContainerFile, file_id)
        if staged is not None:
            staged.status = prior_status
            await db.commit()
        raise
    return {"deleted": True}


@router.delete("/{name}")
async def delete_container(
    name: str,
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
    vector_store: VectorStoreService = Depends(get_vector_store),  # noqa: B008
) -> dict[str, bool]:
    container = await _owned_container(db, name, authenticated.account.id)
    files = list(
        (
            await db.scalars(
                select(RagContainerFile).where(RagContainerFile.collection_name == name)
            )
        ).all()
    )
    if any(staged.status in {"processing", "deleting"} for staged in files):
        raise HTTPException(status_code=409, detail="Wait for indexing to finish before deleting this container.")
    prior_statuses = {staged.id: staged.status for staged in files}
    claimed = await db.execute(
        update(RagContainerFile)
        .where(
            RagContainerFile.collection_name == name,
            RagContainerFile.status.not_in(("processing", "deleting")),
        )
        .values(status="deleting")
    )
    if claimed.rowcount != len(files):
        await db.rollback()
        raise HTTPException(status_code=409, detail="Wait for indexing to finish before deleting this container.")
    await db.commit()
    try:
        await vector_store.delete_collection(name)
        for staged in files:
            await db.delete(staged)
        await db.delete(container)
        await db.commit()
    except Exception:
        await db.rollback()
        for file_id, status in prior_statuses.items():
            staged = await db.get(RagContainerFile, file_id)
            if staged is not None:
                staged.status = status
        await db.commit()
        raise
    logger.info("rag_container_deleted", container=name)
    return {"deleted": True}


async def _owned_container(db: AsyncSession, name: str, owner_id: str) -> RagCollection:
    container = await db.get(RagCollection, name)
    if container is None or container.owner_id != owner_id or container.display_name is None:
        raise NotFoundError("Container", name)
    return container


async def _container_file(db: AsyncSession, name: str, file_id: str) -> RagContainerFile:
    staged = await db.scalar(
        select(RagContainerFile).where(
            RagContainerFile.collection_name == name,
            RagContainerFile.id == file_id,
        )
    )
    if staged is None:
        raise NotFoundError("Container file", file_id)
    return staged


def _validate_relative_path(value: str, filename: str) -> str:
    normalized = value.replace("\\", "/")
    raw_parts = normalized.split("/")
    if (
        not normalized
        or normalized.startswith("/")
        or _DRIVE_PREFIX.match(normalized)
        or "\x00" in normalized
        or any(part == ".." for part in raw_parts)
    ):
        raise HTTPException(status_code=422, detail="File path must stay inside selected folder.")
    path = PurePosixPath(normalized)
    clean_path = "/".join(part for part in path.parts if part not in {"", "."})
    if not clean_path or len(clean_path) > 1_024 or path.name != filename:
        raise HTTPException(status_code=422, detail="File path is invalid.")
    return clean_path


def _file_info(staged: RagContainerFile, size_bytes: int) -> RAGContainerFileInfo:
    return RAGContainerFileInfo(
        id=staged.id,
        relative_path=staged.relative_path,
        status=staged.status,
        chunk_count=staged.chunk_count,
        size_bytes=size_bytes,
        last_error=staged.last_error,
    )

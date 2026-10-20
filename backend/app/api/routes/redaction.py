"""Reviewable, account-scoped document redaction jobs."""

from __future__ import annotations

import asyncio
import hashlib
import json
import tempfile
import uuid
import zipfile
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pymupdf
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse
from sqlalchemy import select, update
from starlette.background import BackgroundTask

from app.api.middleware.rate_limiting import limiter
from app.config import settings
from app.dependencies import get_authenticated_session, get_db
from app.models.db_models import Document, RedactionJob
from app.models.redaction_schemas import (
    RedactionBatchCreate,
    RedactionBatchResponse,
    RedactionClarification,
    RedactionFailedPage,
    RedactionFinding,
    RedactionFindingUpdate,
    RedactionJobCreate,
    RedactionJobResponse,
    RedactionManualBox,
    RedactionPageAction,
    RedactionPageSummary,
    RedactionReviewResponse,
)
from app.services.redaction_detector import page_from_data
from app.services.redaction_documents import (
    RedactionDocumentError,
    redact_to_image_pdf,
    render_page_image,
    validate_boxes,
)
from app.services.redaction_job_worker import (
    load_job_data,
    queue_redaction_batch_jobs,
    queue_redaction_job,
    save_job_data,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.services.auth import AuthenticatedSession

router = APIRouter(prefix="/redaction-jobs", tags=["Document Redaction"])
batch_router = APIRouter(prefix="/redaction-batches", tags=["Document Redaction"])


async def _get_owned_job(db: AsyncSession, job_id: str, owner_id: str) -> RedactionJob:
    job = await db.scalar(
        select(RedactionJob).where(
            RedactionJob.id == job_id,
            RedactionJob.owner_id == owner_id,
        )
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Redaction job not found.")
    return job


async def _lock_review_job(
    db: AsyncSession,
    job: RedactionJob,
    owner_id: str,
    *,
    allowed_statuses: tuple[str, ...] = ("review_ready", "approved", "exported"),
    revision: int | None = None,
) -> None:
    """Serialize review-file mutations through the owning database row."""
    statement = update(RedactionJob).where(
        RedactionJob.id == job.id,
        RedactionJob.owner_id == owner_id,
        RedactionJob.status.in_(allowed_statuses),
    )
    if revision is not None:
        statement = statement.where(RedactionJob.review_revision == revision)
    result = await db.execute(
        statement.values(
            review_revision=RedactionJob.review_revision,
            updated_at=RedactionJob.updated_at,
        ).execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        await db.rollback()
        raise HTTPException(
            status_code=409, detail="The review changed. Refresh before continuing."
        )
    await db.refresh(job)


def _render_source_page(source_path: str, page_number: int) -> bytes:
    """Render and close a source page inside one worker thread."""
    pdf = pymupdf.open(source_path)
    try:
        if page_number < 0 or page_number >= len(pdf):
            raise IndexError("Page not found.")
        return render_page_image(pdf[page_number])
    finally:
        pdf.close()


async def _require_renderable_source_page(
    db: AsyncSession,
    job: RedactionJob,
    page_number: int,
) -> None:
    """Ensure an owned source page can be rendered before recovery actions.

    Args:
        db: Database session.
        job: Owned redaction job.
        page_number: Zero-based source page number.

    Raises:
        HTTPException: If the source page is missing or cannot be rendered.
    """
    document = await db.get(Document, job.document_id)
    if document is None or document.owner_id != job.owner_id:
        raise HTTPException(status_code=404, detail="Source document not found.")
    try:
        await asyncio.to_thread(_render_source_page, document.storage_path, page_number)
    except IndexError as exc:
        raise HTTPException(status_code=404, detail="Page not found.") from exc
    except (OSError, RuntimeError, ValueError, pymupdf.FileDataError) as exc:
        raise HTTPException(
            status_code=409,
            detail="This page cannot be rendered. Retry processing before recovery.",
        ) from exc


def _job_response(job: RedactionJob, warnings: list[str] | None = None) -> RedactionJobResponse:
    return RedactionJobResponse(
        id=job.id,
        document_id=job.document_id,
        batch_id=job.batch_id,
        status=job.status,
        page_count=job.page_count,
        pages_processed=job.pages_processed,
        review_revision=job.review_revision,
        approved_revision=job.approved_revision,
        clarification_question=job.clarification_question,
        error_message=job.error_message,
        warnings=warnings or [],
    )


def _write_redaction_batch_archive(export_paths: list[Path], archive_path: Path) -> None:
    """Write exported PDFs with neutral names into a batch ZIP."""
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_STORED) as archive:
        for index, export_path in enumerate(export_paths, start=1):
            archive.write(export_path, arcname=f"redacted-document-{index:03}.pdf")


def _review_payload(job: RedactionJob) -> tuple[list[RedactionFinding], list[str]]:
    data = load_job_data(job)
    return [RedactionFinding.model_validate(item) for item in data["findings"]], data["warnings"]


def _find_failed_page(data: dict[str, Any], page_number: int) -> dict[str, Any] | None:
    return next(
        (item for item in data.get("failed_pages", []) if item["page_number"] == page_number),
        None,
    )


def _has_whole_page_redaction(data: dict[str, Any], page_number: int) -> bool:
    page = page_from_data(data["pages"][page_number])
    return any(
        finding["page_number"] == page_number
        and finding["selected"]
        and any(
            box[0] <= 0 and box[1] <= 0 and box[2] >= page.width and box[3] >= page.height
            for box in finding["boxes"]
        )
        for finding in data["findings"]
    )


@router.post("", response_model=RedactionJobResponse, status_code=202)
@limiter.limit(settings.rate_limit_upload)
async def create_redaction_job(
    request: Request,
    payload: RedactionJobCreate,
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> RedactionJobResponse:
    """Queue redaction analysis for an existing account-owned PDF or image."""
    document = await db.scalar(
        select(Document).where(
            Document.id == payload.document_id,
            Document.owner_id == authenticated.account.id,
        )
    )
    if document is None:
        raise HTTPException(status_code=404, detail="Source document not found.")
    try:
        job = await queue_redaction_job(db, document, authenticated.account.id, payload)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=410, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _job_response(job)


@batch_router.post("", response_model=RedactionBatchResponse, status_code=202)
@limiter.limit(settings.rate_limit_upload)
async def create_redaction_batch(
    request: Request,
    payload: RedactionBatchCreate,
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> RedactionBatchResponse:
    """Queue one independently reviewable job for each owned source document.

    Args:
        request: HTTP request used by upload rate limiting.
        payload: Source IDs and shared redaction policy.
        authenticated: Current authenticated account.
        db: Database session.

    Returns:
        The batch identifier and queued jobs.
    """
    documents = list(
        (
            await db.scalars(
                select(Document).where(
                    Document.owner_id == authenticated.account.id,
                    Document.id.in_(payload.document_ids),
                )
            )
        ).all()
    )
    if len(documents) != len(payload.document_ids):
        raise HTTPException(status_code=404, detail="One or more source documents were not found.")
    documents_by_id = {document.id: document for document in documents}
    ordered_documents = [documents_by_id[document_id] for document_id in payload.document_ids]
    try:
        batch_id, jobs = await queue_redaction_batch_jobs(
            db, ordered_documents, authenticated.account.id, payload
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=410, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return RedactionBatchResponse(
        id=batch_id,
        jobs=[_job_response(job) for job in jobs],
    )


@batch_router.get("/{batch_id}", response_model=RedactionBatchResponse)
async def get_redaction_batch(
    batch_id: str,
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> RedactionBatchResponse:
    """Return the current status of every job in an owned batch.

    Args:
        batch_id: Identifier shared by the batch's redaction jobs.
        authenticated: Current authenticated account.
        db: Database session.

    Returns:
        The batch identifier and current job statuses.
    """
    jobs = list(
        (
            await db.scalars(
                select(RedactionJob)
                .where(
                    RedactionJob.batch_id == batch_id,
                    RedactionJob.owner_id == authenticated.account.id,
                )
                .order_by(RedactionJob.created_at, RedactionJob.id)
            )
        ).all()
    )
    if not jobs:
        raise HTTPException(status_code=404, detail="Redaction batch not found.")
    return RedactionBatchResponse(
        id=batch_id,
        jobs=[_job_response(job) for job in jobs],
    )


@batch_router.get("/{batch_id}/download")
async def download_redaction_batch(
    batch_id: str,
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> FileResponse:
    """Download every current exported PDF in an owned batch as a ZIP.

    Args:
        batch_id: Identifier shared by the batch's redaction jobs.
        authenticated: Current authenticated account.
        db: Database session.

    Returns:
        A private, temporary ZIP containing the sanitized PDFs.
    """
    jobs = list(
        (
            await db.scalars(
                select(RedactionJob)
                .where(
                    RedactionJob.batch_id == batch_id,
                    RedactionJob.owner_id == authenticated.account.id,
                )
                .order_by(RedactionJob.created_at, RedactionJob.id)
            )
        ).all()
    )
    if not jobs:
        raise HTTPException(status_code=404, detail="Redaction batch not found.")
    if any(
        job.status != "exported" or job.approved_revision != job.review_revision for job in jobs
    ):
        raise HTTPException(
            status_code=409,
            detail="Export every current review in the batch before downloading the ZIP.",
        )

    redaction_root = (settings.upload_path / "redaction-jobs").resolve()
    owner_dir = (redaction_root / authenticated.account.id).resolve()
    if owner_dir.parent != redaction_root or not owner_dir.is_dir():
        raise HTTPException(status_code=404, detail="Redacted batch files are unavailable.")
    export_paths = []
    for job in jobs:
        job_dir = Path(job.job_dir).resolve()
        if job_dir.parent != owner_dir:
            raise HTTPException(status_code=404, detail="Redacted batch files are unavailable.")
        export_path = (job_dir / "redacted.pdf").resolve()
        if export_path.parent != job_dir or not export_path.is_file():
            raise HTTPException(status_code=409, detail="An exported PDF is unavailable.")
        export_paths.append(export_path)

    archive_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix="redaction-batch-",
            suffix=".zip",
            dir=owner_dir,
            delete=False,
        ) as archive_file:
            archive_path = Path(archive_file.name)
        await asyncio.to_thread(_write_redaction_batch_archive, export_paths, archive_path)
    except Exception:
        if archive_path is not None:
            with suppress(OSError):
                archive_path.unlink()
        raise

    return FileResponse(
        archive_path,
        media_type="application/zip",
        filename="redacted-documents.zip",
        headers={"Cache-Control": "no-store"},
        background=BackgroundTask(archive_path.unlink, missing_ok=True),
    )


@router.get("/{job_id}", response_model=RedactionJobResponse)
async def get_redaction_job(
    job_id: str,
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> RedactionJobResponse:
    job = await _get_owned_job(db, job_id, authenticated.account.id)
    warnings = []
    if job.status in {"review_ready", "approved", "exported"}:
        with suppress(OSError, ValueError, KeyError):
            _, warnings = _review_payload(job)
    return _job_response(job, warnings)


@router.post("/{job_id}/clarify", response_model=RedactionJobResponse)
@limiter.limit(settings.rate_limit_llm)
async def clarify_redaction_job(
    request: Request,
    job_id: str,
    payload: RedactionClarification,
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> RedactionJobResponse:
    """Resume an ambiguous redaction request with the owner's clarification."""
    job = await _get_owned_job(db, job_id, authenticated.account.id)
    if job.status != "needs_clarification":
        raise HTTPException(status_code=409, detail="This job is not waiting for clarification.")
    try:
        answers = json.loads(job.clarification_answers)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=500, detail="Clarification history is unavailable."
        ) from exc
    if not isinstance(answers, list) or not all(isinstance(answer, str) for answer in answers):
        raise HTTPException(status_code=500, detail="Clarification history is unavailable.")
    answers.append(payload.answer)
    result = await db.execute(
        update(RedactionJob)
        .where(
            RedactionJob.id == job.id,
            RedactionJob.owner_id == authenticated.account.id,
            RedactionJob.status == "needs_clarification",
        )
        .values(
            clarification_answers=json.dumps(answers, ensure_ascii=False),
            clarification_question=None,
            status="queued",
            pages_processed=0,
            lease_until=None,
            error_message=None,
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        await db.rollback()
        raise HTTPException(
            status_code=409, detail="This job is no longer waiting for clarification."
        )
    await db.commit()
    await db.refresh(job)
    return _job_response(job)


@router.get("/{job_id}/review", response_model=RedactionReviewResponse)
async def get_redaction_review(
    job_id: str,
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> RedactionReviewResponse:
    job = await _get_owned_job(db, job_id, authenticated.account.id)
    if job.status not in {"review_ready", "approved", "exported"}:
        raise HTTPException(status_code=409, detail="Redaction results are not ready for review.")
    data = load_job_data(job)
    findings = [RedactionFinding.model_validate(item) for item in data["findings"]]
    warnings = data["warnings"]
    pages = [
        RedactionPageSummary(number=index, width=page["width"], height=page["height"])
        for index, page in enumerate(data["pages"])
    ]
    failed_pages = [
        RedactionFailedPage.model_validate(
            {
                **item,
                "whole_page_redacted": _has_whole_page_redaction(data, item["page_number"]),
            }
        )
        for item in data.get("failed_pages", [])
    ]
    return RedactionReviewResponse(
        job=_job_response(job, warnings),
        findings=findings,
        pages=pages,
        failed_pages=failed_pages,
    )


@router.get("/{job_id}/pages/{page_number}/preview")
async def get_redaction_page_preview(
    job_id: str,
    page_number: int,
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> Response:
    job = await _get_owned_job(db, job_id, authenticated.account.id)
    if job.status not in {"review_ready", "approved", "exported"}:
        raise HTTPException(status_code=409, detail="Redaction results are not ready for review.")
    document = await db.get(Document, job.document_id)
    if document is None or document.owner_id != job.owner_id:
        raise HTTPException(status_code=404, detail="Source document not found.")
    try:
        image = await asyncio.to_thread(_render_source_page, document.storage_path, page_number)
    except IndexError as exc:
        raise HTTPException(status_code=404, detail="Page not found.") from exc
    except (OSError, RuntimeError, ValueError, pymupdf.FileDataError) as exc:
        raise HTTPException(status_code=410, detail="Source document is unavailable.") from exc
    return Response(image, media_type="image/png", headers={"Cache-Control": "no-store"})


@router.patch("/{job_id}/findings/{finding_id}", response_model=RedactionJobResponse)
async def update_redaction_finding(
    job_id: str,
    finding_id: str,
    payload: RedactionFindingUpdate,
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> RedactionJobResponse:
    job = await _get_owned_job(db, job_id, authenticated.account.id)
    await _lock_review_job(db, job, authenticated.account.id)
    _require_review_state(job)
    data = load_job_data(job)
    finding = next((item for item in data["findings"] if item["id"] == finding_id), None)
    if finding is None:
        raise HTTPException(status_code=404, detail="Redaction finding not found.")
    try:
        page = page_from_data(data["pages"][finding["page_number"]])
        boxes = validate_boxes(page, [tuple(box) for box in payload.boxes])
    except (RedactionDocumentError, IndexError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finding["selected"] = payload.selected
    finding["boxes"] = [list(box) for box in boxes]
    save_job_data(job, data)
    job.review_revision += 1
    job.approved_revision = None
    job.status = "review_ready"
    await db.commit()
    return _job_response(job, data["warnings"])


@router.post("/{job_id}/manual-boxes", response_model=RedactionJobResponse)
async def add_manual_redaction_box(
    job_id: str,
    payload: RedactionManualBox,
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> RedactionJobResponse:
    job = await _get_owned_job(db, job_id, authenticated.account.id)
    await _lock_review_job(db, job, authenticated.account.id)
    _require_review_state(job)
    data = load_job_data(job)
    if payload.page_number >= len(data["pages"]):
        raise HTTPException(status_code=404, detail="Page not found.")
    try:
        page = page_from_data(data["pages"][payload.page_number])
        boxes = validate_boxes(page, [tuple(payload.box)])
    except RedactionDocumentError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    data["findings"].append(
        {
            "id": str(uuid.uuid4()),
            "page_number": payload.page_number,
            "category": "manual region",
            "text": "Manual region",
            "confidence": None,
            "source": "manual",
            "selected": True,
            "boxes": [list(box) for box in boxes],
        }
    )
    save_job_data(job, data)
    job.review_revision += 1
    job.approved_revision = None
    job.status = "review_ready"
    await db.commit()
    return _job_response(job, data["warnings"])


@router.post("/{job_id}/retry-page", response_model=RedactionJobResponse)
async def retry_redaction_page(
    job_id: str,
    payload: RedactionPageAction,
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> RedactionJobResponse:
    """Retry extraction and detection for one failed page.

    Args:
        job_id: Redaction job identifier.
        payload: Page number to retry.
        authenticated: Current authenticated account.
        db: Database session.

    Returns:
        Updated queued job state.
    """
    job = await _get_owned_job(db, job_id, authenticated.account.id)
    await _lock_review_job(db, job, authenticated.account.id, allowed_statuses=("review_ready",))
    data = load_job_data(job)
    failure = _find_failed_page(data, payload.page_number)
    if failure is None:
        raise HTTPException(status_code=404, detail="Failed page not found.")
    retry_pages = set(data.get("retry_pages", []))
    retry_pages.add(payload.page_number)
    data["retry_pages"] = sorted(retry_pages)
    save_job_data(job, data)
    job.status = "queued"
    job.pages_processed = max(0, job.page_count - len(retry_pages))
    job.review_revision += 1
    job.approved_revision = None
    job.error_message = None
    job.lease_until = None
    await db.commit()
    with suppress(OSError):
        (Path(job.job_dir) / "redacted.pdf").unlink(missing_ok=True)
    await db.refresh(job)
    return _job_response(job)


@router.post("/{job_id}/resolve-page", response_model=RedactionJobResponse)
async def resolve_redaction_page_manually(
    job_id: str,
    payload: RedactionPageAction,
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> RedactionJobResponse:
    """Record the owner's manual inspection of an unreadable page.

    Args:
        job_id: Redaction job identifier.
        payload: Page number inspected by the owner.
        authenticated: Current authenticated account.
        db: Database session.

    Returns:
        Updated review job state.
    """
    job = await _get_owned_job(db, job_id, authenticated.account.id)
    await _require_renderable_source_page(db, job, payload.page_number)
    await _lock_review_job(db, job, authenticated.account.id, allowed_statuses=("review_ready",))
    data = load_job_data(job)
    failure = _find_failed_page(data, payload.page_number)
    if failure is None:
        raise HTTPException(status_code=404, detail="Failed page not found.")
    if not failure.get("manual_reviewed", False):
        failure["manual_reviewed"] = True
        save_job_data(job, data)
        job.review_revision += 1
        job.approved_revision = None
        await db.commit()
        await db.refresh(job)
    return _job_response(job, data["warnings"])


@router.post("/{job_id}/redact-whole-page", response_model=RedactionJobResponse)
async def redact_failed_page_whole(
    job_id: str,
    payload: RedactionPageAction,
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> RedactionJobResponse:
    """Resolve an extraction failure by selecting the full page for redaction.

    Args:
        job_id: Redaction job identifier.
        payload: Page number to redact completely.
        authenticated: Current authenticated account.
        db: Database session.

    Returns:
        Updated review job state.
    """
    job = await _get_owned_job(db, job_id, authenticated.account.id)
    await _require_renderable_source_page(db, job, payload.page_number)
    await _lock_review_job(db, job, authenticated.account.id, allowed_statuses=("review_ready",))
    data = load_job_data(job)
    failure = _find_failed_page(data, payload.page_number)
    if failure is None:
        raise HTTPException(status_code=404, detail="Failed page not found.")
    page = page_from_data(data["pages"][payload.page_number])
    box = (0.0, 0.0, page.width, page.height)
    try:
        boxes = validate_boxes(page, [box])
    except RedactionDocumentError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    data["findings"].append(
        {
            "id": str(uuid.uuid4()),
            "page_number": payload.page_number,
            "category": "whole page",
            "text": "Entire page",
            "confidence": None,
            "source": "manual",
            "selected": True,
            "boxes": [list(item) for item in boxes],
        }
    )
    save_job_data(job, data)
    job.review_revision += 1
    job.approved_revision = None
    await db.commit()
    await db.refresh(job)
    return _job_response(job, data["warnings"])


@router.post("/{job_id}/approve", response_model=RedactionJobResponse)
async def approve_redaction_review(
    job_id: str,
    revision: int,
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> RedactionJobResponse:
    job = await _get_owned_job(db, job_id, authenticated.account.id)
    await _lock_review_job(db, job, authenticated.account.id, revision=revision)
    _require_review_state(job)
    data = load_job_data(job)
    failed_pages = data.get("failed_pages", [])
    if any(
        not item.get("manual_reviewed", False)
        and not _has_whole_page_redaction(data, item["page_number"])
        for item in failed_pages
    ):
        raise HTTPException(
            status_code=409,
            detail="Retry, redact, or manually inspect every failed page before approval.",
        )
    manual_review_is_complete = bool(failed_pages) and all(
        item.get("manual_reviewed", False) or _has_whole_page_redaction(data, item["page_number"])
        for item in failed_pages
    )
    if not any(item["selected"] for item in data["findings"]) and not manual_review_is_complete:
        raise HTTPException(status_code=422, detail="Select at least one region to redact.")
    job.approved_revision = revision
    job.status = "approved"
    await db.commit()
    return _job_response(job, data["warnings"])


@router.post("/{job_id}/export", response_model=RedactionJobResponse)
@limiter.limit(settings.rate_limit_upload)
async def export_redacted_document(
    request: Request,
    job_id: str,
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> RedactionJobResponse:
    job = await _get_owned_job(db, job_id, authenticated.account.id)
    if job.status != "approved" or job.approved_revision != job.review_revision:
        raise HTTPException(status_code=409, detail="Approve the current review before export.")
    document = await db.get(Document, job.document_id)
    if document is None or document.owner_id != job.owner_id:
        raise HTTPException(status_code=404, detail="Source document not found.")
    source = Path(document.storage_path)
    if not source.is_file() or await asyncio.to_thread(_sha256, source) != job.source_sha256:
        raise HTTPException(
            status_code=409, detail="The source changed. Create a new redaction job."
        )
    data = load_job_data(job)
    selected_boxes: dict[int, list[tuple[float, float, float, float]]] = {}
    for finding in data["findings"]:
        if finding["selected"]:
            selected_boxes.setdefault(finding["page_number"], []).extend(
                tuple(box) for box in finding["boxes"]
            )
    claimed = await db.execute(
        update(RedactionJob)
        .where(
            RedactionJob.id == job.id,
            RedactionJob.owner_id == authenticated.account.id,
            RedactionJob.status == "approved",
            RedactionJob.review_revision == job.review_revision,
            RedactionJob.approved_revision == job.review_revision,
        )
        .values(status="exporting")
    )
    if claimed.rowcount != 1:
        await db.rollback()
        raise HTTPException(status_code=409, detail="The approved review changed before export.")
    await db.commit()
    output = Path(job.job_dir) / "redacted.pdf"
    try:
        await asyncio.to_thread(redact_to_image_pdf, source, output, selected_boxes)
    except Exception:
        await db.execute(
            update(RedactionJob)
            .where(RedactionJob.id == job.id, RedactionJob.status == "exporting")
            .values(status="approved")
        )
        await db.commit()
        raise
    await db.execute(
        update(RedactionJob)
        .where(
            RedactionJob.id == job.id,
            RedactionJob.status == "exporting",
            RedactionJob.review_revision == job.review_revision,
        )
        .values(status="exported")
    )
    await db.commit()
    await db.refresh(job)
    return _job_response(job, data["warnings"])


@router.get("/{job_id}/download")
async def download_redacted_document(
    job_id: str,
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> FileResponse:
    job = await _get_owned_job(db, job_id, authenticated.account.id)
    if job.status != "exported" or job.approved_revision != job.review_revision:
        raise HTTPException(status_code=409, detail="No approved export is available.")
    filename = "redacted-document.pdf"
    path = Path(job.job_dir) / "redacted.pdf"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Redacted export is unavailable.")
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=filename,
        headers={"Cache-Control": "no-store"},
    )


@router.post("/{job_id}/cancel", response_model=RedactionJobResponse)
async def cancel_redaction_job(
    job_id: str,
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> RedactionJobResponse:
    job = await _get_owned_job(db, job_id, authenticated.account.id)
    if job.status not in {"queued", "processing", "needs_clarification"}:
        raise HTTPException(status_code=409, detail="This redaction job cannot be cancelled.")
    job.status = "cancelled"
    job.lease_until = None
    await db.commit()
    return _job_response(job)


def _require_review_state(job: RedactionJob) -> None:
    if job.status not in {"review_ready", "approved", "exported"}:
        raise HTTPException(status_code=409, detail="Redaction results are not ready for review.")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

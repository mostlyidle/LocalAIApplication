"""Reviewable, account-scoped document redaction jobs."""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pymupdf
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse
from sqlalchemy import select, update

from app.api.middleware.rate_limiting import limiter
from app.config import settings
from app.dependencies import get_authenticated_session, get_db
from app.models.db_models import Document, RedactionJob
from app.models.redaction_schemas import (
    RedactionClarification,
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
    queue_redaction_job,
    save_job_data,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.services.auth import AuthenticatedSession

router = APIRouter(prefix="/redaction-jobs", tags=["Document Redaction"])


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


def _job_response(job: RedactionJob, warnings: list[str] | None = None) -> RedactionJobResponse:
    return RedactionJobResponse(
        id=job.id,
        document_id=job.document_id,
        status=job.status,
        page_count=job.page_count,
        pages_processed=job.pages_processed,
        review_revision=job.review_revision,
        approved_revision=job.approved_revision,
        clarification_question=job.clarification_question,
        error_message=job.error_message,
        warnings=warnings or [],
    )


def _review_payload(job: RedactionJob) -> tuple[list[RedactionFinding], list[str]]:
    data = load_job_data(job)
    return [RedactionFinding.model_validate(item) for item in data["findings"]], data["warnings"]


def _find_failed_page(data: dict[str, Any], page_number: int) -> dict[str, Any] | None:
    return next(
        (item for item in data.get("failed_pages", []) if item["page_number"] == page_number),
        None,
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
    failed_pages = data.get("failed_pages", [])
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
    """Retry extraction and detection for one page that failed in this job."""
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
    """Record the owner's manual inspection of a page extraction could not read."""
    job = await _get_owned_job(db, job_id, authenticated.account.id)
    document = await db.get(Document, job.document_id)
    if document is None or document.owner_id != job.owner_id:
        raise HTTPException(status_code=404, detail="Source document not found.")
    try:
        await asyncio.to_thread(_render_source_page, document.storage_path, payload.page_number)
    except IndexError as exc:
        raise HTTPException(status_code=404, detail="Page not found.") from exc
    except (OSError, RuntimeError, ValueError, pymupdf.FileDataError) as exc:
        raise HTTPException(
            status_code=409,
            detail="This page cannot be rendered. Retry processing before manual review.",
        ) from exc
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
    if any(not item.get("manual_reviewed", False) for item in data.get("failed_pages", [])):
        raise HTTPException(
            status_code=409,
            detail="Retry or manually inspect every failed page before approving this document.",
        )
    if not any(item["selected"] for item in data["findings"]):
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

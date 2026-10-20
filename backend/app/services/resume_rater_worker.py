"""Durable single-process queue for resume rubric and scoring work."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import structlog
from ollama import ResponseError
from sqlalchemy import exists, select, update

from app.api.middleware.error_handler import AppError
from app.models.db_models import (
    ResumeRaterAssessment,
    ResumeRaterCandidate,
    ResumeRaterRevision,
    ResumeRaterTask,
    ResumeRaterWorkspace,
)
from app.models.enums import DocumentFormat
from app.models.resume_rater_schemas import ResumeRubric
from app.services.resume_rater_agent import assess_resume, draft_resume_rubric

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)
LEASE_SECONDS = 900
POLL_SECONDS = 1


async def _claim_task(db: AsyncSession) -> str | None:
    """Claim one queued task using a conditional update safe against duplicate workers."""
    now = datetime.now(UTC).replace(tzinfo=None)
    row = await db.scalar(
        select(ResumeRaterTask.id)
        .where(ResumeRaterTask.status == "queued")
        .order_by(ResumeRaterTask.created_at, ResumeRaterTask.id)
        .limit(1)
    )
    if row is None:
        return None
    result = await db.execute(
        update(ResumeRaterTask)
        .where(ResumeRaterTask.id == row, ResumeRaterTask.status == "queued")
        .values(
            status="processing",
            attempts=ResumeRaterTask.attempts + 1,
            lease_until=now + timedelta(seconds=LEASE_SECONDS),
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        await db.rollback()
        return None
    await db.commit()
    return row


async def recover_interrupted_tasks(db: AsyncSession) -> int:
    """Requeue tasks left in progress by a stopped single-process app worker."""
    tasks = list(
        (
            await db.scalars(select(ResumeRaterTask).where(ResumeRaterTask.status == "processing"))
        ).all()
    )
    for task in tasks:
        task.status = "queued"
        task.lease_until = None
        if task.kind == "rubric":
            revision = await db.get(ResumeRaterRevision, task.revision_id)
            if revision is not None and revision.status == "rubric_processing":
                revision.status = "rubric_queued"
                revision.error_message = None
        elif task.assessment_id:
            assessment = await db.get(ResumeRaterAssessment, task.assessment_id)
            if assessment is not None and assessment.status == "processing":
                assessment.status = "queued"
                assessment.error_message = None
    if tasks:
        await db.commit()
    return len(tasks)


async def _fail_task(db: AsyncSession, task: ResumeRaterTask, error: Exception) -> None:
    """Publish a safe, retryable failure without storing model or resume content."""
    if isinstance(error, (ValueError, ConnectionError, TimeoutError)):
        message = str(error)[:500]
    elif isinstance(error, AppError):
        message = error.message[:500]
    elif isinstance(error, ResponseError) and error.status_code == 404:
        message = (
            "The configured local model is unavailable. Install it in Ollama or update "
            "RESUME_RATER_MODEL, then retry."
        )
    else:
        message = "Processing failed unexpectedly. Retry this item."
    failure_details = {
        "task_id": task.id,
        "kind": task.kind,
        "error_type": type(error).__name__,
    }
    if message == "Processing failed unexpectedly. Retry this item.":
        logger.error(
            "resume_rater_task_failed_unexpectedly",
            **failure_details,
            exc_info=(type(error), error, error.__traceback__),
        )
    else:
        logger.warning("resume_rater_task_failed", **failure_details)
    failed = await db.execute(
        update(ResumeRaterTask)
        .where(ResumeRaterTask.id == task.id, ResumeRaterTask.status == "processing")
        .values(status="failed", lease_until=None)
        .execution_options(synchronize_session=False)
    )
    if failed.rowcount != 1:
        await db.rollback()
        return
    if task.kind == "rubric":
        await db.execute(
            update(ResumeRaterRevision)
            .where(
                ResumeRaterRevision.id == task.revision_id,
                ResumeRaterRevision.status == "rubric_processing",
            )
            .values(status="needs_attention", error_message=message)
            .execution_options(synchronize_session=False)
        )
    elif task.assessment_id:
        await db.execute(
            update(ResumeRaterAssessment)
            .where(
                ResumeRaterAssessment.id == task.assessment_id,
                ResumeRaterAssessment.status == "processing",
            )
            .values(status="needs_attention", error_message=message)
            .execution_options(synchronize_session=False)
        )
    await db.commit()


async def _start_rubric_task(
    db: AsyncSession, task: ResumeRaterTask, revision: ResumeRaterRevision
) -> bool:
    """Mark a rubric as processing only while its task remains active."""
    started = await db.execute(
        update(ResumeRaterRevision)
        .where(
            ResumeRaterRevision.id == revision.id,
            exists(
                select(ResumeRaterTask.id).where(
                    ResumeRaterTask.id == task.id,
                    ResumeRaterTask.status == "processing",
                )
            ),
        )
        .values(status="rubric_processing")
        .execution_options(synchronize_session=False)
    )
    if started.rowcount != 1:
        await db.rollback()
        return False
    await db.commit()
    await db.refresh(revision)
    return revision.status == "rubric_processing"


async def _start_assessment_task(
    db: AsyncSession, task: ResumeRaterTask, assessment: ResumeRaterAssessment
) -> bool:
    """Mark an assessment as processing only while its task remains active."""
    started = await db.execute(
        update(ResumeRaterAssessment)
        .where(
            ResumeRaterAssessment.id == assessment.id,
            ResumeRaterAssessment.status == "queued",
            exists(
                select(ResumeRaterTask.id).where(
                    ResumeRaterTask.id == task.id,
                    ResumeRaterTask.status == "processing",
                )
            ),
        )
        .values(status="processing", error_message=None)
        .execution_options(synchronize_session=False)
    )
    if started.rowcount != 1:
        await db.rollback()
        return False
    await db.commit()
    await db.refresh(assessment)
    return assessment.status == "processing"


async def process_one_resume_rater_task(db: AsyncSession) -> bool:
    """Claim and execute one rubric or candidate assessment task."""
    task_id = await _claim_task(db)
    if task_id is None:
        return False
    task = await db.get(ResumeRaterTask, task_id)
    if task is None:
        return True
    revision = await db.get(ResumeRaterRevision, task.revision_id)
    workspace = await db.get(ResumeRaterWorkspace, task.workspace_id)
    if revision is None or workspace is None or revision.workspace_id != workspace.id:
        await _fail_task(db, task, ValueError("This assessment is no longer available."))
        return True

    try:
        if task.kind == "rubric":
            if not await _start_rubric_task(db, task, revision):
                return True
            rubric = await draft_resume_rubric(revision.job_posting)
            published = await db.execute(
                update(ResumeRaterTask)
                .where(ResumeRaterTask.id == task.id, ResumeRaterTask.status == "processing")
                .values(status="completed", lease_until=None)
                .execution_options(synchronize_session=False)
            )
            if published.rowcount == 1:
                revision.criteria_json = rubric.model_dump_json()
                revision.status = "needs_review"
                revision.error_message = None
                await db.commit()
            else:
                await db.rollback()
            return True

        if task.kind != "assessment" or task.assessment_id is None:
            raise ValueError("The queued task is invalid.")
        assessment = await db.get(ResumeRaterAssessment, task.assessment_id)
        candidate = (
            await db.get(ResumeRaterCandidate, assessment.candidate_id) if assessment else None
        )
        if assessment is None or candidate is None or candidate.workspace_id != workspace.id:
            raise ValueError("The candidate assessment is no longer available.")
        if revision.status != "approved" or assessment.revision_id != revision.id:
            raise ValueError("The approved rubric changed. Create a new assessment.")

        if not await _start_assessment_task(db, task, assessment):
            return True
        from app.services.document_parser import document_parser_service

        extension = Path(candidate.filename).suffix.lower().lstrip(".")
        file_format = DocumentFormat.from_extension(extension)
        parsed = await document_parser_service.parse(Path(candidate.resume_path), file_format)
        if not parsed.text.strip():
            raise ValueError("No readable resume text was found. Upload a text-based PDF or DOCX.")
        rubric = ResumeRubric.model_validate_json(revision.criteria_json or "{}")
        report, score = await assess_resume(revision.job_posting, parsed.text, rubric)
        published = await db.execute(
            update(ResumeRaterTask)
            .where(ResumeRaterTask.id == task.id, ResumeRaterTask.status == "processing")
            .values(status="completed", lease_until=None)
            .execution_options(synchronize_session=False)
        )
        if published.rowcount == 1:
            assessment.score = score
            assessment.result_json = report.model_dump_json()
            assessment.status = "completed"
            assessment.error_message = None
            assessment.completed_at = datetime.now(UTC).replace(tzinfo=None)
            await db.commit()
        else:
            await db.rollback()
        return True
    except asyncio.CancelledError:
        await db.rollback()
        task = await db.get(ResumeRaterTask, task_id)
        if task is not None and task.status == "processing":
            task.status = "queued"
            task.lease_until = None
            if task.kind == "rubric":
                revision = await db.get(ResumeRaterRevision, task.revision_id)
                if revision is not None:
                    revision.status = "rubric_queued"
            elif task.assessment_id:
                assessment = await db.get(ResumeRaterAssessment, task.assessment_id)
                if assessment is not None:
                    assessment.status = "queued"
            await db.commit()
        raise
    except Exception as exc:
        await db.rollback()
        task = await db.get(ResumeRaterTask, task_id)
        if task is not None and task.status == "processing":
            await _fail_task(db, task, exc)
        return True


async def run_resume_rater_worker(stop: asyncio.Event) -> None:
    """Poll the local database queue until application shutdown."""
    from app.services.database import get_app_session_factory

    factory = get_app_session_factory()
    async with factory() as db:
        await recover_interrupted_tasks(db)
    while not stop.is_set():
        async with factory() as db:
            processed = await process_one_resume_rater_task(db)
        if not processed:
            with suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=POLL_SECONDS)

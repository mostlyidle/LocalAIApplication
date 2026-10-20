"""Account-owned job workspaces and evidence-based resume assessments."""

from __future__ import annotations

import asyncio
import hashlib
import io
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: TC002

from app.api.middleware.rate_limiting import limiter
from app.config import settings
from app.dependencies import get_authenticated_session, get_db
from app.models.db_models import (
    ResumeRaterAssessment,
    ResumeRaterCandidate,
    ResumeRaterRevision,
    ResumeRaterTask,
    ResumeRaterWorkspace,
)
from app.models.resume_rater_schemas import (
    ResumeRaterAssessmentResponse,
    ResumeRaterCancelResponse,
    ResumeRaterCandidateNameUpdate,
    ResumeRaterCandidateResponse,
    ResumeRaterDeleteResponse,
    ResumeRaterRevisionCreate,
    ResumeRaterRevisionResponse,
    ResumeRaterRubricUpdate,
    ResumeRaterWorkspaceCreate,
    ResumeRaterWorkspaceDetail,
    ResumeRaterWorkspaceResponse,
    ResumeRubric,
    candidate_label,
)
from app.services.auth import AuthenticatedSession  # noqa: TC001

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/resume-rater/workspaces", tags=["Resume Rater"])
MAX_CANDIDATES = 25


async def _owned_workspace(
    db: AsyncSession, workspace_id: str, owner_id: str
) -> ResumeRaterWorkspace:
    workspace = await db.scalar(
        select(ResumeRaterWorkspace).where(
            ResumeRaterWorkspace.id == workspace_id,
            ResumeRaterWorkspace.owner_id == owner_id,
        )
    )
    if workspace is None:
        raise HTTPException(status_code=404, detail="Resume rating workspace not found.")
    return workspace


def _rubric_for(revision: ResumeRaterRevision) -> list[dict[str, object]] | None:
    rubric = _rubric_model_for(revision)
    if rubric is None:
        return None
    return rubric.model_dump(mode="json")["criteria"]


def _rubric_model_for(revision: ResumeRaterRevision) -> ResumeRubric | None:
    if not revision.criteria_json:
        return None
    try:
        return ResumeRubric.model_validate_json(revision.criteria_json)
    except ValueError:
        return None


def _revision_response(revision: ResumeRaterRevision) -> ResumeRaterRevisionResponse:
    return ResumeRaterRevisionResponse(
        id=revision.id,
        version=revision.version,
        job_posting=revision.job_posting,
        criteria=_rubric_for(revision),
        status=revision.status,
        error_message=revision.error_message,
        created_at=revision.created_at,
    )


def _assessment_response(
    assessment: ResumeRaterAssessment,
    revision_version: int,
    rank: int | None = None,
    rubric: ResumeRubric | None = None,
) -> ResumeRaterAssessmentResponse:
    result = None
    if assessment.result_json:
        try:
            from app.models.resume_rater_schemas import ResumeRaterReport

            result = ResumeRaterReport.model_validate_json(assessment.result_json)
        except ValueError:
            logger.error("resume_rater_saved_report_invalid", assessment_id=assessment.id)
    must_haves_not_met: list[str] = []
    if result is not None and rubric is not None:
        levels = {item.criterion_id: item.level for item in result.criterion_scores}
        must_haves_not_met = [
            criterion.id
            for criterion in rubric.criteria
            if criterion.must_have
            and levels.get(criterion.id) in {None, "not_demonstrated", "weak", "partial"}
        ]
    return ResumeRaterAssessmentResponse(
        id=assessment.id,
        revision_version=revision_version,
        status=assessment.status
        if result is not None or assessment.result_json is None
        else "needs_attention",
        score=assessment.score if result is not None else None,
        rank=rank,
        must_haves_not_met=must_haves_not_met,
        result=result,
        error_message=assessment.error_message,
        created_at=assessment.created_at,
        completed_at=assessment.completed_at,
    )


async def _workspace_detail(
    db: AsyncSession, workspace: ResumeRaterWorkspace
) -> ResumeRaterWorkspaceDetail:
    revisions = list(
        (
            await db.scalars(
                select(ResumeRaterRevision)
                .where(ResumeRaterRevision.workspace_id == workspace.id)
                .order_by(ResumeRaterRevision.version)
            )
        ).all()
    )
    candidates = list(
        (
            await db.scalars(
                select(ResumeRaterCandidate)
                .where(ResumeRaterCandidate.workspace_id == workspace.id)
                .order_by(ResumeRaterCandidate.created_at, ResumeRaterCandidate.id)
            )
        ).all()
    )
    candidate_ids = [candidate.id for candidate in candidates]
    assessments = (
        list(
            (
                await db.scalars(
                    select(ResumeRaterAssessment)
                    .where(ResumeRaterAssessment.candidate_id.in_(candidate_ids))
                    .order_by(ResumeRaterAssessment.created_at)
                )
            ).all()
        )
        if candidate_ids
        else []
    )
    versions = {revision.id: revision.version for revision in revisions}
    rubrics = {
        revision.id: rubric
        for revision in revisions
        if (rubric := _rubric_model_for(revision)) is not None
    }
    current_revision = next(
        (revision for revision in revisions if revision.version == workspace.current_revision), None
    )
    current_assessments = {
        item.candidate_id: item
        for item in assessments
        if current_revision and item.revision_id == current_revision.id
    }
    ranked = sorted(
        (
            item
            for item in current_assessments.values()
            if item.status == "completed" and item.score is not None
        ),
        key=lambda item: (-int(item.score or 0), item.created_at, item.id),
    )
    ranks: dict[str, int] = {}
    last_score: int | None = None
    last_rank = 0
    for position, assessment in enumerate(ranked, start=1):
        if assessment.score != last_score:
            last_score = assessment.score
            last_rank = position
        ranks[assessment.id] = last_rank

    candidate_responses = []
    for candidate in candidates:
        history = [
            _assessment_response(
                item,
                versions.get(item.revision_id, 1),
                ranks.get(item.id),
                rubrics.get(item.revision_id),
            )
            for item in assessments
            if item.candidate_id == candidate.id
        ]
        current = current_assessments.get(candidate.id)
        candidate_responses.append(
            ResumeRaterCandidateResponse(
                id=candidate.id,
                display_name=candidate.display_name,
                filename=candidate.filename,
                created_at=candidate.created_at,
                current_assessment=(
                    _assessment_response(
                        current,
                        workspace.current_revision,
                        ranks.get(current.id),
                        rubrics.get(current.revision_id),
                    )
                    if current
                    else None
                ),
                history=history,
            )
        )

    candidate_count = len(candidates)
    return ResumeRaterWorkspaceDetail(
        id=workspace.id,
        title=workspace.title,
        current_revision=workspace.current_revision,
        revision_status=current_revision.status if current_revision else "needs_attention",
        candidate_count=candidate_count,
        created_at=workspace.created_at,
        updated_at=workspace.updated_at,
        revisions=[_revision_response(revision) for revision in revisions],
        candidates=candidate_responses,
    )


async def _enqueue_assessment(
    db: AsyncSession, candidate: ResumeRaterCandidate, revision: ResumeRaterRevision
) -> ResumeRaterAssessment:
    assessment = ResumeRaterAssessment(
        workspace_id=candidate.workspace_id,
        candidate_id=candidate.id,
        revision_id=revision.id,
        status="queued",
    )
    db.add(assessment)
    await db.flush()
    db.add(
        ResumeRaterTask(
            workspace_id=candidate.workspace_id,
            revision_id=revision.id,
            assessment_id=assessment.id,
            kind="assessment",
            status="queued",
        )
    )
    return assessment


async def _validate_resume(file: UploadFile, aggregate_size: int) -> tuple[str, bytes, str]:
    filename = Path((file.filename or "resume").replace("\\", "/")).name
    extension = Path(filename).suffix.lower()
    if extension not in {".pdf", ".docx"}:
        raise HTTPException(status_code=415, detail=f"{filename}: upload a PDF or DOCX resume.")
    content = await file.read(settings.max_upload_size_bytes + 1)
    if len(content) > settings.max_upload_size_bytes:
        raise HTTPException(
            status_code=413, detail=f"{filename}: file exceeds the upload size limit."
        )
    if aggregate_size + len(content) > settings.max_upload_size_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"The batch exceeds the {settings.max_upload_size_mb} MB total upload limit.",
        )
    if extension == ".pdf":
        if not content.startswith(b"%PDF-"):
            raise HTTPException(status_code=415, detail=f"{filename}: file content is not a PDF.")
        mime_type = "application/pdf"
    else:
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                members = archive.infolist()
                uncompressed_size = sum(item.file_size for item in members)
                if (
                    "word/document.xml" not in archive.namelist()
                    or len(members) > 5_000
                    or uncompressed_size > min(settings.max_upload_size_bytes * 2, 100_000_000)
                    or any(
                        item.file_size > 0
                        and (item.compress_size == 0 or item.file_size / item.compress_size > 100)
                        for item in members
                    )
                ):
                    raise ValueError("Invalid or oversized DOCX archive.")
        except (OSError, zipfile.BadZipFile, ValueError) as exc:
            raise HTTPException(
                status_code=415, detail=f"{filename}: file content is not a valid DOCX."
            ) from exc
        mime_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if not content:
        raise HTTPException(status_code=400, detail=f"{filename}: file is empty.")
    return filename[:255], content, mime_type


async def _write_resume(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    await asyncio.to_thread(path.write_bytes, content)
    await asyncio.to_thread(path.chmod, 0o600)


@router.get("", response_model=list[ResumeRaterWorkspaceResponse])
async def list_workspaces(
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> list[ResumeRaterWorkspaceResponse]:
    """List only the authenticated account's hiring workspaces."""
    workspaces = list(
        (
            await db.scalars(
                select(ResumeRaterWorkspace)
                .where(ResumeRaterWorkspace.owner_id == authenticated.account.id)
                .order_by(ResumeRaterWorkspace.updated_at.desc())
            )
        ).all()
    )
    result = []
    for workspace in workspaces:
        revision = await db.scalar(
            select(ResumeRaterRevision).where(
                ResumeRaterRevision.workspace_id == workspace.id,
                ResumeRaterRevision.version == workspace.current_revision,
            )
        )
        count = await db.scalar(
            select(func.count())
            .select_from(ResumeRaterCandidate)
            .where(ResumeRaterCandidate.workspace_id == workspace.id)
        )
        result.append(
            ResumeRaterWorkspaceResponse(
                id=workspace.id,
                title=workspace.title,
                current_revision=workspace.current_revision,
                revision_status=revision.status if revision else "needs_attention",
                candidate_count=count or 0,
                created_at=workspace.created_at,
                updated_at=workspace.updated_at,
            )
        )
    return result


@router.post("", response_model=ResumeRaterWorkspaceDetail, status_code=201)
@limiter.limit(settings.rate_limit_llm)
async def create_workspace(
    request: Request,
    body: ResumeRaterWorkspaceCreate,
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> ResumeRaterWorkspaceDetail:
    """Create a job workspace and queue a suggested, reviewable rubric."""
    workspace = ResumeRaterWorkspace(owner_id=authenticated.account.id, title=body.title)
    db.add(workspace)
    await db.flush()
    revision = ResumeRaterRevision(
        workspace_id=workspace.id,
        version=1,
        job_posting=body.job_posting,
        status="rubric_queued",
    )
    db.add(revision)
    await db.flush()
    db.add(
        ResumeRaterTask(
            workspace_id=workspace.id,
            revision_id=revision.id,
            kind="rubric",
            status="queued",
        )
    )
    await db.commit()
    return await _workspace_detail(db, workspace)


@router.get("/{workspace_id}", response_model=ResumeRaterWorkspaceDetail)
async def get_workspace(
    workspace_id: str,
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> ResumeRaterWorkspaceDetail:
    """Return one owned workspace, its rubric history and assessment reports."""
    workspace = await _owned_workspace(db, workspace_id, authenticated.account.id)
    return await _workspace_detail(db, workspace)


@router.post(
    "/{workspace_id}/revisions", response_model=ResumeRaterRevisionResponse, status_code=201
)
@limiter.limit(settings.rate_limit_llm)
async def create_revision(
    workspace_id: str,
    request: Request,
    body: ResumeRaterRevisionCreate,
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> ResumeRaterRevisionResponse:
    """Save a changed posting as a new version and draft its rubric."""
    owner_id = authenticated.account.id
    workspace = await _owned_workspace(db, workspace_id, owner_id)
    result = await db.execute(
        update(ResumeRaterWorkspace)
        .where(ResumeRaterWorkspace.id == workspace_id, ResumeRaterWorkspace.owner_id == owner_id)
        .values(current_revision=ResumeRaterWorkspace.current_revision + 1)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        await db.rollback()
        raise HTTPException(status_code=404, detail="Resume rating workspace not found.")
    await db.refresh(workspace)
    revision = ResumeRaterRevision(
        workspace_id=workspace.id,
        version=workspace.current_revision,
        job_posting=body.job_posting,
        status="rubric_queued",
    )
    db.add(revision)
    await db.flush()
    db.add(
        ResumeRaterTask(
            workspace_id=workspace.id, revision_id=revision.id, kind="rubric", status="queued"
        )
    )
    await db.commit()
    return _revision_response(revision)


@router.put(
    "/{workspace_id}/revisions/{version}/rubric",
    response_model=ResumeRaterRevisionResponse,
    status_code=201,
)
async def update_rubric(
    workspace_id: str,
    version: int,
    body: ResumeRaterRubricUpdate,
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> ResumeRaterRevisionResponse:
    """Save manager-edited criteria as a new, reviewable rubric version."""
    workspace = await _owned_workspace(db, workspace_id, authenticated.account.id)
    if version != workspace.current_revision:
        raise HTTPException(
            status_code=409, detail="Refresh the workspace before editing its rubric."
        )
    prior = await db.scalar(
        select(ResumeRaterRevision).where(
            ResumeRaterRevision.workspace_id == workspace.id,
            ResumeRaterRevision.version == version,
        )
    )
    if prior is None or prior.status not in {"needs_review", "approved"}:
        raise HTTPException(
            status_code=409, detail="Wait for the suggested rubric before editing it."
        )
    result = await db.execute(
        update(ResumeRaterWorkspace)
        .where(
            ResumeRaterWorkspace.id == workspace.id,
            ResumeRaterWorkspace.owner_id == authenticated.account.id,
            ResumeRaterWorkspace.current_revision == version,
        )
        .values(current_revision=ResumeRaterWorkspace.current_revision + 1)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        await db.rollback()
        raise HTTPException(
            status_code=409, detail="Refresh the workspace before editing its rubric."
        )
    await db.refresh(workspace)
    revision = ResumeRaterRevision(
        workspace_id=workspace.id,
        version=workspace.current_revision,
        job_posting=prior.job_posting,
        criteria_json=body.model_dump_json(),
        status="needs_review",
    )
    db.add(revision)
    await db.commit()
    return _revision_response(revision)


@router.post(
    "/{workspace_id}/revisions/{version}/approve", response_model=ResumeRaterRevisionResponse
)
@limiter.limit(settings.rate_limit_llm)
async def approve_rubric(
    workspace_id: str,
    version: int,
    request: Request,
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> ResumeRaterRevisionResponse:
    """Approve a complete rubric and queue this version for every candidate."""
    workspace = await _owned_workspace(db, workspace_id, authenticated.account.id)
    revision = await db.scalar(
        select(ResumeRaterRevision).where(
            ResumeRaterRevision.workspace_id == workspace.id,
            ResumeRaterRevision.version == version,
        )
    )
    if revision is None:
        raise HTTPException(status_code=404, detail="Rubric revision not found.")
    if revision.version != workspace.current_revision:
        raise HTTPException(status_code=409, detail="Approve the current rubric revision.")
    if revision.status != "needs_review" or not revision.criteria_json:
        raise HTTPException(status_code=409, detail="The rubric must be reviewed before approval.")
    try:
        ResumeRubric.model_validate_json(revision.criteria_json)
    except ValueError as exc:
        raise HTTPException(
            status_code=409, detail="The saved rubric is invalid; edit it and retry."
        ) from exc

    revision.status = "approved"
    candidates = list(
        (
            await db.scalars(
                select(ResumeRaterCandidate).where(
                    ResumeRaterCandidate.workspace_id == workspace.id
                )
            )
        ).all()
    )
    for candidate in candidates:
        await _enqueue_assessment(db, candidate, revision)
    await db.commit()
    return _revision_response(revision)


@router.post(
    "/{workspace_id}/revisions/{version}/retry", response_model=ResumeRaterRevisionResponse
)
@limiter.limit(settings.rate_limit_llm)
async def retry_rubric(
    workspace_id: str,
    version: int,
    request: Request,
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> ResumeRaterRevisionResponse:
    """Requeue local rubric drafting after a failed or cancelled attempt."""
    workspace = await _owned_workspace(db, workspace_id, authenticated.account.id)
    revision = await db.scalar(
        select(ResumeRaterRevision).where(
            ResumeRaterRevision.workspace_id == workspace.id,
            ResumeRaterRevision.version == version,
        )
    )
    if revision is None:
        raise HTTPException(status_code=404, detail="Rubric revision not found.")
    if revision.version != workspace.current_revision:
        raise HTTPException(status_code=409, detail="Retry the current rubric revision.")
    if revision.status not in {"needs_attention", "cancelled"}:
        raise HTTPException(status_code=409, detail="Only a failed rubric can be retried.")
    task = await db.scalar(
        select(ResumeRaterTask)
        .where(ResumeRaterTask.revision_id == revision.id, ResumeRaterTask.kind == "rubric")
        .order_by(ResumeRaterTask.created_at.desc())
    )
    if task is None or task.status not in {"failed", "cancelled"}:
        raise HTTPException(status_code=409, detail="This rubric cannot be retried yet.")
    task.status = "queued"
    task.lease_until = None
    revision.status = "rubric_queued"
    revision.error_message = None
    await db.commit()
    return _revision_response(revision)


@router.post("/{workspace_id}/revisions/{version}/cancel", response_model=ResumeRaterCancelResponse)
async def cancel_rubric(
    workspace_id: str,
    version: int,
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> ResumeRaterCancelResponse:
    """Stop queued rubric work and prevent an in-flight model result from being published."""
    workspace = await _owned_workspace(db, workspace_id, authenticated.account.id)
    revision = await db.scalar(
        select(ResumeRaterRevision).where(
            ResumeRaterRevision.workspace_id == workspace.id,
            ResumeRaterRevision.version == version,
        )
    )
    if revision is None:
        raise HTTPException(status_code=404, detail="Rubric revision not found.")
    if revision.version != workspace.current_revision:
        raise HTTPException(status_code=409, detail="Cancel the current rubric revision.")
    if revision.status not in {"rubric_queued", "rubric_processing"}:
        raise HTTPException(status_code=409, detail="This rubric has no cancellable work.")
    result = await db.execute(
        update(ResumeRaterTask)
        .where(
            ResumeRaterTask.revision_id == revision.id,
            ResumeRaterTask.kind == "rubric",
            ResumeRaterTask.status.in_({"queued", "processing"}),
        )
        .values(status="cancelled", lease_until=None)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        await db.rollback()
        raise HTTPException(status_code=409, detail="This rubric can no longer be cancelled.")
    revision.status = "cancelled"
    revision.error_message = None
    await db.commit()
    return ResumeRaterCancelResponse(status="cancelled")


@router.post(
    "/{workspace_id}/candidates", response_model=ResumeRaterWorkspaceDetail, status_code=201
)
@limiter.limit(settings.rate_limit_upload)
async def add_candidates(
    workspace_id: str,
    request: Request,
    files: Annotated[list[UploadFile], File()],
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> ResumeRaterWorkspaceDetail:
    """Add one or more private PDF/DOCX resumes to an approved job workspace."""
    if not files or len(files) > MAX_CANDIDATES:
        raise HTTPException(status_code=422, detail="Upload between 1 and 25 resumes per batch.")
    workspace = await _owned_workspace(db, workspace_id, authenticated.account.id)
    # Updating the workspace row holds a write lock through this transaction. That serializes
    # concurrent uploads before both check the 25-candidate limit and insert their batch.
    await db.execute(
        update(ResumeRaterWorkspace)
        .where(ResumeRaterWorkspace.id == workspace.id)
        .values(updated_at=datetime.now(UTC).replace(tzinfo=None))
        .execution_options(synchronize_session=False)
    )
    await db.refresh(workspace)
    revision = await db.scalar(
        select(ResumeRaterRevision).where(
            ResumeRaterRevision.workspace_id == workspace.id,
            ResumeRaterRevision.version == workspace.current_revision,
        )
    )
    if revision is None or revision.status != "approved":
        await db.rollback()
        raise HTTPException(
            status_code=409, detail="Approve the job rubric before adding candidates."
        )
    count = await db.scalar(
        select(func.count())
        .select_from(ResumeRaterCandidate)
        .where(ResumeRaterCandidate.workspace_id == workspace.id)
    )
    if (count or 0) + len(files) > MAX_CANDIDATES:
        await db.rollback()
        raise HTTPException(
            status_code=409, detail="A job workspace can contain at most 25 candidates."
        )

    uploads: list[tuple[str, bytes, str, str]] = []
    total_size = 0
    for file in files:
        filename, content, _mime_type = await _validate_resume(file, total_size)
        total_size += len(content)
        digest = hashlib.sha256(content).hexdigest()
        uploads.append((filename, content, digest, candidate_label(filename)))
    digests = [item[2] for item in uploads]
    if len(set(digests)) != len(digests):
        await db.rollback()
        raise HTTPException(status_code=409, detail="This batch contains a duplicate resume file.")
    existing_digests = set(
        (
            await db.scalars(
                select(ResumeRaterCandidate.content_sha256).where(
                    ResumeRaterCandidate.workspace_id == workspace.id,
                    ResumeRaterCandidate.content_sha256.in_(digests),
                )
            )
        ).all()
    )
    if existing_digests:
        await db.rollback()
        raise HTTPException(
            status_code=409, detail="This workspace already contains a duplicate resume file."
        )

    new_paths: list[Path] = []
    try:
        for filename, content, digest, display_name in uploads:
            candidate_id = str(uuid.uuid4())
            path = (
                settings.upload_path
                / "resume-rater"
                / authenticated.account.id
                / workspace.id
                / f"{candidate_id}{Path(filename).suffix.lower()}"
            )
            await _write_resume(path, content)
            new_paths.append(path)
            candidate = ResumeRaterCandidate(
                id=candidate_id,
                workspace_id=workspace.id,
                display_name=display_name,
                filename=filename,
                resume_path=str(path),
                content_sha256=digest,
            )
            db.add(candidate)
            await db.flush()
            await _enqueue_assessment(db, candidate, revision)
        await db.commit()
    except Exception:
        await db.rollback()
        for path in new_paths:
            await asyncio.to_thread(path.unlink, missing_ok=True)
        raise
    return await _workspace_detail(db, workspace)


@router.patch(
    "/{workspace_id}/candidates/{candidate_id}", response_model=ResumeRaterCandidateResponse
)
async def rename_candidate(
    workspace_id: str,
    candidate_id: str,
    body: ResumeRaterCandidateNameUpdate,
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008, TC002
) -> ResumeRaterCandidateResponse:
    """Correct the manager-visible candidate label without changing resume evidence."""
    await _owned_workspace(db, workspace_id, authenticated.account.id)
    candidate = await db.scalar(
        select(ResumeRaterCandidate).where(
            ResumeRaterCandidate.id == candidate_id,
            ResumeRaterCandidate.workspace_id == workspace_id,
        )
    )
    if candidate is None:
        raise HTTPException(status_code=404, detail="Candidate not found.")
    candidate.display_name = body.display_name
    await db.commit()
    workspace = await _owned_workspace(db, workspace_id, authenticated.account.id)
    detail = await _workspace_detail(db, workspace)
    return next(item for item in detail.candidates if item.id == candidate_id)


@router.post(
    "/{workspace_id}/candidates/{candidate_id}/retry",
    response_model=ResumeRaterAssessmentResponse,
    status_code=202,
)
@limiter.limit(settings.rate_limit_llm)
async def retry_candidate(
    workspace_id: str,
    candidate_id: str,
    request: Request,
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> ResumeRaterAssessmentResponse:
    """Retry one failed candidate against the currently approved rubric."""
    workspace = await _owned_workspace(db, workspace_id, authenticated.account.id)
    revision = await db.scalar(
        select(ResumeRaterRevision).where(
            ResumeRaterRevision.workspace_id == workspace.id,
            ResumeRaterRevision.version == workspace.current_revision,
            ResumeRaterRevision.status == "approved",
        )
    )
    if revision is None:
        raise HTTPException(status_code=409, detail="Approve the current rubric before retrying.")
    candidate = await db.scalar(
        select(ResumeRaterCandidate).where(
            ResumeRaterCandidate.id == candidate_id,
            ResumeRaterCandidate.workspace_id == workspace.id,
        )
    )
    if candidate is None:
        raise HTTPException(status_code=404, detail="Candidate not found.")
    assessment = await db.scalar(
        select(ResumeRaterAssessment).where(
            ResumeRaterAssessment.candidate_id == candidate.id,
            ResumeRaterAssessment.revision_id == revision.id,
        )
    )
    if assessment is None or assessment.status != "needs_attention":
        raise HTTPException(
            status_code=409, detail="Only an assessment needing attention can be retried."
        )
    task = await db.scalar(
        select(ResumeRaterTask)
        .where(ResumeRaterTask.assessment_id == assessment.id)
        .order_by(ResumeRaterTask.created_at.desc())
    )
    if task is None or task.status != "failed":
        raise HTTPException(status_code=409, detail="This assessment cannot be retried yet.")
    task.status = "queued"
    task.lease_until = None
    assessment.status = "queued"
    assessment.error_message = None
    assessment.completed_at = None
    await db.commit()
    return _assessment_response(assessment, revision.version)


@router.post(
    "/{workspace_id}/candidates/{candidate_id}/cancel", response_model=ResumeRaterCancelResponse
)
async def cancel_candidate(
    workspace_id: str,
    candidate_id: str,
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> ResumeRaterCancelResponse:
    """Cancel pending work for one candidate; completed reports remain available."""
    workspace = await _owned_workspace(db, workspace_id, authenticated.account.id)
    candidate = await db.scalar(
        select(ResumeRaterCandidate).where(
            ResumeRaterCandidate.id == candidate_id,
            ResumeRaterCandidate.workspace_id == workspace.id,
        )
    )
    if candidate is None:
        raise HTTPException(status_code=404, detail="Candidate not found.")
    revision = await db.scalar(
        select(ResumeRaterRevision).where(
            ResumeRaterRevision.workspace_id == workspace.id,
            ResumeRaterRevision.version == workspace.current_revision,
        )
    )
    assessment = await db.scalar(
        select(ResumeRaterAssessment).where(
            ResumeRaterAssessment.candidate_id == candidate.id,
            ResumeRaterAssessment.revision_id == (revision.id if revision else ""),
        )
    )
    if assessment is None or assessment.status not in {"queued", "processing"}:
        raise HTTPException(status_code=409, detail="This candidate has no cancellable assessment.")
    cancelled_task = await db.execute(
        update(ResumeRaterTask)
        .where(
            ResumeRaterTask.assessment_id == assessment.id,
            ResumeRaterTask.status.in_({"queued", "processing"}),
        )
        .values(status="cancelled", lease_until=None)
        .execution_options(synchronize_session=False)
    )
    if cancelled_task.rowcount != 1:
        await db.rollback()
        raise HTTPException(status_code=409, detail="This candidate can no longer be cancelled.")
    cancelled_assessment = await db.execute(
        update(ResumeRaterAssessment)
        .where(
            ResumeRaterAssessment.id == assessment.id,
            ResumeRaterAssessment.status.in_({"queued", "processing"}),
        )
        .values(status="cancelled", error_message=None)
        .execution_options(synchronize_session=False)
    )
    if cancelled_assessment.rowcount != 1:
        await db.rollback()
        raise HTTPException(status_code=409, detail="This candidate can no longer be cancelled.")
    await db.commit()
    return ResumeRaterCancelResponse(status="cancelled")


@router.delete(
    "/{workspace_id}/candidates/{candidate_id}", response_model=ResumeRaterDeleteResponse
)
async def delete_candidate(
    workspace_id: str,
    candidate_id: str,
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008, TC002
) -> ResumeRaterDeleteResponse:
    """Delete a candidate, all versions of their reports, and the private resume file."""
    workspace = await _owned_workspace(db, workspace_id, authenticated.account.id)
    candidate = await db.scalar(
        select(ResumeRaterCandidate).where(
            ResumeRaterCandidate.id == candidate_id,
            ResumeRaterCandidate.workspace_id == workspace.id,
        )
    )
    if candidate is None:
        raise HTTPException(status_code=404, detail="Candidate not found.")
    file_path = Path(candidate.resume_path)
    assessments = list(
        (
            await db.scalars(
                select(ResumeRaterAssessment).where(
                    ResumeRaterAssessment.candidate_id == candidate.id
                )
            )
        ).all()
    )
    for assessment in assessments:
        tasks = list(
            (
                await db.scalars(
                    select(ResumeRaterTask).where(ResumeRaterTask.assessment_id == assessment.id)
                )
            ).all()
        )
        for task in tasks:
            await db.delete(task)
        await db.delete(assessment)
    await db.delete(candidate)
    await db.commit()
    await asyncio.to_thread(file_path.unlink, missing_ok=True)
    return ResumeRaterDeleteResponse(status="deleted")


@router.delete("/{workspace_id}", response_model=ResumeRaterDeleteResponse)
async def delete_workspace(
    workspace_id: str,
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008, TC002
) -> ResumeRaterDeleteResponse:
    """Delete an owned workspace, all saved reports, and its uploaded resumes."""
    workspace = await _owned_workspace(db, workspace_id, authenticated.account.id)
    files = list(
        (
            await db.scalars(
                select(ResumeRaterCandidate.resume_path).where(
                    ResumeRaterCandidate.workspace_id == workspace.id
                )
            )
        ).all()
    )
    candidates = list(
        (
            await db.scalars(
                select(ResumeRaterCandidate).where(
                    ResumeRaterCandidate.workspace_id == workspace.id
                )
            )
        ).all()
    )
    assessments = list(
        (
            await db.scalars(
                select(ResumeRaterAssessment).where(
                    ResumeRaterAssessment.workspace_id == workspace.id
                )
            )
        ).all()
    )
    tasks = list(
        (
            await db.scalars(
                select(ResumeRaterTask).where(ResumeRaterTask.workspace_id == workspace.id)
            )
        ).all()
    )
    revisions = list(
        (
            await db.scalars(
                select(ResumeRaterRevision).where(ResumeRaterRevision.workspace_id == workspace.id)
            )
        ).all()
    )
    for row in [*tasks, *assessments, *candidates, *revisions, workspace]:
        await db.delete(row)
    await db.commit()
    for filename in files:
        await asyncio.to_thread(Path(filename).unlink, missing_ok=True)
    return ResumeRaterDeleteResponse(status="deleted")

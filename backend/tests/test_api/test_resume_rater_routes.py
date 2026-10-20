"""Ownership, rubric approval, upload, retry and deletion gates."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import select

from app.models.db_models import (
    Account,
    AccountSession,
    ResumeRaterAssessment,
    ResumeRaterCandidate,
    ResumeRaterRevision,
    ResumeRaterTask,
)
from app.models.resume_rater_schemas import ResumeRubric
from app.services.auth import AuthenticatedSession

if TYPE_CHECKING:
    from httpx import AsyncClient
    from pytest import MonkeyPatch
    from sqlalchemy.ext.asyncio import AsyncSession


def _principal(account: Account) -> AuthenticatedSession:
    return AuthenticatedSession(
        account=account,
        session=AccountSession(
            id=str(uuid.uuid4()),
            account_id=account.id,
            token_hash="0" * 64,
            csrf_token="test-csrf-token",
            expires_at=datetime.now(UTC),
        ),
    )


def _valid_rubric() -> dict[str, object]:
    return {
        "criteria": [
            {
                "id": "experience",
                "label": "Experience",
                "description": "Relevant experience",
                "weight": 50,
            },
            {"id": "skills", "label": "Skills", "description": "Required skills", "weight": 30},
            {
                "id": "leadership",
                "label": "Leadership",
                "description": "Team leadership",
                "weight": 20,
                "must_have": True,
            },
        ]
    }


async def _mark_rubric_ready(db_session: AsyncSession, workspace_id: str) -> ResumeRaterRevision:
    revision = await db_session.scalar(
        select(ResumeRaterRevision).where(ResumeRaterRevision.workspace_id == workspace_id)
    )
    assert revision is not None
    revision.criteria_json = ResumeRubric.model_validate(_valid_rubric()).model_dump_json()
    revision.status = "needs_review"
    task = await db_session.scalar(
        select(ResumeRaterTask).where(
            ResumeRaterTask.workspace_id == workspace_id, ResumeRaterTask.kind == "rubric"
        )
    )
    assert task is not None
    task.status = "completed"
    await db_session.commit()
    return revision


async def test_workspace_requires_approval_and_preserves_rubric_versions(
    client: AsyncClient,
    db_session: AsyncSession,
    authenticated_test_session: AuthenticatedSession,
) -> None:
    from app.dependencies import get_authenticated_session

    client._transport.app.dependency_overrides[get_authenticated_session] = lambda: (
        authenticated_test_session
    )
    created = await client.post(
        "/api/v1/resume-rater/workspaces",
        json={"title": "Backend Engineer", "job_posting": "Build reliable systems. " * 6},
    )
    assert created.status_code == 201
    workspace_id = created.json()["id"]
    assert created.json()["revision_status"] == "rubric_queued"

    blocked = await client.post(
        f"/api/v1/resume-rater/workspaces/{workspace_id}/candidates",
        files={"files": ("resume.pdf", b"%PDF-1.7 sample", "application/pdf")},
    )
    assert blocked.status_code == 409

    await _mark_rubric_ready(db_session, workspace_id)

    edited = await client.put(
        f"/api/v1/resume-rater/workspaces/{workspace_id}/revisions/1/rubric",
        json=_valid_rubric(),
    )
    assert edited.status_code == 201
    assert edited.json()["version"] == 2
    assert edited.json()["status"] == "needs_review"

    approved = await client.post(
        f"/api/v1/resume-rater/workspaces/{workspace_id}/revisions/2/approve"
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"


async def test_rubric_work_can_be_cancelled_and_retried(
    client: AsyncClient,
    authenticated_test_session: AuthenticatedSession,
) -> None:
    from app.dependencies import get_authenticated_session

    client._transport.app.dependency_overrides[get_authenticated_session] = lambda: (
        authenticated_test_session
    )
    created = await client.post(
        "/api/v1/resume-rater/workspaces",
        json={"title": "Backend Engineer", "job_posting": "Build reliable systems. " * 6},
    )
    workspace_id = created.json()["id"]

    cancelled = await client.post(
        f"/api/v1/resume-rater/workspaces/{workspace_id}/revisions/1/cancel"
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"

    retried = await client.post(f"/api/v1/resume-rater/workspaces/{workspace_id}/revisions/1/retry")
    assert retried.status_code == 200
    assert retried.json()["status"] == "rubric_queued"


async def test_candidate_work_can_be_cancelled_once(
    client: AsyncClient,
    authenticated_test_session: AuthenticatedSession,
    db_session: AsyncSession,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    import app.api.routes.resume_rater as resume_routes
    from app.dependencies import get_authenticated_session

    monkeypatch.setattr(resume_routes.settings, "upload_dir", str(tmp_path / "uploads"))
    client._transport.app.dependency_overrides[get_authenticated_session] = lambda: (
        authenticated_test_session
    )
    created = await client.post(
        "/api/v1/resume-rater/workspaces",
        json={"title": "Backend Engineer", "job_posting": "Build reliable systems. " * 6},
    )
    workspace_id = created.json()["id"]
    await _mark_rubric_ready(db_session, workspace_id)
    assert (
        await client.post(f"/api/v1/resume-rater/workspaces/{workspace_id}/revisions/1/approve")
    ).status_code == 200
    uploaded = await client.post(
        f"/api/v1/resume-rater/workspaces/{workspace_id}/candidates",
        files={"files": ("Candidate.pdf", b"%PDF-1.7 candidate", "application/pdf")},
    )
    candidate_id = uploaded.json()["candidates"][0]["id"]
    assessment = await db_session.scalar(
        select(ResumeRaterAssessment).where(ResumeRaterAssessment.candidate_id == candidate_id)
    )
    assert assessment is not None
    task = await db_session.scalar(
        select(ResumeRaterTask).where(ResumeRaterTask.assessment_id == assessment.id)
    )
    assert task is not None

    cancelled = await client.post(
        f"/api/v1/resume-rater/workspaces/{workspace_id}/candidates/{candidate_id}/cancel"
    )
    assert cancelled.status_code == 200
    await db_session.refresh(assessment)
    await db_session.refresh(task)
    assert assessment.status == "cancelled"
    assert task.status == "cancelled"
    assert (
        await client.post(
            f"/api/v1/resume-rater/workspaces/{workspace_id}/candidates/{candidate_id}/cancel"
        )
    ).status_code == 409


async def test_resume_upload_rejects_duplicate_files_and_other_accounts_cannot_read_workspace(
    client: AsyncClient,
    authenticated_test_session: AuthenticatedSession,
    db_session: AsyncSession,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    import app.api.routes.resume_rater as resume_routes
    from app.dependencies import get_authenticated_session

    monkeypatch.setattr(resume_routes.settings, "upload_dir", str(tmp_path / "uploads"))
    client._transport.app.dependency_overrides[get_authenticated_session] = lambda: (
        authenticated_test_session
    )
    workspace = await client.post(
        "/api/v1/resume-rater/workspaces",
        json={"title": "Backend Engineer", "job_posting": "Build reliable systems. " * 6},
    )
    workspace_id = workspace.json()["id"]
    await _mark_rubric_ready(db_session, workspace_id)
    assert (
        await client.post(f"/api/v1/resume-rater/workspaces/{workspace_id}/revisions/1/approve")
    ).status_code == 200

    upload = await client.post(
        f"/api/v1/resume-rater/workspaces/{workspace_id}/candidates",
        files=[
            ("files", ("Candidate A.pdf", b"%PDF-1.7 candidate A", "application/pdf")),
            ("files", ("Candidate B.pdf", b"%PDF-1.7 candidate B", "application/pdf")),
        ],
    )
    assert upload.status_code == 201
    assert upload.json()["candidate_count"] == 2
    assert {
        candidate["current_assessment"]["status"] for candidate in upload.json()["candidates"]
    } == {"queued"}

    first_candidate_id = upload.json()["candidates"][0]["id"]
    assessment = await db_session.scalar(
        select(ResumeRaterAssessment).where(
            ResumeRaterAssessment.candidate_id == first_candidate_id
        )
    )
    assert assessment is not None
    assessment.status = "completed"
    assessment.score = 83
    assessment.result_json = json.dumps(
        {
            "summary": "Experience is strong; leadership evidence is partial.",
            "criterion_scores": [
                {
                    "criterion_id": "experience",
                    "level": "fully_meets",
                    "explanation": "Direct evidence.",
                    "evidence_quotes": ["Built services."],
                },
                {
                    "criterion_id": "skills",
                    "level": "substantial",
                    "explanation": "Relevant tools are listed.",
                    "evidence_quotes": ["Used Python and SQL."],
                },
                {
                    "criterion_id": "leadership",
                    "level": "partial",
                    "explanation": "Mentoring is mentioned.",
                    "evidence_quotes": ["Mentored two engineers."],
                },
            ],
            "strengths": [],
            "gaps": [],
            "interview_questions": [],
            "resume_suggestions": [],
        }
    )
    await db_session.commit()
    detail = await client.get(f"/api/v1/resume-rater/workspaces/{workspace_id}")
    first_candidate = next(
        item for item in detail.json()["candidates"] if item["id"] == first_candidate_id
    )
    assert first_candidate["current_assessment"]["must_haves_not_met"] == ["leadership"]

    duplicate = await client.post(
        f"/api/v1/resume-rater/workspaces/{workspace_id}/candidates",
        files={"files": ("Copy.pdf", b"%PDF-1.7 candidate A", "application/pdf")},
    )
    assert duplicate.status_code == 409

    other = Account(
        id="resume-rater-other",
        username="resume-rater-other",
        display_name="Other",
        password_hash="!test!",
    )
    db_session.add(other)
    await db_session.commit()
    client._transport.app.dependency_overrides[get_authenticated_session] = lambda: _principal(
        other
    )
    assert (await client.get(f"/api/v1/resume-rater/workspaces/{workspace_id}")).status_code == 404


async def test_deleting_candidate_removes_private_file_reports_and_queue_items(
    client: AsyncClient,
    authenticated_test_session: AuthenticatedSession,
    db_session: AsyncSession,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    import app.api.routes.resume_rater as resume_routes
    from app.dependencies import get_authenticated_session

    monkeypatch.setattr(resume_routes.settings, "upload_dir", str(tmp_path / "uploads"))
    client._transport.app.dependency_overrides[get_authenticated_session] = lambda: (
        authenticated_test_session
    )
    workspace_response = await client.post(
        "/api/v1/resume-rater/workspaces",
        json={"title": "Backend Engineer", "job_posting": "Build reliable systems. " * 6},
    )
    workspace_id = workspace_response.json()["id"]
    await _mark_rubric_ready(db_session, workspace_id)
    await client.post(f"/api/v1/resume-rater/workspaces/{workspace_id}/revisions/1/approve")
    uploaded = await client.post(
        f"/api/v1/resume-rater/workspaces/{workspace_id}/candidates",
        files={"files": ("Candidate.pdf", b"%PDF-1.7 candidate", "application/pdf")},
    )
    candidate_id = uploaded.json()["candidates"][0]["id"]
    candidate = await db_session.get(ResumeRaterCandidate, candidate_id)
    assert candidate is not None
    path = Path(candidate.resume_path)
    assert path.exists()

    deleted = await client.delete(
        f"/api/v1/resume-rater/workspaces/{workspace_id}/candidates/{candidate_id}"
    )
    assert deleted.status_code == 200
    assert deleted.json()["status"] == "deleted"
    assert not path.exists()
    assert (
        await db_session.scalar(
            select(ResumeRaterAssessment.id).where(
                ResumeRaterAssessment.candidate_id == candidate_id
            )
        )
        is None
    )
    assert (
        await db_session.scalar(
            select(ResumeRaterTask.id).where(
                ResumeRaterTask.workspace_id == workspace_id,
                ResumeRaterTask.assessment_id.is_not(None),
            )
        )
        is None
    )

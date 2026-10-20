"""Durable work, restart recovery, and unreadable resume handling."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

from app.models.db_models import (
    ResumeRaterAssessment,
    ResumeRaterCandidate,
    ResumeRaterRevision,
    ResumeRaterTask,
    ResumeRaterWorkspace,
)
from app.models.resume_rater_schemas import ResumeRaterReport, ResumeRubric
from app.services.resume_rater_worker import (
    _fail_task,
    process_one_resume_rater_task,
    recover_interrupted_tasks,
)

if TYPE_CHECKING:
    from pathlib import Path

    from pytest import MonkeyPatch
    from sqlalchemy.ext.asyncio import AsyncSession


def _report() -> ResumeRaterReport:
    criteria = [
        {
            "id": "experience",
            "label": "Experience",
            "description": "Relevant experience",
            "weight": 60,
        },
        {"id": "skills", "label": "Skills", "description": "Required skills", "weight": 40},
        {
            "id": "writing",
            "label": "Writing",
            "description": "Clear written communication",
            "weight": 1,
        },
    ]
    criteria[1]["weight"] = 39
    return ResumeRaterReport(
        summary="Evidence was found.",
        criterion_scores=[
            {
                "criterion_id": "experience",
                "level": "fully_meets",
                "explanation": "Direct experience.",
                "evidence_quotes": ["Built services for eight years."],
            },
            {
                "criterion_id": "skills",
                "level": "substantial",
                "explanation": "Relevant skill evidence.",
                "evidence_quotes": ["Used Python and SQL."],
            },
            {
                "criterion_id": "writing",
                "level": "not_demonstrated",
                "explanation": "No example found.",
                "evidence_quotes": [],
            },
        ],
    )


async def test_worker_persists_report_and_calculated_score(
    db_session: AsyncSession, tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    import app.services.document_parser as parser_module
    import app.services.resume_rater_worker as worker

    path = tmp_path / "candidate.pdf"
    path.write_bytes(b"resume")
    workspace = ResumeRaterWorkspace(owner_id="owner", title="Engineer", current_revision=1)
    db_session.add(workspace)
    await db_session.flush()
    revision = ResumeRaterRevision(
        workspace_id=workspace.id,
        version=1,
        job_posting="x" * 100,
        criteria_json=ResumeRubric(
            criteria=[
                {
                    "id": "experience",
                    "label": "Experience",
                    "description": "Relevant experience",
                    "weight": 60,
                },
                {"id": "skills", "label": "Skills", "description": "Required skills", "weight": 39},
                {
                    "id": "writing",
                    "label": "Writing",
                    "description": "Clear written communication",
                    "weight": 1,
                },
            ]
        ).model_dump_json(),
        status="approved",
    )
    db_session.add(revision)
    await db_session.flush()
    candidate = ResumeRaterCandidate(
        workspace_id=workspace.id,
        display_name="Candidate One",
        filename="candidate.pdf",
        resume_path=str(path),
        content_sha256="0" * 64,
    )
    db_session.add(candidate)
    await db_session.flush()
    assessment = ResumeRaterAssessment(
        workspace_id=workspace.id,
        candidate_id=candidate.id,
        revision_id=revision.id,
        status="queued",
    )
    db_session.add(assessment)
    await db_session.flush()
    task = ResumeRaterTask(
        workspace_id=workspace.id,
        revision_id=revision.id,
        assessment_id=assessment.id,
        kind="assessment",
        status="queued",
    )
    db_session.add(task)
    await db_session.commit()

    async def _parse_resume(*_args):
        return _parsed_document("Built services for eight years. Used Python and SQL.")

    monkeypatch.setattr(parser_module.document_parser_service, "parse", _parse_resume)

    async def _assess(_posting: str, _text: str, _rubric: ResumeRubric):
        return _report(), 89

    monkeypatch.setattr(worker, "assess_resume", _assess)
    assert await process_one_resume_rater_task(db_session)
    await db_session.refresh(assessment)
    await db_session.refresh(task)
    assert assessment.status == "completed"
    assert assessment.score == 89
    assert json.loads(assessment.result_json or "{}")["summary"] == "Evidence was found."
    assert task.status == "completed"


async def test_unreadable_resume_needs_attention_and_no_score(
    db_session: AsyncSession, tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    import app.services.document_parser as parser_module

    path = tmp_path / "scanned.pdf"
    path.write_bytes(b"resume")
    workspace = ResumeRaterWorkspace(owner_id="owner", title="Engineer", current_revision=1)
    db_session.add(workspace)
    await db_session.flush()
    revision = ResumeRaterRevision(
        workspace_id=workspace.id,
        version=1,
        job_posting="x" * 100,
        status="approved",
        criteria_json=ResumeRubric(
            criteria=[
                {
                    "id": "experience",
                    "label": "Experience",
                    "description": "Relevant experience",
                    "weight": 60,
                },
                {"id": "skills", "label": "Skills", "description": "Required skills", "weight": 39},
                {
                    "id": "writing",
                    "label": "Writing",
                    "description": "Clear written communication",
                    "weight": 1,
                },
            ]
        ).model_dump_json(),
    )
    db_session.add(revision)
    await db_session.flush()
    candidate = ResumeRaterCandidate(
        workspace_id=workspace.id,
        display_name="Scanned",
        filename="scanned.pdf",
        resume_path=str(path),
        content_sha256="1" * 64,
    )
    db_session.add(candidate)
    await db_session.flush()
    assessment = ResumeRaterAssessment(
        workspace_id=workspace.id,
        candidate_id=candidate.id,
        revision_id=revision.id,
        status="queued",
    )
    db_session.add(assessment)
    await db_session.flush()
    db_session.add(
        ResumeRaterTask(
            workspace_id=workspace.id,
            revision_id=revision.id,
            assessment_id=assessment.id,
            kind="assessment",
            status="queued",
        )
    )
    await db_session.commit()

    async def _parse_resume(*_args):
        return _parsed_document("")

    monkeypatch.setattr(parser_module.document_parser_service, "parse", _parse_resume)

    assert await process_one_resume_rater_task(db_session)
    await db_session.refresh(assessment)
    assert assessment.status == "needs_attention"
    assert assessment.score is None
    assert "text-based PDF or DOCX" in (assessment.error_message or "")


async def test_interrupted_worker_task_is_requeued_after_restart(db_session: AsyncSession) -> None:
    workspace = ResumeRaterWorkspace(owner_id="owner", title="Engineer", current_revision=1)
    db_session.add(workspace)
    await db_session.flush()
    revision = ResumeRaterRevision(
        workspace_id=workspace.id, version=1, job_posting="x" * 100, status="approved"
    )
    db_session.add(revision)
    await db_session.flush()
    candidate = ResumeRaterCandidate(
        workspace_id=workspace.id,
        display_name="Candidate",
        filename="candidate.pdf",
        resume_path="/tmp/candidate.pdf",
        content_sha256="2" * 64,
    )
    db_session.add(candidate)
    await db_session.flush()
    assessment = ResumeRaterAssessment(
        workspace_id=workspace.id,
        candidate_id=candidate.id,
        revision_id=revision.id,
        status="processing",
    )
    db_session.add(assessment)
    await db_session.flush()
    task = ResumeRaterTask(
        workspace_id=workspace.id,
        revision_id=revision.id,
        assessment_id=assessment.id,
        kind="assessment",
        status="processing",
        lease_until=datetime.now(UTC) + timedelta(minutes=5),
    )
    db_session.add(task)
    await db_session.commit()

    assert await recover_interrupted_tasks(db_session) == 1
    await db_session.refresh(assessment)
    await db_session.refresh(task)
    assert assessment.status == "queued"
    assert task.status == "queued"
    assert task.lease_until is None


async def test_cancelled_rubric_is_not_reopened_by_a_worker_that_already_claimed_it(
    db_session: AsyncSession, monkeypatch: MonkeyPatch
) -> None:
    import app.services.resume_rater_worker as worker

    workspace = ResumeRaterWorkspace(owner_id="owner", title="Engineer", current_revision=1)
    db_session.add(workspace)
    await db_session.flush()
    revision = ResumeRaterRevision(
        workspace_id=workspace.id,
        version=1,
        job_posting="x" * 100,
        status="cancelled",
    )
    db_session.add(revision)
    await db_session.flush()
    task = ResumeRaterTask(
        workspace_id=workspace.id,
        revision_id=revision.id,
        kind="rubric",
        status="cancelled",
    )
    db_session.add(task)
    await db_session.commit()

    async def _already_claimed(_db: AsyncSession) -> str:
        return task.id

    async def _should_not_draft(_job_posting: str) -> ResumeRubric:
        raise AssertionError("a cancelled rubric must not be sent to the model")

    monkeypatch.setattr(worker, "_claim_task", _already_claimed)
    monkeypatch.setattr(worker, "draft_resume_rubric", _should_not_draft)

    assert await process_one_resume_rater_task(db_session)
    await db_session.refresh(revision)
    assert revision.status == "cancelled"


async def test_cancelled_assessment_is_not_reopened_by_a_worker_that_already_claimed_it(
    db_session: AsyncSession, monkeypatch: MonkeyPatch
) -> None:
    import app.services.resume_rater_worker as worker

    workspace = ResumeRaterWorkspace(owner_id="owner", title="Engineer", current_revision=1)
    db_session.add(workspace)
    await db_session.flush()
    revision = ResumeRaterRevision(
        workspace_id=workspace.id, version=1, job_posting="x" * 100, status="approved"
    )
    db_session.add(revision)
    await db_session.flush()
    candidate = ResumeRaterCandidate(
        workspace_id=workspace.id,
        display_name="Candidate",
        filename="candidate.pdf",
        resume_path="/tmp/candidate.pdf",
        content_sha256="3" * 64,
    )
    db_session.add(candidate)
    await db_session.flush()
    assessment = ResumeRaterAssessment(
        workspace_id=workspace.id,
        candidate_id=candidate.id,
        revision_id=revision.id,
        status="cancelled",
    )
    db_session.add(assessment)
    await db_session.flush()
    task = ResumeRaterTask(
        workspace_id=workspace.id,
        revision_id=revision.id,
        assessment_id=assessment.id,
        kind="assessment",
        status="cancelled",
    )
    db_session.add(task)
    await db_session.commit()

    async def _already_claimed(_db: AsyncSession) -> str:
        return task.id

    monkeypatch.setattr(worker, "_claim_task", _already_claimed)

    assert await process_one_resume_rater_task(db_session)
    await db_session.refresh(assessment)
    assert assessment.status == "cancelled"


async def test_failure_handler_does_not_overwrite_a_concurrent_cancellation() -> None:
    fake_db = AsyncMock()
    fake_db.execute.return_value = SimpleNamespace(rowcount=0)
    task = SimpleNamespace(
        id="task-id", kind="assessment", assessment_id="assessment-id", revision_id="revision-id"
    )

    await _fail_task(fake_db, task, ValueError("Model output was invalid."))

    fake_db.execute.assert_awaited_once()
    fake_db.rollback.assert_awaited_once()
    fake_db.commit.assert_not_awaited()


def _parsed_document(text: str) -> SimpleNamespace:
    return SimpleNamespace(text=text)

"""Tests for durable processing of local redaction jobs."""

from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING

import pymupdf
import pytest
from sqlalchemy import select

import app.services.redaction_job_worker as worker
from app.config import settings
from app.models.db_models import Account, Document, RedactionJob

if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncSession

    from app.services.redaction_documents import ExtractedPage


@pytest.mark.asyncio
async def test_worker_extracts_candidates_and_persists_review_without_text_logs(
    db_session: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = Account(
        id=str(uuid.uuid4()),
        username="redaction-worker-test",
        display_name="Worker test",
        password_hash="!test!",
    )
    source = tmp_path / "worker-source.pdf"
    document = pymupdf.open()
    page = document.new_page(width=300, height=400)
    page.insert_text((24, 60), "Employee Name: Alex Example", fontsize=14)
    document.save(source)
    document.close()
    job_dir = tmp_path / "job-data"
    db_session.add(owner)
    db_session.add(
        Document(
            id=str(uuid.uuid4()),
            owner_id=owner.id,
            filename="worker-source.pdf",
            format="pdf",
            size_bytes=source.stat().st_size,
            storage_path=str(source),
        )
    )
    db_document = await db_session.scalar(
        select(Document).where(Document.filename == "worker-source.pdf")
    )
    assert db_document is not None
    job = RedactionJob(
        id=str(uuid.uuid4()),
        owner_id=owner.id,
        document_id=db_document.id,
        status="queued",
        instructions="",
        categories_json='["person name"]',
        source_sha256=worker._sha256(source),
        job_dir=str(job_dir),
    )
    db_session.add(job)
    await db_session.commit()

    async def fake_detect(
        page: ExtractedPage,
        categories: list[str],
        *,
        cache_dir: Path,
    ) -> list[dict[str, object]]:
        assert categories == ["person name"]
        assert cache_dir
        start = page.text.index("Alex Example")
        return [
            {
                "start": start,
                "end": start + len("Alex Example"),
                "text": "Alex Example",
                "category": "person name",
                "confidence": 0.99,
                "source": "test",
                "selected": True,
            }
        ]

    monkeypatch.setattr(worker, "detect_candidates", fake_detect)

    assert await worker.process_one_redaction_job(db_session)
    await db_session.refresh(job)
    data = json.loads((job_dir / worker.DATA_FILENAME).read_text(encoding="utf-8"))

    assert job.status == "review_ready"
    assert job.pages_processed == job.page_count == 1
    assert data["findings"][0]["text"] == "Alex Example"
    assert (job_dir / worker.DATA_FILENAME).stat().st_mode & 0o777 == 0o600


def test_artifact_cleanup_is_owner_scoped_and_removes_only_known_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))
    owner_dir = settings.upload_path / "redaction-jobs" / "account-1"
    job_dir = owner_dir / "job-1"
    job_dir.mkdir(parents=True)
    (job_dir / worker.DATA_FILENAME).write_text("private", encoding="utf-8")
    (job_dir / "redacted.pdf").write_bytes(b"private")

    worker.cleanup_redaction_job_artifacts(str(job_dir), "account-1")

    assert not job_dir.exists()
    assert not owner_dir.exists()
    with pytest.raises(ValueError, match="outside"):
        worker.cleanup_redaction_job_artifacts(str(tmp_path), "account-1")

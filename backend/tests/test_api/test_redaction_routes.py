"""Authorization and review gates for document redaction endpoints."""

from __future__ import annotations

import hashlib
import json
import uuid
import zipfile
from datetime import UTC, datetime
from io import BytesIO
from typing import TYPE_CHECKING

import pymupdf
import pytest
from sqlalchemy import select

from app.models.db_models import Account, AccountSession, Document, RedactionJob
from app.services.auth import AuthenticatedSession

if TYPE_CHECKING:
    from pathlib import Path

    from httpx import AsyncClient
    from pytest import MonkeyPatch
    from sqlalchemy.ext.asyncio import AsyncSession
    from starlette.types import Message, Scope


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


async def test_redaction_jobs_are_owner_scoped_and_create_review_state(
    client: AsyncClient,
    db_session: AsyncSession,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    import app.api.routes.redaction as redaction_routes
    from app.dependencies import get_authenticated_session

    monkeypatch.setattr(redaction_routes.settings, "upload_dir", str(tmp_path / "uploads"))
    alice = Account(
        id="redaction-alice",
        username="redaction-alice",
        display_name="Alice",
        password_hash="!test!",
    )
    bob = Account(
        id="redaction-bob",
        username="redaction-bob",
        display_name="Bob",
        password_hash="!test!",
    )
    source = tmp_path / "source.pdf"
    source.write_bytes(b"synthetic source")
    source_id = str(uuid.uuid4())
    db_session.add_all([alice, bob])
    db_session.add(
        Document(
            id=source_id,
            owner_id=alice.id,
            filename="source.pdf",
            format="pdf",
            size_bytes=16,
            content_sha256="not-used",
            storage_path=str(source),
        )
    )
    await db_session.commit()
    client._transport.app.dependency_overrides[get_authenticated_session] = lambda: _principal(
        alice
    )

    created = await client.post(
        "/api/v1/redaction-jobs",
        json={"document_id": source_id, "categories": ["email address"]},
    )
    assert created.status_code == 202
    job_id = created.json()["id"]
    assert created.json()["status"] == "queued"

    client._transport.app.dependency_overrides[get_authenticated_session] = lambda: _principal(bob)
    assert (await client.get(f"/api/v1/redaction-jobs/{job_id}")).status_code == 404
    assert (await client.post(f"/api/v1/redaction-jobs/{job_id}/export")).status_code == 404

    job = await db_session.get(RedactionJob, job_id)
    assert job is not None and job.owner_id == alice.id


async def test_redaction_export_requires_approval(
    client: AsyncClient,
    db_session: AsyncSession,
    authenticated_test_session: AuthenticatedSession,
    tmp_path: Path,
) -> None:
    from app.dependencies import get_authenticated_session

    source = tmp_path / "redaction-export-gate.pdf"
    source.write_bytes(b"synthetic source")
    account = authenticated_test_session.account
    db_session.add(
        Document(
            id="redaction-gate-source",
            owner_id=account.id,
            filename="source.pdf",
            format="pdf",
            size_bytes=16,
            storage_path=str(source),
        )
    )
    job = RedactionJob(
        id="redaction-gate-job",
        owner_id=account.id,
        document_id="redaction-gate-source",
        status="review_ready",
        instructions="",
        categories_json='["email address"]',
        source_sha256="0" * 64,
        job_dir=str(tmp_path / "redaction-gate-job"),
    )
    db_session.add(job)
    await db_session.commit()
    client._transport.app.dependency_overrides[get_authenticated_session] = lambda: (
        authenticated_test_session
    )

    result = await client.post("/api/v1/redaction-jobs/redaction-gate-job/export")
    assert result.status_code == 409


async def test_redaction_batch_queues_one_job_per_owned_source(
    client: AsyncClient,
    db_session: AsyncSession,
    authenticated_test_session: AuthenticatedSession,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    import app.api.routes.redaction as redaction_routes

    monkeypatch.setattr(redaction_routes.settings, "upload_dir", str(tmp_path / "uploads"))
    owner_id = authenticated_test_session.account.id
    documents = []
    for index in range(2):
        source = tmp_path / f"batch-source-{index}.pdf"
        source.write_bytes(f"synthetic PDF {index}".encode())
        documents.append(
            Document(
                id=str(uuid.uuid4()),
                owner_id=owner_id,
                filename=source.name,
                format="pdf",
                size_bytes=source.stat().st_size,
                storage_path=str(source),
            )
        )
    db_session.add_all(documents)
    await db_session.commit()

    response = await client.post(
        "/api/v1/redaction-batches",
        json={
            "document_ids": [document.id for document in documents],
            "categories": ["email address"],
            "instructions": "Redact work emails.",
        },
    )

    assert response.status_code == 202
    body = response.json()
    assert len(body["jobs"]) == 2
    assert [job["document_id"] for job in body["jobs"]] == [document.id for document in documents]
    assert all(job["batch_id"] == body["id"] for job in body["jobs"])
    persisted_jobs = list(
        (
            await db_session.scalars(
                select(RedactionJob).where(RedactionJob.batch_id == body["id"])
            )
        ).all()
    )
    assert len(persisted_jobs) == 2

    status = await client.get(f"/api/v1/redaction-batches/{body['id']}")
    assert status.status_code == 200
    assert [job["id"] for job in status.json()["jobs"]] == [job["id"] for job in body["jobs"]]

    from app.dependencies import get_authenticated_session

    other_account = Account(
        id="redaction-batch-other",
        username="redaction-batch-other",
        display_name="Other",
        password_hash="!test!",
    )
    db_session.add(other_account)
    await db_session.commit()
    client._transport.app.dependency_overrides[get_authenticated_session] = lambda: _principal(
        other_account
    )
    assert (await client.get(f"/api/v1/redaction-batches/{body['id']}")).status_code == 404


async def test_redaction_batch_rejects_invalid_source_without_partial_jobs(
    client: AsyncClient,
    db_session: AsyncSession,
    authenticated_test_session: AuthenticatedSession,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    import app.api.routes.redaction as redaction_routes

    upload_dir = tmp_path / "uploads"
    monkeypatch.setattr(redaction_routes.settings, "upload_dir", str(upload_dir))
    owner_id = authenticated_test_session.account.id
    documents = []
    for filename, file_format in [("valid.pdf", "pdf"), ("invalid.docx", "docx")]:
        source = tmp_path / filename
        source.write_bytes(b"synthetic source")
        documents.append(
            Document(
                id=str(uuid.uuid4()),
                owner_id=owner_id,
                filename=filename,
                format=file_format,
                size_bytes=source.stat().st_size,
                storage_path=str(source),
            )
        )
    db_session.add_all(documents)
    await db_session.commit()

    response = await client.post(
        "/api/v1/redaction-batches",
        json={
            "document_ids": [document.id for document in documents],
            "categories": ["email address"],
        },
    )

    assert response.status_code == 422
    assert list((await db_session.scalars(select(RedactionJob))).all()) == []
    assert not (upload_dir / "redaction-jobs" / owner_id).exists()


async def test_redaction_batch_download_requires_current_exports_and_hides_source_names(
    client: AsyncClient,
    db_session: AsyncSession,
    authenticated_test_session: AuthenticatedSession,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    import app.api.routes.redaction as redaction_routes
    from app.dependencies import get_authenticated_session

    monkeypatch.setattr(redaction_routes.settings, "upload_dir", str(tmp_path / "uploads"))
    owner_id = authenticated_test_session.account.id
    batch_id = str(uuid.uuid4())
    jobs = []
    owner_dir = tmp_path / "uploads" / "redaction-jobs" / owner_id
    for index in range(2):
        document_id = str(uuid.uuid4())
        job_id = str(uuid.uuid4())
        job_dir = owner_dir / job_id
        job_dir.mkdir(parents=True)
        (job_dir / "redacted.pdf").write_bytes(f"sanitized-{index}".encode())
        db_session.add(
            Document(
                id=document_id,
                owner_id=owner_id,
                filename=f"confidential-source-{index}.pdf",
                format="pdf",
                size_bytes=16,
                storage_path=str(tmp_path / f"missing-source-{index}.pdf"),
            )
        )
        jobs.append(
            RedactionJob(
                id=job_id,
                owner_id=owner_id,
                document_id=document_id,
                batch_id=batch_id,
                status="exported",
                instructions="",
                categories_json='["email address"]',
                source_sha256="0" * 64,
                job_dir=str(job_dir),
                review_revision=2,
                approved_revision=2,
            )
        )
    db_session.add_all(jobs)
    await db_session.commit()
    client._transport.app.dependency_overrides[get_authenticated_session] = lambda: (
        authenticated_test_session
    )

    response = await client.get(f"/api/v1/redaction-batches/{batch_id}/download")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert response.headers["cache-control"] == "no-store"
    assert "redacted-documents.zip" in response.headers["content-disposition"]
    with zipfile.ZipFile(BytesIO(response.content)) as archive:
        assert archive.namelist() == ["redacted-document-001.pdf", "redacted-document-002.pdf"]
        assert archive.read("redacted-document-001.pdf") == b"sanitized-0"
        assert archive.read("redacted-document-002.pdf") == b"sanitized-1"
        assert all("confidential-source" not in name for name in archive.namelist())
    assert not list(owner_dir.glob("redaction-batch-*.zip"))

    other_account = Account(
        id="redaction-batch-download-other",
        username="redaction-batch-download-other",
        display_name="Other",
        password_hash="!test!",
    )
    db_session.add(other_account)
    await db_session.commit()
    client._transport.app.dependency_overrides[get_authenticated_session] = lambda: _principal(
        other_account
    )
    assert (await client.get(f"/api/v1/redaction-batches/{batch_id}/download")).status_code == 404

    client._transport.app.dependency_overrides[get_authenticated_session] = lambda: (
        authenticated_test_session
    )
    jobs[1].status = "review_ready"
    await db_session.commit()
    assert (await client.get(f"/api/v1/redaction-batches/{batch_id}/download")).status_code == 409


async def test_redaction_batch_archive_is_removed_when_response_send_fails(tmp_path: Path) -> None:
    import app.api.routes.redaction as redaction_routes

    archive_path = tmp_path / "temporary-redaction-batch.zip"
    archive_path.write_bytes(b"archive")
    response = redaction_routes._TemporaryArchiveResponse(
        archive_path,
        media_type="application/zip",
        filename="redacted-documents.zip",
    )
    scope: Scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/download",
        "raw_path": b"/download",
        "query_string": b"",
        "root_path": "",
        "headers": [],
        "client": ("test", 1),
        "server": ("test", 80),
    }

    async def receive() -> Message:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: Message) -> None:
        if message["type"] == "http.response.body":
            raise RuntimeError("Client disconnected.")

    with pytest.raises(RuntimeError, match="Client disconnected"):
        await response(scope, receive, send)

    assert not archive_path.exists()


async def test_redaction_agent_catalog_task_opens_a_private_job(
    client: AsyncClient,
    db_session: AsyncSession,
    authenticated_test_session: AuthenticatedSession,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    import app.api.routes.redaction as redaction_routes
    from app.dependencies import get_authenticated_session

    monkeypatch.setattr(redaction_routes.settings, "upload_dir", str(tmp_path / "uploads"))
    source = tmp_path / "agent-source.pdf"
    source.write_bytes(b"synthetic document bytes")
    document_id = str(uuid.uuid4())
    db_session.add(
        Document(
            id=document_id,
            owner_id=authenticated_test_session.account.id,
            filename="agent-source.pdf",
            format="pdf",
            size_bytes=source.stat().st_size,
            storage_path=str(source),
        )
    )
    await db_session.commit()
    client._transport.app.dependency_overrides[get_authenticated_session] = lambda: (
        authenticated_test_session
    )

    result = await client.post(
        "/api/v1/tasks",
        json={
            "prompt": "Redact employee names but leave manager names.",
            "target": "document_redaction",
            "asset_id": document_id,
        },
    )

    assert result.status_code == 200
    assert result.json()["agent"] == "document_redaction"
    assert result.json()["artifacts"]["review_url"].startswith("/redaction?job_id=")


async def test_manual_review_approval_gates_sanitized_download(
    client: AsyncClient,
    db_session: AsyncSession,
    authenticated_test_session: AuthenticatedSession,
    tmp_path: Path,
) -> None:
    from app.dependencies import get_authenticated_session

    owner = authenticated_test_session.account
    source = tmp_path / "review-source.pdf"
    pdf = pymupdf.open()
    page = pdf.new_page(width=300, height=400)
    page.insert_text((24, 60), "Employee Name: Alex Example", fontsize=14)
    pdf.save(source)
    pdf.close()
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    job_dir = tmp_path / "review-job"
    job_dir.mkdir()
    (job_dir / "review-data.json").write_text(
        json.dumps(
            {
                "pages": [
                    {
                        "number": 0,
                        "width": 300,
                        "height": 400,
                        "text": "Employee Name: Alex Example",
                        "words": [
                            {
                                "start": 15,
                                "end": 19,
                                "rect": [110, 45, 135, 62],
                                "line": [0, 0],
                                "source": "pdf",
                                "confidence": None,
                            },
                        ],
                    }
                ],
                "failed_pages": [
                    {
                        "page_number": 0,
                        "error": "Page extraction failed.",
                        "manual_reviewed": False,
                        "attempts": 1,
                    }
                ],
                "findings": [
                    {
                        "id": "review-finding",
                        "page_number": 0,
                        "category": "person name",
                        "text": "Alex",
                        "confidence": 0.9,
                        "source": "gliner",
                        "selected": True,
                        "boxes": [[108, 43, 138, 64]],
                    }
                ],
                "warnings": [],
            }
        ),
        encoding="utf-8",
    )
    db_session.add(
        Document(
            id="review-source-document",
            owner_id=owner.id,
            filename="review-source.pdf",
            format="pdf",
            size_bytes=source.stat().st_size,
            storage_path=str(source),
        )
    )
    db_session.add(
        RedactionJob(
            id="reviewable-redaction-job",
            owner_id=owner.id,
            document_id="review-source-document",
            status="review_ready",
            instructions="",
            categories_json='["person name"]',
            source_sha256=digest,
            job_dir=str(job_dir),
            page_count=1,
            pages_processed=1,
            review_revision=1,
        )
    )
    await db_session.commit()
    client._transport.app.dependency_overrides[get_authenticated_session] = lambda: (
        authenticated_test_session
    )

    review = await client.get("/api/v1/redaction-jobs/reviewable-redaction-job/review")
    assert review.status_code == 200
    assert review.json()["pages"] == [{"number": 0, "width": 300.0, "height": 400.0}]

    changed = await client.patch(
        "/api/v1/redaction-jobs/reviewable-redaction-job/findings/review-finding",
        json={"selected": False, "boxes": [[108, 43, 138, 64]]},
    )
    assert changed.json()["review_revision"] == 2
    whole_page = await client.post(
        "/api/v1/redaction-jobs/reviewable-redaction-job/redact-whole-page",
        json={"page_number": 0},
    )
    assert whole_page.json()["review_revision"] == 3
    updated_review = await client.get("/api/v1/redaction-jobs/reviewable-redaction-job/review")
    assert updated_review.json()["failed_pages"][0]["manual_reviewed"] is False
    assert updated_review.json()["failed_pages"][0]["whole_page_redacted"] is True
    assert any(
        finding["category"] == "whole page"
        and finding["selected"]
        and finding["boxes"] == [[0.0, 0.0, 300.0, 400.0]]
        for finding in updated_review.json()["findings"]
    )
    manual = await client.post(
        "/api/v1/redaction-jobs/reviewable-redaction-job/manual-boxes",
        json={"page_number": 0, "box": [108, 43, 138, 64]},
    )
    assert manual.json()["review_revision"] == 4
    approved = await client.post(
        "/api/v1/redaction-jobs/reviewable-redaction-job/approve?revision=4"
    )
    assert approved.json()["status"] == "approved"
    exported = await client.post("/api/v1/redaction-jobs/reviewable-redaction-job/export")
    assert exported.json()["status"] == "exported"
    download = await client.get("/api/v1/redaction-jobs/reviewable-redaction-job/download")
    assert download.status_code == 200
    assert download.headers["cache-control"] == "no-store"
    result = pymupdf.open(stream=download.content, filetype="pdf")
    assert result[0].get_text().strip() == ""
    result.close()

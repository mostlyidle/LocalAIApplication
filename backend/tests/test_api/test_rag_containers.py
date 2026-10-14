"""API tests for private RAG containers and staged-file ingestion."""

from __future__ import annotations

import io
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, call

from app.models.db_models import LEGACY_ACCOUNT_ID, Document, RagContainerFile

if TYPE_CHECKING:
    from pathlib import Path

    import pytest
    from httpx import AsyncClient


async def _create_container(client: AsyncClient, display_name: str = "Research") -> dict:
    response = await client.post("/api/v1/rag/containers", json={"display_name": display_name})
    assert response.status_code == 201
    return response.json()


class TestRAGContainers:
    async def test_create_and_list_container(self, client: AsyncClient) -> None:
        created = await _create_container(client)
        listed = await client.get("/api/v1/rag/containers")
        legacy_delete = await client.delete(f"/api/v1/rag/collections/{created['name']}")

        assert created["display_name"] == "Research"
        assert created["file_count"] == 0
        assert created["name"].startswith("container_")
        assert listed.json() == [created]
        assert legacy_delete.status_code == 409

    async def test_container_names_are_unique_per_account(self, client: AsyncClient) -> None:
        await _create_container(client)
        response = await client.post(
            "/api/v1/rag/containers", json={"display_name": "Research"}
        )

        assert response.status_code == 409

    async def test_upload_reports_each_failure_and_rejects_path_traversal(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from app.config import settings

        monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))
        container = await _create_container(client)
        response = await client.post(
            f"/api/v1/rag/containers/{container['name']}/files",
            files=[
                ("relative_paths", (None, "folder/guide.txt")),
                ("files", ("guide.txt", io.BytesIO(b"safe content"), "text/plain")),
                ("relative_paths", (None, "../outside.txt")),
                ("files", ("outside.txt", io.BytesIO(b"outside"), "text/plain")),
                ("relative_paths", (None, "folder/unknown.exe")),
                ("files", ("unknown.exe", io.BytesIO(b"binary"), "application/octet-stream")),
            ],
        )

        assert response.status_code == 200
        data = response.json()
        assert [item["relative_path"] for item in data["files"]] == ["folder/guide.txt"]
        assert data["files"][0]["status"] == "staged"
        assert [item["relative_path"] for item in data["failures"]] == [
            "../outside.txt",
            "folder/unknown.exe",
        ]
        summary = await client.get("/api/v1/rag/containers")
        assert summary.json()[0]["staged_file_count"] == 1

    async def test_add_existing_document_to_container_queues_it_for_indexing(
        self,
        client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        from app.config import settings

        monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))
        container = await _create_container(client)
        uploaded = await client.post(
            "/api/v1/documents/upload",
            files={"file": ("report.txt", io.BytesIO(b"Report contents"), "text/plain")},
        )
        assert uploaded.status_code == 200
        document = uploaded.json()

        queued = await client.post(
            f"/api/v1/rag/containers/{container['name']}/documents/{document['id']}"
        )
        listed = await client.get(f"/api/v1/rag/containers/{container['name']}/files")

        assert queued.status_code == 202
        assert queued.json()["relative_path"] == "report.txt"
        assert queued.json()["status"] == "queued"
        assert listed.json() == [queued.json()]

    async def test_add_existing_document_rejects_another_accounts_document(
        self,
        client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        from app.config import settings
        from app.dependencies import get_authenticated_session
        from app.models.db_models import Account, AccountSession
        from app.services.auth import AuthenticatedSession

        monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))
        container = await _create_container(client)
        uploaded = await client.post(
            "/api/v1/documents/upload",
            files={"file": ("report.txt", io.BytesIO(b"Report contents"), "text/plain")},
        )
        document_id = uploaded.json()["id"]
        other_account = Account(
            id="10000000-0000-4000-8000-000000000000",
            username="other-account",
            display_name="Other Account",
            password_hash="!test!",
        )
        other = AuthenticatedSession(
            account=other_account,
            session=AccountSession(
                id="other-session",
                account_id=other_account.id,
                token_hash="1" * 64,
                csrf_token="other-csrf-token",
                expires_at=datetime.now(UTC),
            ),
        )
        client._transport.app.dependency_overrides[get_authenticated_session] = lambda: other

        response = await client.post(
            f"/api/v1/rag/containers/{container['name']}/documents/{document_id}"
        )

        assert response.status_code == 404

    async def test_container_data_is_private(self, client: AsyncClient) -> None:
        from app.dependencies import get_authenticated_session
        from app.models.db_models import Account, AccountSession
        from app.services.auth import AuthenticatedSession

        container = await _create_container(client)
        other_account = Account(
            id="10000000-0000-4000-8000-000000000000",
            username="other-account",
            display_name="Other Account",
            password_hash="!test!",
        )
        other = AuthenticatedSession(
            account=other_account,
            session=AccountSession(
                id="other-session",
                account_id=other_account.id,
                token_hash="1" * 64,
                csrf_token="other-csrf-token",
                expires_at=datetime.now(UTC),
            ),
        )
        client._transport.app.dependency_overrides[get_authenticated_session] = lambda: other

        listed = await client.get("/api/v1/rag/containers")
        files = await client.get(f"/api/v1/rag/containers/{container['name']}/files")
        deleted = await client.delete(f"/api/v1/rag/containers/{container['name']}")
        searched = await client.post(
            "/api/v1/rag/search",
            json={"query": "private notes", "collection": container["name"]},
        )

        assert listed.json() == []
        assert files.status_code == 404
        assert deleted.status_code == 404
        assert searched.status_code == 404

    async def test_load_worker_indexes_staged_file(
        self,
        client: AsyncClient,
        db_session,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        from app.config import settings
        from app.services.rag_container_worker import process_one_container_file

        monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))
        container = await _create_container(client)
        uploaded = await client.post(
            f"/api/v1/rag/containers/{container['name']}/files",
            files=[
                ("relative_paths", (None, "notes.txt")),
                ("files", ("notes.txt", io.BytesIO(b"Local notes"), "text/plain")),
            ],
        )
        assert uploaded.status_code == 200
        file_id = uploaded.json()["files"][0]["id"]
        assert (await client.post(f"/api/v1/rag/containers/{container['name']}/load")).json() == {
            "queued": 1
        }

        parser = SimpleNamespace(
            parse=AsyncMock(return_value=SimpleNamespace(text="Local notes")),
            chunk_document=MagicMock(
                return_value=[{"text": "Local notes", "metadata": {"source": "notes.txt"}}]
            ),
        )
        vector_store = AsyncMock()
        assert await process_one_container_file(db_session, parser=parser, vector_store=vector_store)
        indexed = await db_session.get(RagContainerFile, file_id)
        assert indexed is not None
        assert indexed.status == "indexed"
        assert indexed.chunk_count == 1
        vector_store.add_documents.assert_awaited_once()
        staged_document = await db_session.get(Document, indexed.document_id)
        assert staged_document is not None
        assert staged_document.owner_id == LEGACY_ACCOUNT_ID

    async def test_deleting_replaced_source_removes_prior_indexed_vectors(
        self,
        client: AsyncClient,
        db_session,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        from app.config import settings
        from app.dependencies import get_vector_store

        monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))
        container = await _create_container(client)
        uploaded = await client.post(
            f"/api/v1/rag/containers/{container['name']}/files",
            files=[
                ("relative_paths", (None, "notes.txt")),
                ("files", ("notes.txt", io.BytesIO(b"Current source"), "text/plain")),
            ],
        )
        file_id = uploaded.json()["files"][0]["id"]
        staged = await db_session.get(RagContainerFile, file_id)
        assert staged is not None
        current_document_id = staged.document_id
        staged.indexed_document_id = "previous-version-document"
        await db_session.commit()

        vector_store = AsyncMock()
        client._transport.app.dependency_overrides[get_vector_store] = lambda: vector_store
        deleted = await client.delete(f"/api/v1/documents/{current_document_id}")

        assert deleted.status_code == 200
        assert vector_store.delete_asset.await_args_list == [
            call(container["name"], "previous-version-document"),
            call(container["name"], current_document_id),
        ]
        assert await db_session.get(RagContainerFile, file_id, populate_existing=True) is None

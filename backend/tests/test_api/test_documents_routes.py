"""Tests for document API routes."""

from __future__ import annotations

import io
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient


class TestDocumentUpload:
    """Tests for POST /api/v1/documents/upload."""

    async def test_upload_valid_pdf(self, client: AsyncClient):
        """Upload a small fake PDF file."""
        content = b"%PDF-1.4 fake pdf content for testing"
        files = {"file": ("test_doc.pdf", io.BytesIO(content), "application/pdf")}

        resp = await client.post("/api/v1/documents/upload", files=files)

        assert resp.status_code == 200
        data = resp.json()
        assert data["filename"] == "test_doc.pdf"
        assert data["format"] == "pdf"
        assert data["size_bytes"] == len(content)
        assert data["status"] == "pending"
        assert "id" in data

    async def test_upload_csv_file(self, client: AsyncClient):
        """Upload a CSV file."""
        content = b"name,age\nAlice,30\nBob,25"
        files = {"file": ("data.csv", io.BytesIO(content), "text/csv")}

        resp = await client.post("/api/v1/documents/upload", files=files)

        assert resp.status_code == 200
        data = resp.json()
        assert data["format"] == "csv"

    async def test_upload_unsupported_format(self, client: AsyncClient):
        """Upload a file with an unsupported extension."""
        content = b"binary data"
        files = {"file": ("malware.exe", io.BytesIO(content), "application/octet-stream")}

        resp = await client.post("/api/v1/documents/upload", files=files)

        assert resp.status_code == 415
        data = resp.json()
        assert data["error"]["code"] == "UNSUPPORTED_FORMAT"

    async def test_rejects_oversized_upload_before_reading_file(self, client: AsyncClient):
        content = b"x" * (4 * 1024 * 1024 + 1)
        files = {"file": ("large.txt", io.BytesIO(content), "text/plain")}
        with (
            patch("app.api.routes.documents.settings.max_upload_size_mb", 4),
            patch(
                "starlette.datastructures.UploadFile.read",
                new_callable=AsyncMock,
                return_value=content,
            ) as read,
        ):
            response = await client.post("/api/v1/documents/upload", files=files)

        assert response.status_code == 413
        read.assert_not_awaited()


class TestDocumentList:
    """Tests for GET /api/v1/documents."""

    async def test_list_empty(self, client: AsyncClient):
        """List documents when none uploaded."""
        resp = await client.get("/api/v1/documents")

        assert resp.status_code == 200
        assert resp.json() == []

    async def test_list_after_upload(self, client: AsyncClient):
        """After uploading a document, it should appear in the list."""
        # Upload first
        content = b"some markdown content"
        files = {"file": ("readme.md", io.BytesIO(content), "text/markdown")}
        upload_resp = await client.post("/api/v1/documents/upload", files=files)
        assert upload_resp.status_code == 200

        # List
        resp = await client.get("/api/v1/documents")
        assert resp.status_code == 200
        docs = resp.json()
        assert len(docs) == 1
        assert docs[0]["filename"] == "readme.md"


class TestDocumentGetAndDelete:
    """Tests for GET /api/v1/documents/{id} and DELETE /api/v1/documents/{id}."""

    async def test_get_nonexistent_returns_404(self, client: AsyncClient):
        resp = await client.get("/api/v1/documents/nonexistent-id")
        assert resp.status_code == 404

    async def test_delete_nonexistent_returns_404(self, client: AsyncClient):
        resp = await client.delete("/api/v1/documents/nonexistent-id")
        assert resp.status_code == 404

    async def test_upload_get_delete_cycle(self, client: AsyncClient):
        """Full lifecycle: upload, get, then delete."""
        # Upload
        content = b"test content"
        files = {"file": ("cycle.txt", io.BytesIO(content), "text/plain")}
        upload_resp = await client.post("/api/v1/documents/upload", files=files)
        assert upload_resp.status_code == 200
        doc_id = upload_resp.json()["id"]

        # Get
        get_resp = await client.get(f"/api/v1/documents/{doc_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["filename"] == "cycle.txt"

        # Delete
        del_resp = await client.delete(f"/api/v1/documents/{doc_id}")
        assert del_resp.status_code == 200
        assert del_resp.json()["status"] == "deleted"

        # Verify deleted
        get_resp2 = await client.get(f"/api/v1/documents/{doc_id}")
        assert get_resp2.status_code == 404

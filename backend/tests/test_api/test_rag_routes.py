"""Tests for RAG API routes.

Covers all 4 endpoints:
  POST /rag/search
  POST /rag/ingest
  GET  /rag/collections
  DELETE /rag/collections/{name}
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from app.services.rag_store import (
    RagCollectionConflictError,
    RagCollectionSchemaError,
    RagStoreUnavailableError,
)


@pytest.mark.parametrize("error, expected", [
    (RagCollectionConflictError("Embedding mismatch"), 409),
    (RagCollectionSchemaError("Loader collection is protected"), 422),
    (RagStoreUnavailableError("Store is unavailable"), 503),
])
@pytest.mark.parametrize("operation", ["ingest", "delete"])
async def test_rag_operations_surface_domain_errors(
    client: AsyncClient, db_session, tmp_path: Path, error: Exception, expected: int, operation: str
) -> None:
    from app.dependencies import get_document_parser, get_vector_store
    from app.models.db_models import Document

    store = AsyncMock()
    store.add_documents.side_effect = error
    store.delete_collection.side_effect = error
    client._transport.app.dependency_overrides[get_vector_store] = lambda: store
    if operation == "delete":
        response = await client.delete("/api/v1/rag/collections/loader")
    else:
        path = tmp_path / "report.txt"
        path.write_text("evidence", encoding="utf-8")
        db_session.add(Document(id="error-doc", filename=path.name, format="text", size_bytes=8, storage_path=str(path)))
        await db_session.commit()
        parser = SimpleNamespace(
            parse=AsyncMock(return_value=SimpleNamespace(text="evidence")),
            chunk_document=MagicMock(return_value=[{"text": "evidence", "metadata": {}}]),
        )
        client._transport.app.dependency_overrides[get_document_parser] = lambda: parser
        response = await client.post("/api/v1/rag/ingest", json={"document_id": "error-doc"})
    assert response.status_code == expected
    assert response.json()["error"]["message"] == str(error)


# =============================================================================
# POST /rag/search
# =============================================================================


class TestRAGSearch:
    """Tests for POST /api/v1/rag/search."""

    async def test_search_returns_results(self, client: AsyncClient) -> None:
        mock_vs = AsyncMock()
        mock_vs.search = AsyncMock(
            return_value=[
                {
                    "content": "Python is a programming language.",
                    "score": 0.92,
                    "metadata": {"source": "intro.pdf", "page": 1, "section": "Overview"},
                },
                {
                    "content": "It supports multiple paradigms.",
                    "score": 0.78,
                    "metadata": {"source": "intro.pdf", "page": 2},
                },
            ]
        )
        mock_vs.search_with_provenance = AsyncMock(
            return_value=SimpleNamespace(passages=mock_vs.search.return_value, retrieval={})
        )

        from app.dependencies import get_vector_store

        client._transport.app.dependency_overrides[get_vector_store] = lambda: mock_vs

        resp = await client.post(
            "/api/v1/rag/search",
            json={"query": "What is Python?"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["query"] == "What is Python?"
        assert data["total_results"] == 2
        assert len(data["results"]) == 2
        assert data["results"][0]["source"] == "intro.pdf"
        assert data["results"][0]["score"] == 0.92
        assert data["results"][0]["page"] == 1
        assert data["results"][0]["section"] == "Overview"
        assert data["results"][1]["page"] == 2
        assert data["results"][1]["section"] is None

    async def test_search_empty_results(self, client: AsyncClient) -> None:
        mock_vs = AsyncMock()
        mock_vs.search = AsyncMock(return_value=[])
        mock_vs.search_with_provenance = AsyncMock(
            return_value=SimpleNamespace(passages=[], retrieval={})
        )

        from app.dependencies import get_vector_store

        client._transport.app.dependency_overrides[get_vector_store] = lambda: mock_vs

        resp = await client.post(
            "/api/v1/rag/search",
            json={"query": "nonexistent topic"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_results"] == 0
        assert data["results"] == []

    async def test_search_custom_params(self, client: AsyncClient) -> None:
        mock_vs = AsyncMock()
        mock_vs.search = AsyncMock(return_value=[])
        mock_vs.search_with_provenance = AsyncMock(
            return_value=SimpleNamespace(passages=[], retrieval={})
        )

        from app.dependencies import get_vector_store

        client._transport.app.dependency_overrides[get_vector_store] = lambda: mock_vs

        resp = await client.post(
            "/api/v1/rag/search",
            json={
                "query": "test",
                "collection": "custom_collection",
                "top_k": 10,
                "score_threshold": 0.8,
            },
        )
        assert resp.status_code == 200
        mock_vs.search_with_provenance.assert_awaited_once_with(
            query="test",
            collection="custom_collection",
            top_k=10,
            score_threshold=0.8,
            agent_name="rag",
        )

    async def test_search_missing_query(self, client: AsyncClient) -> None:
        resp = await client.post("/api/v1/rag/search", json={})
        assert resp.status_code == 422

    async def test_search_empty_query(self, client: AsyncClient) -> None:
        resp = await client.post("/api/v1/rag/search", json={"query": ""})
        assert resp.status_code == 422

    async def test_search_top_k_bounds(self, client: AsyncClient) -> None:
        # top_k < 1
        resp = await client.post("/api/v1/rag/search", json={"query": "test", "top_k": 0})
        assert resp.status_code == 422

        # top_k > 50
        resp = await client.post("/api/v1/rag/search", json={"query": "test", "top_k": 51})
        assert resp.status_code == 422

    async def test_search_score_threshold_bounds(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/v1/rag/search",
            json={"query": "test", "score_threshold": -0.1},
        )
        assert resp.status_code == 422

        resp = await client.post(
            "/api/v1/rag/search",
            json={"query": "test", "score_threshold": 1.1},
        )
        assert resp.status_code == 422

    async def test_search_metadata_missing_source(self, client: AsyncClient) -> None:
        """Result without source in metadata falls back to 'unknown'."""
        mock_vs = AsyncMock()
        mock_vs.search = AsyncMock(
            return_value=[{"content": "chunk", "score": 0.5, "metadata": {}}]
        )
        mock_vs.search_with_provenance = AsyncMock(
            return_value=SimpleNamespace(
                passages=mock_vs.search.return_value,
                retrieval={},
            )
        )

        from app.dependencies import get_vector_store

        client._transport.app.dependency_overrides[get_vector_store] = lambda: mock_vs

        resp = await client.post("/api/v1/rag/search", json={"query": "test"})
        assert resp.status_code == 200
        assert resp.json()["results"][0]["source"] == "unknown"


# =============================================================================
# POST /rag/ingest
# =============================================================================


class TestRAGIngest:
    """Tests for POST /api/v1/rag/ingest."""

    async def test_ingest_success(self, client: AsyncClient, db_session) -> None:
        """Ingest a document that exists in the DB and on disk."""
        from app.models.db_models import Document

        doc = Document(
            id="test-doc-1",
            filename="report.pdf",
            format="pdf",
            size_bytes=1024,
            storage_path="/tmp/test_uploads/report.pdf",
            status="completed",
        )
        db_session.add(doc)
        await db_session.commit()

        # Create the file on disk
        file_path = Path("/tmp/test_uploads/report.pdf")
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(b"fake pdf content")

        mock_parser = AsyncMock()
        mock_parsed = MagicMock()
        mock_parsed.text = "The report shows quarterly revenue growth."
        mock_parsed.tables = []
        mock_parsed.page_count = 1
        mock_parsed.word_count = 6
        mock_parsed.metadata = {"format": "pdf"}
        mock_parser.parse = AsyncMock(return_value=mock_parsed)
        mock_parser.chunk_document = MagicMock(
            return_value=[
                {
                    "text": "The report shows quarterly revenue growth.",
                    "metadata": {"source": "report.pdf", "document_id": "test-doc-1"},
                }
            ]
        )

        mock_vs = AsyncMock()
        mock_vs.add_documents = AsyncMock(return_value=1)

        from app.dependencies import get_document_parser, get_vector_store

        client._transport.app.dependency_overrides[get_document_parser] = lambda: mock_parser
        client._transport.app.dependency_overrides[get_vector_store] = lambda: mock_vs

        resp = await client.post(
            "/api/v1/rag/ingest",
            json={"document_id": "test-doc-1", "collection": "docs"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["document_id"] == "test-doc-1"
        assert data["chunks_ingested"] == 1
        assert data["collection"] == "docs"
        assert data["filename"] == "report.pdf"

        # Cleanup
        file_path.unlink(missing_ok=True)

    async def test_ingest_document_not_found(self, client: AsyncClient) -> None:
        """Ingest request for a nonexistent document returns 404."""
        resp = await client.post(
            "/api/v1/rag/ingest",
            json={"document_id": "nonexistent-id"},
        )
        assert resp.status_code == 404

    async def test_ingest_file_missing_on_disk(self, client: AsyncClient, db_session) -> None:
        """Document record exists but file is missing on disk."""
        from app.models.db_models import Document

        doc = Document(
            id="test-doc-missing",
            filename="gone.pdf",
            format="pdf",
            size_bytes=500,
            storage_path="/tmp/test_uploads/does_not_exist.pdf",
            status="completed",
        )
        db_session.add(doc)
        await db_session.commit()

        resp = await client.post(
            "/api/v1/rag/ingest",
            json={"document_id": "test-doc-missing"},
        )
        assert resp.status_code == 404

    async def test_ingest_no_text_content(self, client: AsyncClient, db_session) -> None:
        """Document parses but produces no chunks."""
        from app.models.db_models import Document

        doc = Document(
            id="test-doc-empty",
            filename="empty.pdf",
            format="pdf",
            size_bytes=100,
            storage_path="/tmp/test_uploads/empty.pdf",
            status="completed",
        )
        db_session.add(doc)
        await db_session.commit()

        file_path = Path("/tmp/test_uploads/empty.pdf")
        file_path.write_bytes(b"empty")

        mock_parser = AsyncMock()
        mock_parsed = MagicMock()
        mock_parsed.text = ""
        mock_parsed.tables = []
        mock_parsed.page_count = 0
        mock_parsed.word_count = 0
        mock_parsed.metadata = {"format": "pdf"}
        mock_parser.parse = AsyncMock(return_value=mock_parsed)
        mock_parser.chunk_document = MagicMock(return_value=[])

        from app.dependencies import get_document_parser

        client._transport.app.dependency_overrides[get_document_parser] = lambda: mock_parser

        resp = await client.post(
            "/api/v1/rag/ingest",
            json={"document_id": "test-doc-empty"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["chunks_ingested"] == 0
        assert "No text content" in data["message"]

        file_path.unlink(missing_ok=True)

    async def test_ingest_missing_document_id(self, client: AsyncClient) -> None:
        resp = await client.post("/api/v1/rag/ingest", json={})
        assert resp.status_code == 422


# =============================================================================
# GET /rag/collections
# =============================================================================


class TestRAGCollections:
    """Tests for GET /api/v1/rag/collections."""

    async def test_list_collections(self, client: AsyncClient) -> None:
        mock_vs = AsyncMock()
        mock_vs.list_collections = AsyncMock(
            return_value=[
                {"name": "documents", "document_count": 42, "metadata": {}},
                {"name": "reports", "document_count": 7, "metadata": {"source": "uploads"}},
            ]
        )

        from app.dependencies import get_vector_store

        client._transport.app.dependency_overrides[get_vector_store] = lambda: mock_vs

        resp = await client.get("/api/v1/rag/collections")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["name"] == "documents"
        assert data[0]["document_count"] == 42
        assert data[1]["name"] == "reports"

    async def test_list_collections_empty(self, client: AsyncClient) -> None:
        mock_vs = AsyncMock()
        mock_vs.list_collections = AsyncMock(return_value=[])

        from app.dependencies import get_vector_store

        client._transport.app.dependency_overrides[get_vector_store] = lambda: mock_vs

        resp = await client.get("/api/v1/rag/collections")
        assert resp.status_code == 200
        assert resp.json() == []


# =============================================================================
# DELETE /rag/collections/{name}
# =============================================================================


class TestDeleteCollection:
    """Tests for DELETE /api/v1/rag/collections/{name}."""

    async def test_delete_collection_success(self, client: AsyncClient) -> None:
        mock_vs = AsyncMock()
        mock_vs.delete_collection = AsyncMock(return_value=True)

        from app.dependencies import get_vector_store

        client._transport.app.dependency_overrides[get_vector_store] = lambda: mock_vs

        resp = await client.delete("/api/v1/rag/collections/old_docs")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "deleted"
        assert data["collection"] == "old_docs"

    async def test_delete_collection_not_found(self, client: AsyncClient) -> None:
        mock_vs = AsyncMock()
        mock_vs.delete_collection = AsyncMock(return_value=False)

        from app.dependencies import get_vector_store

        client._transport.app.dependency_overrides[get_vector_store] = lambda: mock_vs

        resp = await client.delete("/api/v1/rag/collections/nonexistent")
        assert resp.status_code == 404

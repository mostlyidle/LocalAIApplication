"""Tests for app.mcp.servers.rag_server — MCP server for RAG tools."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.mcp.servers.rag_server import (
    delete_collection,
    ingest_document,
    list_collections,
    search_knowledge_base,
)


# =============================================================================
# search_knowledge_base
# =============================================================================


class TestSearchKnowledgeBase:
    """Test the search_knowledge_base MCP tool."""

    async def test_returns_formatted_results(self):
        mock_results = [
            {
                "content": "The quick brown fox",
                "score": 0.92,
                "metadata": {"source": "doc1.pdf", "page": 3},
            },
            {
                "content": "Jumped over the lazy dog",
                "score": 0.85,
                "metadata": {"source": "doc2.txt", "page": 1},
            },
        ]

        with patch(
            "app.services.vector_store.vector_store_service.search",
            new_callable=AsyncMock,
            return_value=mock_results,
        ):
            result = await search_knowledge_base("fox")

        assert "0.9200" in result
        assert "doc1.pdf" in result
        assert "quick brown fox" in result
        assert "[1]" in result
        assert "[2]" in result

    async def test_no_results(self):
        with patch(
            "app.services.vector_store.vector_store_service.search",
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await search_knowledge_base("nonexistent query")

        assert "No relevant results" in result

    async def test_search_error(self):
        with patch(
            "app.services.vector_store.vector_store_service.search",
            new_callable=AsyncMock,
            side_effect=RuntimeError("ChromaDB unavailable"),
        ):
            result = await search_knowledge_base("query")

        assert "Search error" in result

    async def test_custom_parameters(self):
        with patch(
            "app.services.vector_store.vector_store_service.search",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_search:
            await search_knowledge_base("q", collection="custom", top_k=10, score_threshold=0.8)

        mock_search.assert_awaited_once_with(
            query="q", collection="custom", top_k=10, score_threshold=0.8
        )

    async def test_content_truncated_at_500_chars(self):
        long_content = "x" * 1000
        with patch(
            "app.services.vector_store.vector_store_service.search",
            new_callable=AsyncMock,
            return_value=[
                {
                    "content": long_content,
                    "score": 0.9,
                    "metadata": {"source": "big.txt", "page": 1},
                }
            ],
        ):
            result = await search_knowledge_base("query")

        # Content should be truncated; the full output includes score/source metadata
        # so we check the content portion doesn't have all 1000 x's
        assert len(result) < 1000


# =============================================================================
# ingest_document
# =============================================================================


class TestIngestDocument:
    """Test the ingest_document MCP tool."""

    async def test_successful_ingestion(self, tmp_path):
        test_file = tmp_path / "test.txt"
        test_file.write_text("Hello world content for testing")

        mock_parsed = MagicMock()
        mock_parsed.text = "Hello world content for testing"

        mock_chunks = [
            {"text": "Hello world", "metadata": {"source": "test.txt"}},
        ]

        with (
            patch(
                "app.services.document_parser.document_parser_service.parse",
                new_callable=AsyncMock,
                return_value=mock_parsed,
            ),
            patch(
                "app.services.document_parser.document_parser_service.chunk_text",
                return_value=mock_chunks,
            ),
            patch(
                "app.services.vector_store.vector_store_service.add_documents",
                new_callable=AsyncMock,
                return_value=1,
            ),
        ):
            result = await ingest_document(str(test_file))

        assert "Successfully ingested" in result
        assert "1 chunks" in result
        assert "test.txt" in result

    async def test_file_not_found(self):
        result = await ingest_document("/nonexistent/path/file.txt")
        assert "File not found" in result

    async def test_unsupported_format(self, tmp_path):
        test_file = tmp_path / "test.xyz"
        test_file.write_text("data")

        result = await ingest_document(str(test_file))
        assert "Unsupported" in result

    async def test_empty_document(self, tmp_path):
        test_file = tmp_path / "empty.txt"
        test_file.write_text("")

        mock_parsed = MagicMock()
        mock_parsed.text = ""

        with (
            patch(
                "app.services.document_parser.document_parser_service.parse",
                new_callable=AsyncMock,
                return_value=mock_parsed,
            ),
            patch(
                "app.services.document_parser.document_parser_service.chunk_text",
                return_value=[],
            ),
        ):
            result = await ingest_document(str(test_file))

        assert "No text content" in result

    async def test_parse_error(self, tmp_path):
        test_file = tmp_path / "bad.pdf"
        test_file.write_text("not a real pdf")

        with patch(
            "app.services.document_parser.document_parser_service.parse",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Corrupt PDF"),
        ):
            result = await ingest_document(str(test_file))

        assert "Ingestion error" in result


# =============================================================================
# list_collections
# =============================================================================


class TestListCollections:
    """Test the list_collections MCP tool."""

    async def test_returns_collections_json(self):
        with patch(
            "app.services.vector_store.vector_store_service.list_collections",
            new_callable=AsyncMock,
            return_value=[{"name": "documents", "count": 42}],
        ):
            result = await list_collections()

        assert "documents" in result
        assert "42" in result

    async def test_empty_collections(self):
        with patch(
            "app.services.vector_store.vector_store_service.list_collections",
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await list_collections()

        assert "No collections" in result

    async def test_error_handling(self):
        with patch(
            "app.services.vector_store.vector_store_service.list_collections",
            new_callable=AsyncMock,
            side_effect=RuntimeError("DB error"),
        ):
            result = await list_collections()

        assert "Error" in result


# =============================================================================
# delete_collection
# =============================================================================


class TestDeleteCollection:
    """Test the delete_collection MCP tool."""

    async def test_successful_deletion(self):
        with patch(
            "app.services.vector_store.vector_store_service.delete_collection",
            new_callable=AsyncMock,
            return_value=True,
        ):
            result = await delete_collection("old_data")

        assert "deleted successfully" in result

    async def test_collection_not_found(self):
        with patch(
            "app.services.vector_store.vector_store_service.delete_collection",
            new_callable=AsyncMock,
            return_value=False,
        ):
            result = await delete_collection("nonexistent")

        assert "not found" in result

    async def test_deletion_error(self):
        with patch(
            "app.services.vector_store.vector_store_service.delete_collection",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Permission denied"),
        ):
            result = await delete_collection("protected")

        assert "Error" in result

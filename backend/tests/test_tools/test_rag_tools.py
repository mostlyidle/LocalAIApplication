"""Tests for rag_tools — ingest, search, list collections.

Covers:
  - ingest_document (helper)
  - search_documents (helper)
  - rag_search_tool
  - rag_ingest_tool
  - rag_list_collections_tool
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# =============================================================================
# Helpers
# =============================================================================


def _make_parsed(
    text: str = "Document content here",
    metadata: dict | None = None,
) -> MagicMock:
    parsed = MagicMock()
    parsed.text = text
    parsed.tables = []
    parsed.page_count = 1
    parsed.word_count = len(text.split())
    parsed.metadata = metadata or {"format": "text"}
    return parsed


# =============================================================================
# ingest_document (async helper)
# =============================================================================


class TestIngestDocument:
    async def test_ingest_creates_chunks_and_stores(self, tmp_path: Path) -> None:
        f = tmp_path / "doc.txt"
        f.write_text("Some text to chunk and embed.")

        mock_parsed = _make_parsed(text="Some text to chunk and embed.")

        with (
            patch(
                "app.tools.rag_tools.parse_document_file",
                new_callable=AsyncMock,
                return_value=mock_parsed,
            ),
            patch("app.tools.rag_tools.document_parser_service") as mock_parser,
            patch("app.tools.rag_tools.vector_store_service") as mock_vs,
        ):
            mock_parser.chunk_text = MagicMock(
                return_value=[
                    {"text": "Some text to chunk", "metadata": {"source": "doc.txt"}},
                    {"text": "and embed.", "metadata": {"source": "doc.txt"}},
                ]
            )
            mock_vs.add_documents = AsyncMock(return_value=2)

            from app.tools.rag_tools import ingest_document

            result = await ingest_document(f, collection="test_col")
            assert result["chunk_count"] == 2
            assert result["collection"] == "test_col"
            assert "document_id" in result
            mock_vs.add_documents.assert_called_once()

    async def test_ingest_with_custom_doc_id(self, tmp_path: Path) -> None:
        f = tmp_path / "doc.txt"
        f.write_text("text")

        with (
            patch(
                "app.tools.rag_tools.parse_document_file",
                new_callable=AsyncMock,
                return_value=_make_parsed(),
            ),
            patch("app.tools.rag_tools.document_parser_service") as mock_parser,
            patch("app.tools.rag_tools.vector_store_service") as mock_vs,
        ):
            mock_parser.chunk_text = MagicMock(return_value=[{"text": "chunk", "metadata": {}}])
            mock_vs.add_documents = AsyncMock(return_value=1)

            from app.tools.rag_tools import ingest_document

            result = await ingest_document(f, document_id="my-custom-id")
            assert result["document_id"] == "my-custom-id"

    async def test_ingest_no_chunks(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.txt"
        f.write_text("")

        with (
            patch(
                "app.tools.rag_tools.parse_document_file",
                new_callable=AsyncMock,
                return_value=_make_parsed(text=""),
            ),
            patch("app.tools.rag_tools.document_parser_service") as mock_parser,
            patch("app.tools.rag_tools.vector_store_service") as mock_vs,
        ):
            mock_parser.chunk_text = MagicMock(return_value=[])

            from app.tools.rag_tools import ingest_document

            result = await ingest_document(f)
            assert result["chunk_count"] == 0
            mock_vs.add_documents.assert_not_called()


# =============================================================================
# search_documents (async helper)
# =============================================================================


class TestSearchDocuments:
    async def test_search_delegates_to_vector_store(self) -> None:
        with patch("app.tools.rag_tools.vector_store_service") as mock_vs:
            mock_vs.search = AsyncMock(
                return_value=[
                    {"content": "result 1", "score": 0.9, "metadata": {}},
                ]
            )

            from app.tools.rag_tools import search_documents

            results = await search_documents("query", collection="docs", top_k=3)
            assert len(results) == 1
            assert results[0]["content"] == "result 1"
            mock_vs.search.assert_called_once_with(
                query="query",
                collection="docs",
                top_k=3,
                score_threshold=None,
            )

    async def test_search_empty_results(self) -> None:
        with patch("app.tools.rag_tools.vector_store_service") as mock_vs:
            mock_vs.search = AsyncMock(return_value=[])

            from app.tools.rag_tools import search_documents

            results = await search_documents("nothing")
            assert results == []


# =============================================================================
# rag_search_tool (LangChain tool)
# =============================================================================


class TestRAGSearchTool:
    async def test_search_returns_formatted_results(self) -> None:
        with patch("app.tools.rag_tools.vector_store_service") as mock_vs:
            mock_vs.search = AsyncMock(
                return_value=[
                    {
                        "content": "Python is great.",
                        "score": 0.95,
                        "metadata": {"source": "intro.pdf", "page": 3},
                    },
                    {
                        "content": "It supports async.",
                        "score": 0.82,
                        "metadata": {"source": "guide.md"},
                    },
                ]
            )

            from app.tools.rag_tools import rag_search_tool

            result = await rag_search_tool.ainvoke(
                {"query": "What is Python?", "collection": "docs", "top_k": 5}
            )
            assert "Result 1" in result
            assert "intro.pdf" in result
            assert "Page 3" in result
            assert "0.95" in result
            assert "Result 2" in result
            assert "guide.md" in result

    async def test_search_no_results(self) -> None:
        with patch("app.tools.rag_tools.vector_store_service") as mock_vs:
            mock_vs.search = AsyncMock(return_value=[])

            from app.tools.rag_tools import rag_search_tool

            result = await rag_search_tool.ainvoke({"query": "obscure topic"})
            assert "No relevant documents found" in result

    async def test_search_truncates_long_content(self) -> None:
        with patch("app.tools.rag_tools.vector_store_service") as mock_vs:
            mock_vs.search = AsyncMock(
                return_value=[
                    {
                        "content": "x" * 1000,
                        "score": 0.7,
                        "metadata": {"source": "long.txt"},
                    }
                ]
            )

            from app.tools.rag_tools import rag_search_tool

            result = await rag_search_tool.ainvoke({"query": "test"})
            # Content should be capped at 500 chars per chunk
            # The formatted output also contains "long.txt" which adds an "x"
            x_count = result.count("x")
            assert x_count <= 510  # 500 content + a few in source/formatting


# =============================================================================
# rag_ingest_tool (LangChain tool)
# =============================================================================


class TestRAGIngestTool:
    async def test_ingest_returns_summary(self, tmp_path: Path) -> None:
        f = tmp_path / "doc.txt"
        f.write_text("content")

        with (
            patch(
                "app.tools.rag_tools.parse_document_file",
                new_callable=AsyncMock,
                return_value=_make_parsed(),
            ),
            patch("app.tools.rag_tools.document_parser_service") as mock_parser,
            patch("app.tools.rag_tools.vector_store_service") as mock_vs,
        ):
            mock_parser.chunk_text = MagicMock(return_value=[{"text": "chunk", "metadata": {}}])
            mock_vs.add_documents = AsyncMock(return_value=1)

            from app.tools.rag_tools import rag_ingest_tool

            result = await rag_ingest_tool.ainvoke({"file_path": str(f), "collection": "mydata"})
            assert "Document ingested successfully" in result
            assert "Chunks created: 1" in result
            assert "Collection: mydata" in result


# =============================================================================
# rag_list_collections_tool (LangChain tool)
# =============================================================================


class TestRAGListCollectionsTool:
    async def test_lists_collections(self) -> None:
        with patch("app.tools.rag_tools.vector_store_service") as mock_vs:
            mock_vs.list_collections = AsyncMock(
                return_value=[
                    {"name": "documents", "document_count": 10},
                    {"name": "reports", "document_count": 5},
                ]
            )

            from app.tools.rag_tools import rag_list_collections_tool

            result = await rag_list_collections_tool.ainvoke({})
            assert "documents" in result
            assert "10 documents" in result
            assert "reports" in result
            assert "5 documents" in result

    async def test_no_collections(self) -> None:
        with patch("app.tools.rag_tools.vector_store_service") as mock_vs:
            mock_vs.list_collections = AsyncMock(return_value=[])

            from app.tools.rag_tools import rag_list_collections_tool

            result = await rag_list_collections_tool.ainvoke({})
            assert "No collections found" in result


# =============================================================================
# Tools list export
# =============================================================================


class TestRAGToolsExport:
    def test_rag_tools_list(self) -> None:
        from app.tools.rag_tools import rag_tools

        assert len(rag_tools) == 3
        names = {t.name for t in rag_tools}
        assert names == {"rag_search_tool", "rag_ingest_tool", "rag_list_collections_tool"}

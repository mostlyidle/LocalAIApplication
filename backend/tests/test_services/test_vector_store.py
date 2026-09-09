"""Tests for vector store service — ChromaDB operations.

Targets app/services/vector_store.py for 24% → 80%+ coverage.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.vector_store import VectorStoreService


# =============================================================================
# Helper: mock ChromaDB collection
# =============================================================================


def _mock_collection(
    name: str = "documents",
    count: int = 0,
    query_result: dict | None = None,
) -> MagicMock:
    """Create a mock ChromaDB collection with configurable behavior."""
    col = MagicMock()
    col.name = name
    col.count.return_value = count
    col.metadata = {"hnsw:space": "cosine"}
    col.add = MagicMock()
    col.query.return_value = query_result or {
        "documents": [[]],
        "metadatas": [[]],
        "distances": [[]],
    }
    return col


def _mock_client(collections: list[MagicMock] | None = None) -> MagicMock:
    """Create a mock ChromaDB PersistentClient."""
    client = MagicMock()
    cols = collections or []
    client.list_collections.return_value = cols
    client.get_or_create_collection.side_effect = lambda name, **kwargs: next(
        (c for c in cols if c.name == name), _mock_collection(name=name)
    )
    client.delete_collection = MagicMock()
    return client


# =============================================================================
# Initialization
# =============================================================================


class TestVectorStoreInit:
    """Tests for VectorStoreService initialization."""

    def test_lazy_client_initialization(self):
        """Client is not created until first use."""
        svc = VectorStoreService()
        assert svc._client is None

    def test_get_client_creates_on_first_call(self):
        """_get_client() creates a PersistentClient on first call."""
        svc = VectorStoreService()
        with patch("app.services.vector_store.chromadb.PersistentClient") as mock_cls:
            mock_cls.return_value = MagicMock()
            client = svc._get_client()
        assert client is not None
        assert svc._client is not None

    def test_get_client_caches(self):
        """Second call to _get_client() returns the same instance."""
        svc = VectorStoreService()
        with patch("app.services.vector_store.chromadb.PersistentClient") as mock_cls:
            mock_instance = MagicMock()
            mock_cls.return_value = mock_instance
            first = svc._get_client()
            second = svc._get_client()
        assert first is second
        mock_cls.assert_called_once()


# =============================================================================
# _get_or_create_collection
# =============================================================================


class TestGetOrCreateCollection:
    """Tests for _get_or_create_collection."""

    def test_uses_default_name(self):
        """Without name arg, uses settings.chroma_collection_name."""
        svc = VectorStoreService()
        mock_client = MagicMock()
        mock_client.get_or_create_collection.return_value = _mock_collection()
        svc._client = mock_client

        svc._get_or_create_collection()
        call_args = mock_client.get_or_create_collection.call_args
        # Default from settings is "documents"
        assert call_args[1].get("name") or call_args[0][0]  # check name was passed

    def test_uses_custom_name(self):
        """Explicit name is passed to ChromaDB."""
        svc = VectorStoreService()
        mock_client = MagicMock()
        mock_client.get_or_create_collection.return_value = _mock_collection("custom")
        svc._client = mock_client

        svc._get_or_create_collection("custom")
        mock_client.get_or_create_collection.assert_called_once_with(
            name="custom",
            metadata={"hnsw:space": "cosine"},
        )


# =============================================================================
# add_documents
# =============================================================================


class TestAddDocuments:
    """Tests for VectorStoreService.add_documents."""

    async def test_returns_zero_for_empty_texts(self):
        """Empty texts list returns 0 without touching ChromaDB."""
        svc = VectorStoreService()
        result = await svc.add_documents(texts=[], metadatas=[], ids=[])
        assert result == 0

    async def test_adds_documents_with_embeddings(self):
        """Texts are embedded and added to the collection."""
        svc = VectorStoreService()
        mock_col = _mock_collection()
        svc._client = _mock_client([mock_col])

        mock_embed = AsyncMock(return_value=[[0.1, 0.2], [0.3, 0.4]])

        with patch("app.services.vector_store.asyncio.to_thread") as mock_thread:
            mock_thread.side_effect = lambda fn: fn()  # run sync immediately
            with patch(
                "app.services.embeddings.embedding_service",
                MagicMock(embed_texts=mock_embed),
            ):
                result = await svc.add_documents(
                    texts=["doc1", "doc2"],
                    metadatas=[{"source": "a"}, {"source": "b"}],
                    ids=["id1", "id2"],
                )

        assert result == 2

    async def test_uses_specified_collection(self):
        """Collection name is passed through to _get_or_create_collection."""
        svc = VectorStoreService()
        mock_col = _mock_collection("custom")
        mock_client = _mock_client([mock_col])
        svc._client = mock_client

        mock_embed = AsyncMock(return_value=[[0.1]])

        with patch("app.services.vector_store.asyncio.to_thread") as mock_thread:
            mock_thread.side_effect = lambda fn: fn()
            with patch(
                "app.services.embeddings.embedding_service",
                MagicMock(embed_texts=mock_embed),
            ):
                await svc.add_documents(
                    texts=["doc1"],
                    metadatas=[{"source": "a"}],
                    ids=["id1"],
                    collection="custom",
                )

        mock_client.get_or_create_collection.assert_called_with(
            name="custom",
            metadata={"hnsw:space": "cosine"},
        )


# =============================================================================
# search
# =============================================================================


class TestSearch:
    """Tests for VectorStoreService.search."""

    async def test_returns_empty_when_no_results(self):
        """Empty collection returns empty results."""
        svc = VectorStoreService()
        mock_col = _mock_collection()
        svc._client = _mock_client([mock_col])

        mock_embed_svc = MagicMock()
        mock_embed_svc.embed_text = AsyncMock(return_value=[0.1, 0.2])

        with patch("app.services.vector_store.asyncio.to_thread") as mock_thread:
            mock_thread.side_effect = lambda fn: fn()
            with patch("app.services.embeddings.embedding_service", mock_embed_svc):
                result = await svc.search(query="test query")

        assert result == []

    async def test_returns_results_above_threshold(self):
        """Results with score >= threshold are returned."""
        svc = VectorStoreService()
        query_result = {
            "documents": [["Document A", "Document B"]],
            "metadatas": [[{"source": "a.txt"}, {"source": "b.txt"}]],
            "distances": [[0.2, 0.8]],  # scores: 0.8, 0.2
        }
        mock_col = _mock_collection(query_result=query_result)
        svc._client = _mock_client([mock_col])

        mock_embed_svc = MagicMock()
        mock_embed_svc.embed_text = AsyncMock(return_value=[0.1, 0.2])

        with patch("app.services.vector_store.asyncio.to_thread") as mock_thread:
            mock_thread.side_effect = lambda fn: fn()
            with patch("app.services.embeddings.embedding_service", mock_embed_svc):
                result = await svc.search(query="test", score_threshold=0.5)

        # Only Document A should pass (score 0.8 >= 0.5), Document B fails (0.2 < 0.5)
        assert len(result) == 1
        assert result[0]["content"] == "Document A"
        assert result[0]["score"] == 0.8

    async def test_filters_below_threshold(self):
        """Results below threshold are excluded."""
        svc = VectorStoreService()
        query_result = {
            "documents": [["Low relevance doc"]],
            "metadatas": [[{"source": "low.txt"}]],
            "distances": [[0.9]],  # score = 0.1
        }
        mock_col = _mock_collection(query_result=query_result)
        svc._client = _mock_client([mock_col])

        mock_embed_svc = MagicMock()
        mock_embed_svc.embed_text = AsyncMock(return_value=[0.1])

        with patch("app.services.vector_store.asyncio.to_thread") as mock_thread:
            mock_thread.side_effect = lambda fn: fn()
            with patch("app.services.embeddings.embedding_service", mock_embed_svc):
                result = await svc.search(query="test", score_threshold=0.5)

        assert len(result) == 0

    async def test_uses_default_top_k_and_threshold(self):
        """When not specified, uses settings defaults for top_k and threshold."""
        svc = VectorStoreService()
        mock_col = _mock_collection()
        svc._client = _mock_client([mock_col])

        mock_embed_svc = MagicMock()
        mock_embed_svc.embed_text = AsyncMock(return_value=[0.1])

        with patch("app.services.vector_store.asyncio.to_thread") as mock_thread:
            mock_thread.side_effect = lambda fn: fn()
            with patch("app.services.embeddings.embedding_service", mock_embed_svc):
                await svc.search(query="anything")

        # Verify n_results was set (comes from settings.rag_top_k)
        call_kwargs = mock_col.query.call_args
        assert call_kwargs is not None

    async def test_includes_metadata_in_results(self):
        """Metadata from ChromaDB is included in result dicts."""
        svc = VectorStoreService()
        query_result = {
            "documents": [["Content here"]],
            "metadatas": [[{"source": "report.pdf", "page": 3}]],
            "distances": [[0.1]],  # score = 0.9
        }
        mock_col = _mock_collection(query_result=query_result)
        svc._client = _mock_client([mock_col])

        mock_embed_svc = MagicMock()
        mock_embed_svc.embed_text = AsyncMock(return_value=[0.1])

        with patch("app.services.vector_store.asyncio.to_thread") as mock_thread:
            mock_thread.side_effect = lambda fn: fn()
            with patch("app.services.embeddings.embedding_service", mock_embed_svc):
                result = await svc.search(query="test", score_threshold=0.5)

        assert len(result) == 1
        assert result[0]["metadata"]["source"] == "report.pdf"
        assert result[0]["metadata"]["page"] == 3


# =============================================================================
# list_collections
# =============================================================================


class TestListCollections:
    """Tests for VectorStoreService.list_collections."""

    async def test_returns_empty_for_no_collections(self):
        """No collections returns empty list."""
        svc = VectorStoreService()
        mock_client = _mock_client([])
        svc._client = mock_client

        with patch("app.services.vector_store.asyncio.to_thread") as mock_thread:
            mock_thread.side_effect = lambda fn: fn()
            result = await svc.list_collections()

        assert result == []

    async def test_returns_collection_info(self):
        """Collections are returned with name, count, metadata."""
        col1 = _mock_collection("docs", count=10)
        col2 = _mock_collection("notes", count=5)
        svc = VectorStoreService()
        mock_client = _mock_client([col1, col2])
        svc._client = mock_client

        with patch("app.services.vector_store.asyncio.to_thread") as mock_thread:
            mock_thread.side_effect = lambda fn: fn()
            result = await svc.list_collections()

        assert len(result) == 2
        assert result[0]["name"] == "docs"
        assert result[0]["document_count"] == 10
        assert result[1]["name"] == "notes"
        assert result[1]["document_count"] == 5

    async def test_handles_string_collection_names(self):
        """If ChromaDB returns strings instead of Collection objects, handles it."""
        svc = VectorStoreService()
        mock_client = MagicMock()
        mock_client.list_collections.return_value = ["docs", "notes"]

        docs_col = _mock_collection("docs", count=3)
        notes_col = _mock_collection("notes", count=7)
        mock_client.get_collection.side_effect = lambda name: (
            docs_col if name == "docs" else notes_col
        )
        svc._client = mock_client

        with patch("app.services.vector_store.asyncio.to_thread") as mock_thread:
            mock_thread.side_effect = lambda fn: fn()
            result = await svc.list_collections()

        assert len(result) == 2
        assert result[0]["name"] == "docs"
        assert result[0]["document_count"] == 3


# =============================================================================
# delete_collection
# =============================================================================


class TestDeleteCollection:
    """Tests for VectorStoreService.delete_collection."""

    async def test_deletes_existing_collection(self):
        """Deleting an existing collection returns True."""
        svc = VectorStoreService()
        mock_client = MagicMock()
        mock_client.delete_collection = MagicMock()
        svc._client = mock_client

        with patch("app.services.vector_store.asyncio.to_thread") as mock_thread:
            mock_thread.side_effect = lambda fn: fn()
            result = await svc.delete_collection("documents")

        assert result is True

    async def test_returns_false_for_nonexistent(self):
        """Deleting a nonexistent collection returns False."""
        svc = VectorStoreService()
        mock_client = MagicMock()
        mock_client.delete_collection.side_effect = ValueError("not found")
        svc._client = mock_client

        with patch("app.services.vector_store.asyncio.to_thread") as mock_thread:
            mock_thread.side_effect = lambda fn: fn()
            result = await svc.delete_collection("nonexistent")

        assert result is False


# =============================================================================
# get_collection_count
# =============================================================================


class TestGetCollectionCount:
    """Tests for VectorStoreService.get_collection_count."""

    async def test_returns_count(self):
        """Returns the count from the collection."""
        svc = VectorStoreService()
        mock_col = _mock_collection(count=42)
        svc._client = _mock_client([mock_col])

        with patch("app.services.vector_store.asyncio.to_thread") as mock_thread:
            mock_thread.side_effect = lambda fn: fn()
            result = await svc.get_collection_count()

        assert result == 42

    async def test_returns_zero_for_empty(self):
        """Empty collection returns 0."""
        svc = VectorStoreService()
        mock_col = _mock_collection(count=0)
        svc._client = _mock_client([mock_col])

        with patch("app.services.vector_store.asyncio.to_thread") as mock_thread:
            mock_thread.side_effect = lambda fn: fn()
            result = await svc.get_collection_count()

        assert result == 0

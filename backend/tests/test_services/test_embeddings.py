"""Tests for app.services.embeddings — Ollama embedding service."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.services.embeddings import EmbeddingService

# =============================================================================
# Init
# =============================================================================


class TestEmbeddingServiceInit:
    """Test constructor and defaults."""

    @patch("app.services.embeddings.OllamaEmbeddings")
    def test_default_model(self, mock_cls):
        svc = EmbeddingService()
        assert svc._model == "nomic-embed-text"

    @patch("app.services.embeddings.OllamaEmbeddings")
    def test_custom_model(self, mock_cls):
        svc = EmbeddingService(model="mxbai-embed-large")
        assert svc._model == "mxbai-embed-large"

    @patch("app.services.embeddings.OllamaEmbeddings")
    def test_model_name_property(self, mock_cls):
        svc = EmbeddingService(model="test-model")
        assert svc.model_name == "test-model"

    async def test_identity_records_installed_digest(self) -> None:
        response = httpx.Response(200, json={"models": [{
            "name": "qwen3-embedding:0.6b", "digest": "sha256:actual-weights",
        }]}, request=httpx.Request("GET", "http://localhost:11434/api/tags"))
        client = AsyncMock()
        client.__aenter__.return_value = client
        client.get.return_value = response
        with patch("app.services.embeddings.httpx.AsyncClient", return_value=client):
            identity = await EmbeddingService("qwen3-embedding:0.6b").get_identity()
        assert identity["embedding_digest"] == "sha256:actual-weights"
        assert identity["embedding_profile"] == "qwen3-embedding-retrieval-v1"

    async def test_malformed_inventory_is_actionable(self) -> None:
        from app.api.middleware.error_handler import LLMConnectionError

        client = AsyncMock()
        client.__aenter__.return_value = client
        client.get.return_value = httpx.Response(
            200, json=[], request=httpx.Request("GET", "http://localhost:11434/api/tags"),
        )
        with (
            patch("app.services.embeddings.httpx.AsyncClient", return_value=client),
            pytest.raises(LLMConnectionError, match="identify"),
        ):
            await EmbeddingService().get_identity()


# =============================================================================
# embed_text
# =============================================================================


class TestEmbedText:
    """Test single-text embedding."""

    @pytest.mark.parametrize(
        ("model", "query", "document"),
        [
            ("qwen3-embedding:0.6b", "Instruct: Retrieve relevant passages that answer the query\nQuery: hello", "hello"),
            ("embeddinggemma", "task: search result | query: hello", "title: none | text: hello"),
        ],
    )
    async def test_retrieval_input_profiles(self, model: str, query: str, document: str) -> None:
        client = AsyncMock()
        with patch("app.services.embeddings.OllamaEmbeddings", return_value=client):
            service = EmbeddingService(model)
            await service.embed_text("hello")
            await service.embed_texts(["hello"])
        client.aembed_query.assert_awaited_once_with(query)
        client.aembed_documents.assert_awaited_once_with([document])

    async def test_returns_embedding_vector(self):
        mock_embeddings = AsyncMock()
        mock_embeddings.aembed_query = AsyncMock(return_value=[0.1, 0.2, 0.3])

        with patch("app.services.embeddings.OllamaEmbeddings", return_value=mock_embeddings):
            svc = EmbeddingService()
            result = await svc.embed_text("hello world")

        assert result == [0.1, 0.2, 0.3]
        mock_embeddings.aembed_query.assert_awaited_once_with("hello world")

    async def test_empty_text(self):
        mock_embeddings = AsyncMock()
        mock_embeddings.aembed_query = AsyncMock(return_value=[0.0] * 768)

        with patch("app.services.embeddings.OllamaEmbeddings", return_value=mock_embeddings):
            svc = EmbeddingService()
            result = await svc.embed_text("")

        assert len(result) == 768


# =============================================================================
# embed_texts (batched)
# =============================================================================


class TestEmbedTexts:
    """Test batch embedding."""

    async def test_single_batch(self):
        mock_embeddings = AsyncMock()
        mock_embeddings.aembed_documents = AsyncMock(
            return_value=[[0.1, 0.2], [0.3, 0.4], [0.5, 0.6]]
        )

        with patch("app.services.embeddings.OllamaEmbeddings", return_value=mock_embeddings):
            svc = EmbeddingService()
            result = await svc.embed_texts(["a", "b", "c"], batch_size=32)

        assert len(result) == 3
        mock_embeddings.aembed_documents.assert_awaited_once()

    async def test_multiple_batches(self):
        """When texts exceed batch_size, should split into multiple calls."""
        mock_embeddings = AsyncMock()
        # Two batches of 2, then one batch of 1
        mock_embeddings.aembed_documents = AsyncMock(
            side_effect=[
                [[0.1], [0.2]],
                [[0.3], [0.4]],
                [[0.5]],
            ]
        )

        with patch("app.services.embeddings.OllamaEmbeddings", return_value=mock_embeddings):
            svc = EmbeddingService()
            result = await svc.embed_texts(["a", "b", "c", "d", "e"], batch_size=2)

        assert len(result) == 5
        assert mock_embeddings.aembed_documents.await_count == 3

    async def test_empty_input(self):
        mock_embeddings = AsyncMock()
        mock_embeddings.aembed_documents = AsyncMock()

        with patch("app.services.embeddings.OllamaEmbeddings", return_value=mock_embeddings):
            svc = EmbeddingService()
            result = await svc.embed_texts([])

        assert result == []
        mock_embeddings.aembed_documents.assert_not_awaited()


# =============================================================================
# Module-level singleton
# =============================================================================


class TestSingleton:
    def test_module_level_instance(self):
        from app.services.embeddings import embedding_service

        assert isinstance(embedding_service, EmbeddingService)

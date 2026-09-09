"""Tests for FastAPI dependency injection providers."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


class TestGetDb:
    """Tests for the get_db dependency."""

    async def test_yields_async_session(self):
        """get_db should yield an AsyncSession from get_app_session."""
        from unittest.mock import MagicMock

        mock_session = MagicMock()

        async def fake_get_app_session():
            yield mock_session

        with patch("app.dependencies.get_app_session", fake_get_app_session):
            from app.dependencies import get_db

            results = []
            async for session in get_db():
                results.append(session)
            assert len(results) == 1
            assert results[0] is mock_session


class TestGetLlm:
    """Tests for the get_llm dependency."""

    def test_returns_llm_service_singleton(self):
        """get_llm should return the llm_service singleton."""
        from unittest.mock import MagicMock

        mock_service = MagicMock()
        with patch("app.services.llm.llm_service", mock_service):
            from app.dependencies import get_llm

            result = get_llm()
            assert result is mock_service


class TestGetEmbeddings:
    """Tests for the get_embeddings dependency."""

    def test_returns_embedding_service_singleton(self):
        """get_embeddings should return the embedding_service singleton."""
        from unittest.mock import MagicMock

        mock_service = MagicMock()
        with patch("app.services.embeddings.embedding_service", mock_service):
            from app.dependencies import get_embeddings

            result = get_embeddings()
            assert result is mock_service


class TestGetVectorStore:
    """Tests for the get_vector_store dependency."""

    def test_returns_vector_store_singleton(self):
        """get_vector_store should return the vector_store_service singleton."""
        from unittest.mock import MagicMock

        mock_service = MagicMock()
        with patch("app.services.vector_store.vector_store_service", mock_service):
            from app.dependencies import get_vector_store

            result = get_vector_store()
            assert result is mock_service


class TestGetDocumentParser:
    """Tests for the get_document_parser dependency."""

    def test_returns_document_parser_singleton(self):
        """get_document_parser should return the document_parser_service singleton."""
        from unittest.mock import MagicMock

        mock_service = MagicMock()
        with patch("app.services.document_parser.document_parser_service", mock_service):
            from app.dependencies import get_document_parser

            result = get_document_parser()
            assert result is mock_service


class TestGetOcr:
    """Tests for the get_ocr dependency."""

    def test_returns_ocr_service_singleton(self):
        """get_ocr should return the ocr_service singleton."""
        from unittest.mock import MagicMock

        mock_service = MagicMock()
        with patch("app.services.ocr.ocr_service", mock_service):
            from app.dependencies import get_ocr

            result = get_ocr()
            assert result is mock_service


class TestModuleExports:
    """Tests for module-level exports."""

    def test_all_exports(self):
        """__all__ should contain all expected names."""
        from app.dependencies import __all__

        expected = {
            "get_db",
            "get_document_parser",
            "get_embeddings",
            "get_llm",
            "get_ocr",
            "get_vector_store",
            "DocumentParserService",
            "EmbeddingService",
            "LLMService",
            "OCRService",
            "VectorStoreService",
        }
        assert set(__all__) == expected

    def test_type_re_exports_importable(self):
        """Type re-exports should be importable from the module."""
        from app.dependencies import (
            DocumentParserService,
            EmbeddingService,
            LLMService,
            OCRService,
            VectorStoreService,
        )

        # Just confirm they are classes/types
        assert DocumentParserService is not None
        assert EmbeddingService is not None
        assert LLMService is not None
        assert OCRService is not None
        assert VectorStoreService is not None

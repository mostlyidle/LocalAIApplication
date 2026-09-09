"""Tests for app.services.ocr — EasyOCR abstraction."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import app.services.ocr as ocr_module
from app.services.ocr import OCRService, _get_reader


# =============================================================================
# _get_reader (lazy init)
# =============================================================================


class TestGetReader:
    """Test lazy EasyOCR reader initialization."""

    def setup_method(self):
        """Reset the module-level reader before each test."""
        ocr_module._reader = None

    def teardown_method(self):
        """Reset after each test to avoid polluting other tests."""
        ocr_module._reader = None

    def test_creates_reader_on_first_call(self):
        mock_easyocr = MagicMock()
        mock_reader = MagicMock()
        mock_easyocr.Reader.return_value = mock_reader

        with patch.dict(sys.modules, {"easyocr": mock_easyocr}):
            result = _get_reader()

        mock_easyocr.Reader.assert_called_once_with(["en"], gpu=False)
        assert result is mock_reader

    def test_caches_reader_on_subsequent_calls(self):
        mock_easyocr = MagicMock()
        mock_reader = MagicMock()
        mock_easyocr.Reader.return_value = mock_reader

        with patch.dict(sys.modules, {"easyocr": mock_easyocr}):
            r1 = _get_reader()
            r2 = _get_reader()

        assert r1 is r2
        assert mock_easyocr.Reader.call_count == 1

    def test_custom_languages(self):
        mock_easyocr = MagicMock()
        mock_easyocr.Reader.return_value = MagicMock()

        with patch.dict(sys.modules, {"easyocr": mock_easyocr}):
            _get_reader(languages=["en", "fr"])

        mock_easyocr.Reader.assert_called_once_with(["en", "fr"], gpu=False)


# =============================================================================
# OCRService.extract_text
# =============================================================================


class TestExtractText:
    """Test async text extraction from images."""

    async def test_extracts_text_above_threshold(self):
        mock_reader = MagicMock()
        mock_reader.readtext.return_value = [
            ([[0, 0], [1, 0], [1, 1], [0, 1]], "Hello", 0.95),
            ([[0, 0], [1, 0], [1, 1], [0, 1]], "World", 0.80),
            ([[0, 0], [1, 0], [1, 1], [0, 1]], "noise", 0.10),  # Below 0.3 threshold
        ]

        with patch("app.services.ocr._get_reader", return_value=mock_reader):
            svc = OCRService()
            result = await svc.extract_text(Path("/tmp/test.png"))

        assert result == "Hello\nWorld"

    async def test_empty_image_returns_empty_string(self):
        mock_reader = MagicMock()
        mock_reader.readtext.return_value = []

        with patch("app.services.ocr._get_reader", return_value=mock_reader):
            svc = OCRService()
            result = await svc.extract_text(Path("/tmp/blank.png"))

        assert result == ""

    async def test_all_below_threshold(self):
        mock_reader = MagicMock()
        mock_reader.readtext.return_value = [
            ([[0, 0], [1, 0], [1, 1], [0, 1]], "junk", 0.15),
            ([[0, 0], [1, 0], [1, 1], [0, 1]], "garbage", 0.05),
        ]

        with patch("app.services.ocr._get_reader", return_value=mock_reader):
            svc = OCRService()
            result = await svc.extract_text(Path("/tmp/noisy.png"))

        assert result == ""

    async def test_custom_languages_passed(self):
        mock_reader = MagicMock()
        mock_reader.readtext.return_value = [
            ([[0, 0], [1, 0], [1, 1], [0, 1]], "Bonjour", 0.90),
        ]

        with patch("app.services.ocr._get_reader", return_value=mock_reader) as mock_get:
            svc = OCRService()
            result = await svc.extract_text(Path("/tmp/fr.png"), languages=["fr"])

        mock_get.assert_called_once_with(["fr"])
        assert result == "Bonjour"


# =============================================================================
# OCRService.extract_structured
# =============================================================================


class TestExtractStructured:
    """Test structured extraction with bounding boxes."""

    async def test_returns_structured_data(self):
        mock_reader = MagicMock()
        mock_reader.readtext.return_value = [
            ([[10, 20], [100, 20], [100, 50], [10, 50]], "Invoice", 0.97),
            ([[10, 60], [100, 60], [100, 80], [10, 80]], "Total", 0.85),
            ([[10, 90], [100, 90], [100, 110], [10, 110]], "x", 0.1),  # filtered
        ]

        with patch("app.services.ocr._get_reader", return_value=mock_reader):
            svc = OCRService()
            result = await svc.extract_structured(Path("/tmp/invoice.png"))

        assert len(result) == 2
        assert result[0]["text"] == "Invoice"
        assert result[0]["confidence"] == 0.97
        assert isinstance(result[0]["bbox"], list)
        assert len(result[0]["bbox"]) == 4

    async def test_empty_results(self):
        mock_reader = MagicMock()
        mock_reader.readtext.return_value = []

        with patch("app.services.ocr._get_reader", return_value=mock_reader):
            svc = OCRService()
            result = await svc.extract_structured(Path("/tmp/blank.png"))

        assert result == []

    async def test_bbox_values_are_floats(self):
        mock_reader = MagicMock()
        mock_reader.readtext.return_value = [
            ([[10, 20], [100, 20], [100, 50], [10, 50]], "Text", 0.9),
        ]

        with patch("app.services.ocr._get_reader", return_value=mock_reader):
            svc = OCRService()
            result = await svc.extract_structured(Path("/tmp/t.png"))

        for point in result[0]["bbox"]:
            for val in point:
                assert isinstance(val, float)


# =============================================================================
# Module-level singleton
# =============================================================================


class TestSingleton:
    def test_module_level_instance(self):
        from app.services.ocr import ocr_service

        assert isinstance(ocr_service, OCRService)

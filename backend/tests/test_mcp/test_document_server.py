"""Tests for app.mcp.servers.document_server — MCP server for document tools."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.mcp.servers.document_server import (
    document_info,
    extract_tables,
    extract_text_ocr,
    parse_document,
    supported_formats,
)


# =============================================================================
# parse_document
# =============================================================================


class TestParseDocument:
    """Test the parse_document MCP tool."""

    async def test_successful_parse(self, tmp_path):
        test_file = tmp_path / "report.txt"
        test_file.write_text("Hello world. " * 100)

        mock_parsed = MagicMock()
        mock_parsed.text = "Hello world. " * 100
        mock_parsed.word_count = 200
        mock_parsed.page_count = 1
        mock_parsed.tables = []
        mock_parsed.metadata = {"source": "report.txt"}

        with patch(
            "app.services.document_parser.document_parser_service.parse",
            new_callable=AsyncMock,
            return_value=mock_parsed,
        ):
            result = await parse_document(str(test_file))

        data = json.loads(result)
        assert data["word_count"] == 200
        assert data["page_count"] == 1
        assert data["table_count"] == 0

    async def test_file_not_found(self):
        result = await parse_document("/nonexistent/file.txt")
        assert "File not found" in result

    async def test_unsupported_format(self, tmp_path):
        test_file = tmp_path / "data.xyz"
        test_file.write_text("content")

        result = await parse_document(str(test_file))
        assert "Unsupported" in result

    async def test_truncation_of_long_text(self, tmp_path):
        test_file = tmp_path / "long.txt"
        test_file.write_text("x" * 10000)

        mock_parsed = MagicMock()
        mock_parsed.text = "x" * 10000
        mock_parsed.word_count = 10000
        mock_parsed.page_count = 1
        mock_parsed.tables = []
        mock_parsed.metadata = {}

        with patch(
            "app.services.document_parser.document_parser_service.parse",
            new_callable=AsyncMock,
            return_value=mock_parsed,
        ):
            result = await parse_document(str(test_file))

        data = json.loads(result)
        assert data["truncated"] is True
        assert data["total_characters"] == 10000
        assert len(data["text"]) == 5000

    async def test_parse_error(self, tmp_path):
        test_file = tmp_path / "corrupt.pdf"
        test_file.write_text("not really a pdf")

        with patch(
            "app.services.document_parser.document_parser_service.parse",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Corrupt file"),
        ):
            result = await parse_document(str(test_file))

        assert "Parse error" in result


# =============================================================================
# extract_text_ocr
# =============================================================================


class TestExtractTextOcr:
    """Test the extract_text_ocr MCP tool."""

    async def test_successful_ocr(self, tmp_path):
        test_file = tmp_path / "invoice.png"
        test_file.write_bytes(b"\x89PNG")  # Fake image

        with patch(
            "app.services.ocr.ocr_service.extract_text",
            new_callable=AsyncMock,
            return_value="Invoice #123\nTotal: $500",
        ):
            result = await extract_text_ocr(str(test_file))

        assert "Invoice" in result
        assert "$500" in result

    async def test_file_not_found(self):
        result = await extract_text_ocr("/nonexistent/image.png")
        assert "File not found" in result

    async def test_no_text_detected(self, tmp_path):
        test_file = tmp_path / "blank.png"
        test_file.write_bytes(b"\x89PNG")

        with patch(
            "app.services.ocr.ocr_service.extract_text",
            new_callable=AsyncMock,
            return_value="",
        ):
            result = await extract_text_ocr(str(test_file))

        assert "No text detected" in result

    async def test_ocr_error(self, tmp_path):
        test_file = tmp_path / "bad.png"
        test_file.write_bytes(b"\x89PNG")

        with patch(
            "app.services.ocr.ocr_service.extract_text",
            new_callable=AsyncMock,
            side_effect=RuntimeError("OCR engine failed"),
        ):
            result = await extract_text_ocr(str(test_file))

        assert "OCR error" in result


# =============================================================================
# extract_tables
# =============================================================================


class TestExtractTables:
    """Test the extract_tables MCP tool."""

    async def test_tables_found(self, tmp_path):
        test_file = tmp_path / "data.csv"
        test_file.write_text("a,b\n1,2")

        mock_parsed = MagicMock()
        mock_parsed.tables = [{"headers": ["a", "b"], "rows": [["1", "2"]]}]

        with patch(
            "app.services.document_parser.document_parser_service.parse",
            new_callable=AsyncMock,
            return_value=mock_parsed,
        ):
            result = await extract_tables(str(test_file))

        data = json.loads(result)
        assert len(data) == 1
        assert data[0]["headers"] == ["a", "b"]

    async def test_no_tables(self, tmp_path):
        test_file = tmp_path / "plain.txt"
        test_file.write_text("no tables here")

        mock_parsed = MagicMock()
        mock_parsed.tables = []

        with patch(
            "app.services.document_parser.document_parser_service.parse",
            new_callable=AsyncMock,
            return_value=mock_parsed,
        ):
            result = await extract_tables(str(test_file))

        assert "No tables" in result

    async def test_file_not_found(self):
        result = await extract_tables("/nonexistent/file.csv")
        assert "File not found" in result

    async def test_unsupported_format(self, tmp_path):
        test_file = tmp_path / "file.xyz"
        test_file.write_text("content")
        result = await extract_tables(str(test_file))
        assert "Unsupported" in result

    async def test_extraction_error(self, tmp_path):
        test_file = tmp_path / "bad.csv"
        test_file.write_text("a,b")

        with patch(
            "app.services.document_parser.document_parser_service.parse",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Parse failed"),
        ):
            result = await extract_tables(str(test_file))

        assert "extraction error" in result.lower()


# =============================================================================
# document_info
# =============================================================================


class TestDocumentInfo:
    """Test the document_info MCP tool."""

    async def test_returns_file_info(self, tmp_path):
        test_file = tmp_path / "report.pdf"
        test_file.write_text("fake pdf content" * 100)

        result = await document_info(str(test_file))
        data = json.loads(result)

        assert data["filename"] == "report.pdf"
        assert data["extension"] == ".pdf"
        assert data["size_bytes"] > 0
        assert data["format"] == "pdf"

    async def test_file_not_found(self):
        result = await document_info("/nonexistent/file.pdf")
        assert "File not found" in result

    async def test_unknown_format(self, tmp_path):
        test_file = tmp_path / "data.xyz"
        test_file.write_text("content")

        result = await document_info(str(test_file))
        data = json.loads(result)

        assert data["format"] == "unknown"

    async def test_image_format(self, tmp_path):
        test_file = tmp_path / "photo.png"
        test_file.write_bytes(b"\x89PNG")

        result = await document_info(str(test_file))
        data = json.loads(result)

        assert data["format"] == "png"
        assert data["is_image"] is True
        assert data["is_office"] is False


# =============================================================================
# supported_formats (MCP resource)
# =============================================================================


class TestSupportedFormats:
    """Test the supported_formats resource."""

    async def test_returns_all_formats(self):
        result = await supported_formats()
        data = json.loads(result)

        assert isinstance(data, list)
        assert len(data) > 0

        format_names = [f["name"] for f in data]
        assert "pdf" in format_names
        assert "docx" in format_names
        assert "png" in format_names

    async def test_format_properties(self):
        result = await supported_formats()
        data = json.loads(result)

        for fmt in data:
            assert "name" in fmt
            assert "is_image" in fmt
            assert "is_office" in fmt

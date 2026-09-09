"""Tests for document_tools — parsing, OCR, table extraction, info.

Covers:
  - parse_document_file (async helper)
  - extract_text_with_ocr (async helper)
  - chunk_document (sync helper)
  - document_parse_tool
  - document_ocr_tool
  - document_extract_tables_tool
  - document_info_tool
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# =============================================================================
# Helper: fake ParsedDocument
# =============================================================================


def _make_parsed(
    text: str = "Hello world",
    tables: list | None = None,
    page_count: int | None = 1,
    word_count: int = 2,
    metadata: dict | None = None,
) -> MagicMock:
    parsed = MagicMock()
    parsed.text = text
    parsed.tables = tables or []
    parsed.page_count = page_count
    parsed.word_count = word_count
    parsed.metadata = metadata or {"format": "text"}
    return parsed


# =============================================================================
# parse_document_file
# =============================================================================


class TestParseDocumentFile:
    async def test_parses_existing_file(self, tmp_path: Path) -> None:
        f = tmp_path / "doc.txt"
        f.write_text("content")

        with patch("app.tools.document_tools.document_parser_service") as mock_parser:
            mock_parser.parse = AsyncMock(return_value=_make_parsed())
            from app.tools.document_tools import parse_document_file

            result = await parse_document_file(f)
            assert result.text == "Hello world"
            mock_parser.parse.assert_called_once()

    async def test_raises_for_nonexistent_file(self) -> None:
        from app.tools.document_tools import parse_document_file

        with pytest.raises(Exception, match="not found"):
            await parse_document_file(Path("/nonexistent/file.txt"))

    async def test_raises_for_unsupported_extension(self, tmp_path: Path) -> None:
        f = tmp_path / "data.xyz"
        f.write_text("stuff")

        from app.tools.document_tools import parse_document_file

        with pytest.raises(ValueError, match="Unsupported file extension"):
            await parse_document_file(f)


# =============================================================================
# extract_text_with_ocr
# =============================================================================


class TestExtractTextWithOCR:
    async def test_extracts_text(self, tmp_path: Path) -> None:
        img = tmp_path / "image.png"
        img.write_bytes(b"fake png")

        with patch("app.tools.document_tools.ocr_service") as mock_ocr:
            mock_ocr.extract_text = AsyncMock(return_value="Extracted text from image")
            from app.tools.document_tools import extract_text_with_ocr

            result = await extract_text_with_ocr(img)
            assert result == "Extracted text from image"

    async def test_raises_for_nonexistent_image(self) -> None:
        from app.tools.document_tools import extract_text_with_ocr

        with pytest.raises(Exception, match="not found"):
            await extract_text_with_ocr(Path("/nonexistent/image.png"))


# =============================================================================
# chunk_document
# =============================================================================


class TestChunkDocument:
    def test_chunks_text(self) -> None:
        with patch("app.tools.document_tools.document_parser_service") as mock_parser:
            mock_parser.chunk_text = MagicMock(
                return_value=[
                    {"text": "chunk 1", "metadata": {"source": "test"}},
                    {"text": "chunk 2", "metadata": {"source": "test"}},
                ]
            )
            from app.tools.document_tools import chunk_document

            result = chunk_document("full text", metadata={"source": "test"})
            assert len(result) == 2
            mock_parser.chunk_text.assert_called_once_with("full text", {"source": "test"})


# =============================================================================
# document_parse_tool (LangChain tool)
# =============================================================================


class TestDocumentParseTool:
    async def test_parse_returns_text(self, tmp_path: Path) -> None:
        f = tmp_path / "report.txt"
        f.write_text("A long report about things.")

        with patch("app.tools.document_tools.document_parser_service") as mock_parser:
            mock_parser.parse = AsyncMock(
                return_value=_make_parsed(
                    text="A long report about things.",
                    word_count=5,
                    page_count=1,
                )
            )
            from app.tools.document_tools import document_parse_tool

            result = await document_parse_tool.ainvoke({"file_path": str(f)})
            assert "A long report about things." in result
            assert "5 words" in result
            assert "1 page" in result

    async def test_parse_includes_table_count(self, tmp_path: Path) -> None:
        f = tmp_path / "data.csv"
        f.write_text("a,b\n1,2")

        with patch("app.tools.document_tools.document_parser_service") as mock_parser:
            mock_parser.parse = AsyncMock(
                return_value=_make_parsed(
                    text="a,b\n1,2",
                    tables=[{"headers": ["a", "b"], "rows": [["1", "2"]]}],
                    word_count=2,
                )
            )
            from app.tools.document_tools import document_parse_tool

            result = await document_parse_tool.ainvoke({"file_path": str(f)})
            assert "1 table(s) extracted" in result

    async def test_parse_truncates_long_text(self, tmp_path: Path) -> None:
        f = tmp_path / "huge.txt"
        long_text = "x" * 10000
        f.write_text(long_text)

        with patch("app.tools.document_tools.document_parser_service") as mock_parser:
            mock_parser.parse = AsyncMock(return_value=_make_parsed(text=long_text, word_count=1))
            from app.tools.document_tools import document_parse_tool

            result = await document_parse_tool.ainvoke({"file_path": str(f)})
            # Should be capped at 8000 chars of text content
            assert len(result) <= 8200  # 8000 + metadata lines


# =============================================================================
# document_ocr_tool
# =============================================================================


class TestDocumentOCRTool:
    async def test_ocr_returns_text(self, tmp_path: Path) -> None:
        img = tmp_path / "scan.png"
        img.write_bytes(b"fake image")

        with patch("app.tools.document_tools.ocr_service") as mock_ocr:
            mock_ocr.extract_text = AsyncMock(return_value="Invoice #1234")
            from app.tools.document_tools import document_ocr_tool

            result = await document_ocr_tool.ainvoke({"image_path": str(img)})
            assert result == "Invoice #1234"

    async def test_ocr_empty_text(self, tmp_path: Path) -> None:
        img = tmp_path / "blank.png"
        img.write_bytes(b"fake image")

        with patch("app.tools.document_tools.ocr_service") as mock_ocr:
            mock_ocr.extract_text = AsyncMock(return_value="   ")
            from app.tools.document_tools import document_ocr_tool

            result = await document_ocr_tool.ainvoke({"image_path": str(img)})
            assert "No text could be extracted" in result


# =============================================================================
# document_extract_tables_tool
# =============================================================================


class TestDocumentExtractTablesTool:
    async def test_extracts_tables(self, tmp_path: Path) -> None:
        f = tmp_path / "tables.pdf"
        f.write_bytes(b"fake pdf")

        with patch("app.tools.document_tools.document_parser_service") as mock_parser:
            mock_parser.parse = AsyncMock(
                return_value=_make_parsed(
                    tables=[
                        {
                            "headers": ["Name", "Age"],
                            "rows": [["Alice", "30"], ["Bob", "25"]],
                            "page": 1,
                        },
                        {
                            "headers": ["Product", "Price"],
                            "rows": [["Widget", "$10"]],
                            "sheet": "Sheet1",
                        },
                    ],
                )
            )
            from app.tools.document_tools import document_extract_tables_tool

            result = await document_extract_tables_tool.ainvoke({"file_path": str(f)})
            assert "Table 1" in result
            assert "Page 1" in result
            assert "Alice" in result
            assert "Table 2" in result
            assert "Sheet1" in result

    async def test_no_tables_found(self, tmp_path: Path) -> None:
        f = tmp_path / "text.txt"
        f.write_text("just text")

        with patch("app.tools.document_tools.document_parser_service") as mock_parser:
            mock_parser.parse = AsyncMock(return_value=_make_parsed(text="just text", tables=[]))
            from app.tools.document_tools import document_extract_tables_tool

            result = await document_extract_tables_tool.ainvoke({"file_path": str(f)})
            assert "No tables found" in result

    async def test_table_rows_truncated(self, tmp_path: Path) -> None:
        f = tmp_path / "big_table.csv"
        f.write_text("col\n" + "\n".join(f"row{i}" for i in range(30)))

        rows = [[f"row{i}"] for i in range(30)]
        with patch("app.tools.document_tools.document_parser_service") as mock_parser:
            mock_parser.parse = AsyncMock(
                return_value=_make_parsed(
                    tables=[{"headers": ["col"], "rows": rows}],
                )
            )
            from app.tools.document_tools import document_extract_tables_tool

            result = await document_extract_tables_tool.ainvoke({"file_path": str(f)})
            assert "30 total rows" in result


# =============================================================================
# document_info_tool
# =============================================================================


class TestDocumentInfoTool:
    async def test_returns_file_info(self, tmp_path: Path) -> None:
        f = tmp_path / "report.txt"
        f.write_text("Some content for the file")

        with patch("app.tools.document_tools.document_parser_service") as mock_parser:
            mock_parser.parse = AsyncMock(
                return_value=_make_parsed(
                    text="Some content for the file",
                    word_count=5,
                    page_count=2,
                    tables=[{"headers": [], "rows": []}],
                    metadata={"format": "text"},
                )
            )
            from app.tools.document_tools import document_info_tool

            result = await document_info_tool.ainvoke({"file_path": str(f)})
            assert "report.txt" in result
            assert "KB" in result
            assert "Word count: 5" in result
            assert "Pages: 2" in result
            assert "Tables: 1" in result

    async def test_returns_not_found_for_missing_file(self) -> None:
        from app.tools.document_tools import document_info_tool

        result = await document_info_tool.ainvoke({"file_path": "/nonexistent/file.txt"})
        assert "not found" in result.lower()


# =============================================================================
# Tools list export
# =============================================================================


class TestDocumentToolsExport:
    def test_document_tools_list(self) -> None:
        from app.tools.document_tools import document_tools

        assert len(document_tools) == 4
        names = {t.name for t in document_tools}
        assert names == {
            "document_parse_tool",
            "document_ocr_tool",
            "document_extract_tables_tool",
            "document_info_tool",
        }

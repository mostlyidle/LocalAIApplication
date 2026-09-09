"""Tests for document parser service — multi-format parsing and chunking.

Targets app/services/document_parser.py for 18% → 80%+ coverage.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.middleware.error_handler import DocumentParseError, UnsupportedFormatError
from app.models.enums import DocumentFormat
from app.services.document_parser import DocumentParserService, ParsedDocument


# =============================================================================
# ParsedDocument
# =============================================================================


class TestParsedDocument:
    """Tests for the ParsedDocument value object."""

    def test_basic_attributes(self):
        """ParsedDocument stores text, tables, metadata, page_count."""
        doc = ParsedDocument(text="Hello world", page_count=3)
        assert doc.text == "Hello world"
        assert doc.tables == []
        assert doc.metadata == {}
        assert doc.page_count == 3

    def test_word_count(self):
        """word_count property splits on whitespace."""
        doc = ParsedDocument(text="one two three four")
        assert doc.word_count == 4

    def test_word_count_empty(self):
        """Empty text returns 0 (splitting '' yields [])."""
        doc = ParsedDocument(text="")
        assert doc.word_count == 0

    def test_tables_and_metadata(self):
        """Non-default tables and metadata are preserved."""
        doc = ParsedDocument(
            text="data",
            tables=[{"headers": ["A"], "rows": [["1"]]}],
            metadata={"source": "test.csv"},
        )
        assert len(doc.tables) == 1
        assert doc.metadata["source"] == "test.csv"


# =============================================================================
# chunk_text
# =============================================================================


class TestChunkText:
    """Tests for DocumentParserService.chunk_text()."""

    def test_short_text_single_chunk(self):
        """Text shorter than chunk_size produces one chunk."""
        parser = DocumentParserService()
        result = parser.chunk_text("Short text")
        assert len(result) == 1
        assert result[0]["text"] == "Short text"
        assert result[0]["metadata"]["chunk_index"] == 0

    def test_preserves_metadata(self):
        """Base metadata is attached to each chunk."""
        parser = DocumentParserService()
        meta = {"source": "doc.pdf", "format": "pdf"}
        result = parser.chunk_text("Some text content", metadata=meta)
        assert result[0]["metadata"]["source"] == "doc.pdf"
        assert result[0]["metadata"]["format"] == "pdf"

    def test_long_text_multiple_chunks(self):
        """Text longer than chunk_size is split into multiple chunks."""
        parser = DocumentParserService()
        # Create text that will exceed default chunk_size=1000
        long_text = "word " * 500  # ~2500 chars
        result = parser.chunk_text(long_text)
        assert len(result) >= 2
        # All chunks should have sequential indices
        for i, chunk in enumerate(result):
            assert chunk["metadata"]["chunk_index"] == i

    def test_empty_metadata_default(self):
        """None metadata defaults to empty dict base."""
        parser = DocumentParserService()
        result = parser.chunk_text("text")
        assert "chunk_index" in result[0]["metadata"]


# =============================================================================
# parse() — routing
# =============================================================================


class TestParseRouting:
    """Tests for the parse() method routing to format-specific handlers."""

    async def test_routes_to_text_parser(self, tmp_path: Path):
        """TEXT format routes to _parse_text."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Hello from text file")
        parser = DocumentParserService()
        result = await parser.parse(test_file, DocumentFormat.TEXT)
        assert "Hello from text file" in result.text
        assert result.metadata["format"] == "text"

    async def test_routes_to_markdown_parser(self, tmp_path: Path):
        """MARKDOWN format routes to _parse_text with markdown format."""
        test_file = tmp_path / "test.md"
        test_file.write_text("# Heading\n\nParagraph")
        parser = DocumentParserService()
        result = await parser.parse(test_file, DocumentFormat.MARKDOWN)
        assert "Heading" in result.text
        assert result.metadata["format"] == "markdown"

    async def test_routes_to_csv_parser(self, tmp_path: Path):
        """CSV format routes to _parse_csv."""
        test_file = tmp_path / "data.csv"
        with open(test_file, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["name", "age"])
            writer.writerow(["Alice", "30"])
            writer.writerow(["Bob", "25"])
        parser = DocumentParserService()
        result = await parser.parse(test_file, DocumentFormat.CSV)
        assert "name" in result.text
        assert "Alice" in result.text
        assert len(result.tables) == 1
        assert result.tables[0]["headers"] == ["name", "age"]
        assert result.metadata["row_count"] == 2

    async def test_routes_to_html_parser(self, tmp_path: Path):
        """HTML format routes to _parse_html."""
        test_file = tmp_path / "page.html"
        test_file.write_text(
            "<html><head><title>Test</title></head>"
            "<body><p>Hello HTML</p><script>evil();</script></body></html>"
        )
        parser = DocumentParserService()
        result = await parser.parse(test_file, DocumentFormat.HTML)
        assert "Hello HTML" in result.text
        assert "evil" not in result.text  # script removed
        assert result.metadata["title"] == "Test"

    async def test_routes_to_image_parser(self):
        """Image format returns placeholder text with OCR metadata."""
        parser = DocumentParserService()
        fake_path = Path("/tmp/photo.png")
        result = await parser.parse(fake_path, DocumentFormat.PNG)
        assert "[Image file: photo.png]" in result.text
        assert result.metadata["requires_ocr"] is True

    async def test_pdf_routes_to_pdf_parser(self):
        """PDF format calls _parse_pdf."""
        parser = DocumentParserService()
        with patch.object(parser, "_parse_pdf", new_callable=AsyncMock) as mock_parse:
            mock_parse.return_value = ParsedDocument(text="pdf content", page_count=5)
            result = await parser.parse(Path("/tmp/doc.pdf"), DocumentFormat.PDF)
        assert result.text == "pdf content"
        mock_parse.assert_awaited_once()

    async def test_docx_routes_to_docx_parser(self):
        """DOCX format calls _parse_docx."""
        parser = DocumentParserService()
        with patch.object(parser, "_parse_docx", new_callable=AsyncMock) as mock_parse:
            mock_parse.return_value = ParsedDocument(text="docx content")
            result = await parser.parse(Path("/tmp/doc.docx"), DocumentFormat.DOCX)
        assert result.text == "docx content"

    async def test_xlsx_routes_to_xlsx_parser(self):
        """XLSX format calls _parse_xlsx."""
        parser = DocumentParserService()
        with patch.object(parser, "_parse_xlsx", new_callable=AsyncMock) as mock_parse:
            mock_parse.return_value = ParsedDocument(text="xlsx content")
            result = await parser.parse(Path("/tmp/doc.xlsx"), DocumentFormat.XLSX)
        assert result.text == "xlsx content"

    async def test_pptx_routes_to_pptx_parser(self):
        """PPTX format calls _parse_pptx."""
        parser = DocumentParserService()
        with patch.object(parser, "_parse_pptx", new_callable=AsyncMock) as mock_parse:
            mock_parse.return_value = ParsedDocument(text="pptx content")
            result = await parser.parse(Path("/tmp/doc.pptx"), DocumentFormat.PPTX)
        assert result.text == "pptx content"

    async def test_parse_wraps_unexpected_errors(self, tmp_path: Path):
        """Unexpected exceptions are wrapped in DocumentParseError."""
        parser = DocumentParserService()
        with patch.object(
            parser, "_parse_pdf", new_callable=AsyncMock, side_effect=RuntimeError("boom")
        ):
            with pytest.raises(DocumentParseError) as exc_info:
                await parser.parse(Path("/tmp/doc.pdf"), DocumentFormat.PDF)
            assert "boom" in str(exc_info.value)

    async def test_parse_re_raises_document_parse_error(self):
        """DocumentParseError is not double-wrapped."""
        parser = DocumentParserService()
        original = DocumentParseError("already wrapped")
        with patch.object(parser, "_parse_pdf", new_callable=AsyncMock, side_effect=original):
            with pytest.raises(DocumentParseError) as exc_info:
                await parser.parse(Path("/tmp/doc.pdf"), DocumentFormat.PDF)
            assert exc_info.value is original

    async def test_parse_re_raises_unsupported_format_error(self):
        """UnsupportedFormatError is not wrapped."""
        parser = DocumentParserService()
        original = UnsupportedFormatError("xyz")
        with patch.object(parser, "_parse_pdf", new_callable=AsyncMock, side_effect=original):
            with pytest.raises(UnsupportedFormatError) as exc_info:
                await parser.parse(Path("/tmp/doc.pdf"), DocumentFormat.PDF)
            assert exc_info.value is original


# =============================================================================
# _parse_text
# =============================================================================


class TestParseText:
    """Tests for the plain text / markdown parser."""

    async def test_parse_plain_text(self, tmp_path: Path):
        """Plain .txt file is read and returned."""
        f = tmp_path / "readme.txt"
        f.write_text("Line 1\nLine 2\nLine 3")
        parser = DocumentParserService()
        result = await parser._parse_text(f)
        assert result.text == "Line 1\nLine 2\nLine 3"
        assert result.metadata["format"] == "text"
        assert result.metadata["filename"] == "readme.txt"

    async def test_parse_markdown_file(self, tmp_path: Path):
        """Markdown file is read and format set to 'markdown'."""
        f = tmp_path / "notes.md"
        f.write_text("# Title\n\nContent here")
        parser = DocumentParserService()
        result = await parser._parse_text(f)
        assert result.metadata["format"] == "markdown"


# =============================================================================
# _parse_csv
# =============================================================================


class TestParseCsv:
    """Tests for CSV parsing."""

    async def test_parse_csv_with_headers_and_rows(self, tmp_path: Path):
        """CSV with data produces text and table."""
        f = tmp_path / "data.csv"
        with open(f, "w", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(["id", "name", "value"])
            writer.writerow(["1", "alpha", "100"])
            writer.writerow(["2", "beta", "200"])

        parser = DocumentParserService()
        result = await parser._parse_csv(f)
        assert "id | name | value" in result.text
        assert "alpha" in result.text
        assert len(result.tables) == 1
        assert result.tables[0]["headers"] == ["id", "name", "value"]
        assert len(result.tables[0]["rows"]) == 2

    async def test_parse_empty_csv(self, tmp_path: Path):
        """Empty CSV returns empty text."""
        f = tmp_path / "empty.csv"
        f.write_text("")
        parser = DocumentParserService()
        result = await parser._parse_csv(f)
        assert result.text == ""

    async def test_parse_csv_with_semicolons(self, tmp_path: Path):
        """CSV with semicolon delimiters is handled by Sniffer."""
        f = tmp_path / "semi.csv"
        f.write_text("name;age\nAlice;30\nBob;25\n")
        parser = DocumentParserService()
        result = await parser._parse_csv(f)
        assert "Alice" in result.text


# =============================================================================
# _parse_html
# =============================================================================


class TestParseHtml:
    """Tests for HTML parsing."""

    async def test_strips_script_and_style(self, tmp_path: Path):
        """Scripts, styles, nav, footer, header are removed."""
        html = """
        <html>
        <head><style>body { color: red; }</style></head>
        <body>
        <header>Nav here</header>
        <p>Good content</p>
        <script>alert('xss');</script>
        <footer>Footer</footer>
        </body>
        </html>
        """
        f = tmp_path / "page.html"
        f.write_text(html)
        parser = DocumentParserService()
        result = await parser._parse_html(f)
        assert "Good content" in result.text
        assert "alert" not in result.text
        assert "color: red" not in result.text

    async def test_extracts_title(self, tmp_path: Path):
        """Page title is extracted into metadata."""
        html = "<html><head><title>My Page</title></head><body><p>Hi</p></body></html>"
        f = tmp_path / "titled.html"
        f.write_text(html)
        parser = DocumentParserService()
        result = await parser._parse_html(f)
        assert result.metadata["title"] == "My Page"

    async def test_no_title(self, tmp_path: Path):
        """Page without title sets None."""
        html = "<html><body><p>No title</p></body></html>"
        f = tmp_path / "notitle.html"
        f.write_text(html)
        parser = DocumentParserService()
        result = await parser._parse_html(f)
        assert result.metadata["title"] is None


# =============================================================================
# _parse_image
# =============================================================================


class TestParseImage:
    """Tests for image file handling."""

    async def test_returns_placeholder_text(self):
        """Image returns placeholder with requires_ocr flag."""
        parser = DocumentParserService()
        result = await parser._parse_image(Path("/images/scan.jpg"))
        assert "[Image file: scan.jpg]" in result.text
        assert result.metadata["requires_ocr"] is True
        assert result.metadata["format"] == "jpg"

    async def test_handles_different_extensions(self):
        """Various image extensions set correct format."""
        parser = DocumentParserService()
        for ext, expected_fmt in [("png", "png"), ("tiff", "tiff"), ("bmp", "bmp")]:
            result = await parser._parse_image(Path(f"/img/file.{ext}"))
            assert result.metadata["format"] == expected_fmt


# =============================================================================
# parse() — UnsupportedFormatError (line 100)
# =============================================================================


class TestUnsupportedFormatElseBranch:
    """Test the else branch in parse() that raises UnsupportedFormatError."""

    async def test_unsupported_format_raises(self):
        """A format not matched by any branch raises UnsupportedFormatError."""
        parser = DocumentParserService()
        # Create a fake format that won't match any if/elif branch.
        # We need it to be string-like (for structlog) but not equal to any real enum member.
        fake_format = MagicMock()
        fake_format.value = "unknown_format"
        fake_format.is_image = False
        fake_format.__str__ = lambda self: "unknown_format"
        fake_format.__repr__ = lambda self: "unknown_format"
        fake_format.__eq__ = lambda self, other: False
        fake_format.__hash__ = lambda self: hash("unknown_format_fake")
        # The `in` check for (DocumentFormat.DOCX,) etc. uses __eq__ which always returns False
        with pytest.raises(UnsupportedFormatError):
            await parser.parse(Path("/tmp/file.xyz"), fake_format)


# =============================================================================
# _parse_pdf (lines 142-182)
# =============================================================================


class TestParsePdf:
    """Tests for PDF parsing with mocked fitz and pdfplumber."""

    async def test_parse_pdf_basic(self):
        """PDF text is extracted from pages and tables from pdfplumber."""
        import sys

        # Mock fitz (PyMuPDF)
        mock_page = MagicMock()
        mock_page.get_text.return_value = "Page 1 text"

        mock_doc = MagicMock()
        mock_doc.__iter__ = MagicMock(return_value=iter([mock_page]))

        mock_fitz = MagicMock()
        mock_fitz.open.return_value = mock_doc

        # Mock pdfplumber
        mock_pdfplumber_page = MagicMock()
        mock_pdfplumber_page.extract_tables.return_value = [
            [["Header1", "Header2"], ["val1", "val2"]]
        ]

        mock_pdf_context = MagicMock()
        mock_pdf_context.pages = [mock_pdfplumber_page]
        mock_pdf_context.__enter__ = MagicMock(return_value=mock_pdf_context)
        mock_pdf_context.__exit__ = MagicMock(return_value=False)

        mock_pdfplumber = MagicMock()
        mock_pdfplumber.open.return_value = mock_pdf_context

        with patch.dict(sys.modules, {"fitz": mock_fitz, "pdfplumber": mock_pdfplumber}):
            parser = DocumentParserService()
            result = await parser._parse_pdf(Path("/fake/test.pdf"))

        assert "Page 1 text" in result.text
        assert len(result.tables) == 1
        assert result.tables[0]["headers"] == ["Header1", "Header2"]
        assert result.tables[0]["rows"] == [["val1", "val2"]]
        assert result.tables[0]["page"] == 1
        assert result.page_count == 1
        assert result.metadata["format"] == "pdf"
        assert result.metadata["filename"] == "test.pdf"

    async def test_parse_pdf_multiple_pages(self):
        """Multiple PDF pages are joined with double newlines."""
        import sys

        mock_page1 = MagicMock()
        mock_page1.get_text.return_value = "First page"
        mock_page2 = MagicMock()
        mock_page2.get_text.return_value = "Second page"

        mock_doc = MagicMock()
        mock_doc.__iter__ = MagicMock(return_value=iter([mock_page1, mock_page2]))

        mock_fitz = MagicMock()
        mock_fitz.open.return_value = mock_doc

        # pdfplumber with no tables
        mock_pp_page1 = MagicMock()
        mock_pp_page1.extract_tables.return_value = []
        mock_pp_page2 = MagicMock()
        mock_pp_page2.extract_tables.return_value = []

        mock_pdf_context = MagicMock()
        mock_pdf_context.pages = [mock_pp_page1, mock_pp_page2]
        mock_pdf_context.__enter__ = MagicMock(return_value=mock_pdf_context)
        mock_pdf_context.__exit__ = MagicMock(return_value=False)

        mock_pdfplumber = MagicMock()
        mock_pdfplumber.open.return_value = mock_pdf_context

        with patch.dict(sys.modules, {"fitz": mock_fitz, "pdfplumber": mock_pdfplumber}):
            parser = DocumentParserService()
            result = await parser._parse_pdf(Path("/fake/multi.pdf"))

        assert "First page" in result.text
        assert "Second page" in result.text
        assert result.page_count == 2
        assert result.tables == []

    async def test_parse_pdf_table_extraction_failure_graceful(self):
        """If pdfplumber fails, text is still returned and tables are empty."""
        import sys

        mock_page = MagicMock()
        mock_page.get_text.return_value = "Text content"

        mock_doc = MagicMock()
        mock_doc.__iter__ = MagicMock(return_value=iter([mock_page]))

        mock_fitz = MagicMock()
        mock_fitz.open.return_value = mock_doc

        # pdfplumber raises an exception
        mock_pdfplumber = MagicMock()
        mock_pdfplumber.open.side_effect = RuntimeError("pdfplumber broken")

        with patch.dict(sys.modules, {"fitz": mock_fitz, "pdfplumber": mock_pdfplumber}):
            parser = DocumentParserService()
            result = await parser._parse_pdf(Path("/fake/broken_tables.pdf"))

        assert "Text content" in result.text
        assert result.tables == []
        assert result.page_count == 1

    async def test_parse_pdf_table_with_none_cells(self):
        """None cells in tables are converted to empty strings."""
        import sys

        mock_page = MagicMock()
        mock_page.get_text.return_value = "Page text"

        mock_doc = MagicMock()
        mock_doc.__iter__ = MagicMock(return_value=iter([mock_page]))

        mock_fitz = MagicMock()
        mock_fitz.open.return_value = mock_doc

        # pdfplumber with None cells
        mock_pp_page = MagicMock()
        mock_pp_page.extract_tables.return_value = [[[None, "Col2"], ["data1", None]]]

        mock_pdf_context = MagicMock()
        mock_pdf_context.pages = [mock_pp_page]
        mock_pdf_context.__enter__ = MagicMock(return_value=mock_pdf_context)
        mock_pdf_context.__exit__ = MagicMock(return_value=False)

        mock_pdfplumber = MagicMock()
        mock_pdfplumber.open.return_value = mock_pdf_context

        with patch.dict(sys.modules, {"fitz": mock_fitz, "pdfplumber": mock_pdfplumber}):
            parser = DocumentParserService()
            result = await parser._parse_pdf(Path("/fake/nullcells.pdf"))

        assert result.tables[0]["headers"] == ["", "Col2"]
        assert result.tables[0]["rows"] == [["data1", ""]]

    async def test_parse_pdf_single_row_table_skipped(self):
        """Tables with only a header row (len <= 1) are skipped."""
        import sys

        mock_page = MagicMock()
        mock_page.get_text.return_value = "Page"

        mock_doc = MagicMock()
        mock_doc.__iter__ = MagicMock(return_value=iter([mock_page]))

        mock_fitz = MagicMock()
        mock_fitz.open.return_value = mock_doc

        mock_pp_page = MagicMock()
        mock_pp_page.extract_tables.return_value = [
            [["OnlyHeader"]],  # single row, should be skipped
        ]

        mock_pdf_context = MagicMock()
        mock_pdf_context.pages = [mock_pp_page]
        mock_pdf_context.__enter__ = MagicMock(return_value=mock_pdf_context)
        mock_pdf_context.__exit__ = MagicMock(return_value=False)

        mock_pdfplumber = MagicMock()
        mock_pdfplumber.open.return_value = mock_pdf_context

        with patch.dict(sys.modules, {"fitz": mock_fitz, "pdfplumber": mock_pdfplumber}):
            parser = DocumentParserService()
            result = await parser._parse_pdf(Path("/fake/singlerow.pdf"))

        assert result.tables == []


# =============================================================================
# _parse_docx (lines 187-214)
# =============================================================================


class TestParseDocx:
    """Tests for DOCX parsing with mocked python-docx."""

    async def test_parse_docx_basic(self):
        """DOCX paragraphs and tables are extracted."""
        import sys

        # Build mock paragraphs
        mock_para1 = MagicMock()
        mock_para1.text = "First paragraph"
        mock_para2 = MagicMock()
        mock_para2.text = "  "  # whitespace-only, should be skipped
        mock_para3 = MagicMock()
        mock_para3.text = "Third paragraph"

        # Build mock table: 2 rows x 2 columns
        mock_cell_00 = MagicMock()
        mock_cell_00.text = " Name "
        mock_cell_01 = MagicMock()
        mock_cell_01.text = " Age "
        mock_cell_10 = MagicMock()
        mock_cell_10.text = " Alice "
        mock_cell_11 = MagicMock()
        mock_cell_11.text = " 30 "

        mock_row0 = MagicMock()
        mock_row0.cells = [mock_cell_00, mock_cell_01]
        mock_row1 = MagicMock()
        mock_row1.cells = [mock_cell_10, mock_cell_11]

        mock_table = MagicMock()
        mock_table.rows = [mock_row0, mock_row1]

        mock_document_instance = MagicMock()
        mock_document_instance.paragraphs = [mock_para1, mock_para2, mock_para3]
        mock_document_instance.tables = [mock_table]

        mock_docx_module = MagicMock()
        mock_docx_module.Document.return_value = mock_document_instance

        with patch.dict(sys.modules, {"docx": mock_docx_module}):
            parser = DocumentParserService()
            result = await parser._parse_docx(Path("/fake/report.docx"))

        assert "First paragraph" in result.text
        assert "Third paragraph" in result.text
        # whitespace-only paragraph should not appear in text
        assert result.text == "First paragraph\n\nThird paragraph"
        assert len(result.tables) == 1
        assert result.tables[0]["headers"] == ["Name", "Age"]
        assert result.tables[0]["rows"] == [["Alice", "30"]]
        assert result.metadata["format"] == "docx"
        assert result.metadata["filename"] == "report.docx"

    async def test_parse_docx_no_tables(self):
        """DOCX with no tables returns empty tables list."""
        import sys

        mock_para = MagicMock()
        mock_para.text = "Just text"

        mock_document_instance = MagicMock()
        mock_document_instance.paragraphs = [mock_para]
        mock_document_instance.tables = []

        mock_docx_module = MagicMock()
        mock_docx_module.Document.return_value = mock_document_instance

        with patch.dict(sys.modules, {"docx": mock_docx_module}):
            parser = DocumentParserService()
            result = await parser._parse_docx(Path("/fake/simple.docx"))

        assert result.text == "Just text"
        assert result.tables == []

    async def test_parse_docx_single_row_table_skipped(self):
        """A table with only one row (header only) is skipped."""
        import sys

        mock_para = MagicMock()
        mock_para.text = "Content"

        mock_cell = MagicMock()
        mock_cell.text = "Header"
        mock_row = MagicMock()
        mock_row.cells = [mock_cell]

        mock_table = MagicMock()
        mock_table.rows = [mock_row]

        mock_document_instance = MagicMock()
        mock_document_instance.paragraphs = [mock_para]
        mock_document_instance.tables = [mock_table]

        mock_docx_module = MagicMock()
        mock_docx_module.Document.return_value = mock_document_instance

        with patch.dict(sys.modules, {"docx": mock_docx_module}):
            parser = DocumentParserService()
            result = await parser._parse_docx(Path("/fake/onerow.docx"))

        assert result.tables == []


# =============================================================================
# _parse_xlsx (lines 219-250)
# =============================================================================


class TestParseXlsx:
    """Tests for XLSX parsing with mocked openpyxl."""

    async def test_parse_xlsx_basic(self):
        """XLSX sheets are extracted as text and tables."""
        import sys

        # Mock worksheet
        mock_ws = MagicMock()
        mock_ws.iter_rows.return_value = [
            ("Name", "Score"),
            ("Alice", 95),
            ("Bob", 87),
        ]

        # Mock workbook
        mock_wb = MagicMock()
        mock_wb.sheetnames = ["Sheet1"]
        mock_wb.__getitem__ = MagicMock(return_value=mock_ws)

        mock_openpyxl = MagicMock()
        mock_openpyxl.load_workbook.return_value = mock_wb

        with patch.dict(sys.modules, {"openpyxl": mock_openpyxl}):
            parser = DocumentParserService()
            result = await parser._parse_xlsx(Path("/fake/data.xlsx"))

        assert "## Sheet: Sheet1" in result.text
        assert "Name | Score" in result.text
        assert "Alice | 95" in result.text
        assert len(result.tables) == 1
        assert result.tables[0]["headers"] == ["Name", "Score"]
        assert result.tables[0]["rows"] == [["Alice", "95"], ["Bob", "87"]]
        assert result.tables[0]["sheet"] == "Sheet1"
        assert result.metadata["format"] == "xlsx"
        assert result.metadata["filename"] == "data.xlsx"

    async def test_parse_xlsx_none_cells(self):
        """None cells in XLSX are converted to empty strings."""
        import sys

        mock_ws = MagicMock()
        mock_ws.iter_rows.return_value = [
            ("Col1", None),
            (None, "value"),
        ]

        mock_wb = MagicMock()
        mock_wb.sheetnames = ["Data"]
        mock_wb.__getitem__ = MagicMock(return_value=mock_ws)

        mock_openpyxl = MagicMock()
        mock_openpyxl.load_workbook.return_value = mock_wb

        with patch.dict(sys.modules, {"openpyxl": mock_openpyxl}):
            parser = DocumentParserService()
            result = await parser._parse_xlsx(Path("/fake/nulls.xlsx"))

        assert result.tables[0]["headers"] == ["Col1", ""]
        assert result.tables[0]["rows"] == [["", "value"]]

    async def test_parse_xlsx_multiple_sheets(self):
        """Multiple sheets are all extracted."""
        import sys

        mock_ws1 = MagicMock()
        mock_ws1.iter_rows.return_value = [("A",), ("1",)]
        mock_ws2 = MagicMock()
        mock_ws2.iter_rows.return_value = [("B",), ("2",)]

        mock_wb = MagicMock()
        mock_wb.sheetnames = ["First", "Second"]
        mock_wb.__getitem__ = MagicMock(
            side_effect=lambda name: {"First": mock_ws1, "Second": mock_ws2}[name]
        )

        mock_openpyxl = MagicMock()
        mock_openpyxl.load_workbook.return_value = mock_wb

        with patch.dict(sys.modules, {"openpyxl": mock_openpyxl}):
            parser = DocumentParserService()
            result = await parser._parse_xlsx(Path("/fake/multi.xlsx"))

        assert "## Sheet: First" in result.text
        assert "## Sheet: Second" in result.text
        assert len(result.tables) == 2
        assert result.tables[0]["sheet"] == "First"
        assert result.tables[1]["sheet"] == "Second"

    async def test_parse_xlsx_single_row_sheet_no_table(self):
        """A sheet with only one row (header) does not produce a table."""
        import sys

        mock_ws = MagicMock()
        mock_ws.iter_rows.return_value = [("OnlyHeader",)]

        mock_wb = MagicMock()
        mock_wb.sheetnames = ["Lonely"]
        mock_wb.__getitem__ = MagicMock(return_value=mock_ws)

        mock_openpyxl = MagicMock()
        mock_openpyxl.load_workbook.return_value = mock_wb

        with patch.dict(sys.modules, {"openpyxl": mock_openpyxl}):
            parser = DocumentParserService()
            result = await parser._parse_xlsx(Path("/fake/single.xlsx"))

        assert result.tables == []
        assert "OnlyHeader" in result.text


# =============================================================================
# _parse_pptx (lines 255-281)
# =============================================================================


class TestParsePptx:
    """Tests for PPTX parsing with mocked python-pptx."""

    async def test_parse_pptx_basic(self):
        """PPTX slides with text frames are extracted."""
        import sys

        # Build mock paragraphs
        mock_paragraph1 = MagicMock()
        mock_paragraph1.text = "Slide Title"
        mock_paragraph2 = MagicMock()
        mock_paragraph2.text = "Bullet point"
        mock_paragraph_empty = MagicMock()
        mock_paragraph_empty.text = "   "  # whitespace, should be skipped

        mock_text_frame = MagicMock()
        mock_text_frame.paragraphs = [mock_paragraph1, mock_paragraph2, mock_paragraph_empty]

        mock_shape = MagicMock()
        mock_shape.has_text_frame = True
        mock_shape.text_frame = mock_text_frame

        mock_slide = MagicMock()
        mock_slide.shapes = [mock_shape]

        mock_slides = MagicMock()
        mock_slides.__iter__ = MagicMock(return_value=iter([mock_slide]))
        mock_slides.__len__ = MagicMock(return_value=1)

        mock_presentation = MagicMock()
        mock_presentation.slides = mock_slides

        mock_pptx_module = MagicMock()
        mock_pptx_module.Presentation.return_value = mock_presentation

        with patch.dict(sys.modules, {"pptx": mock_pptx_module}):
            parser = DocumentParserService()
            result = await parser._parse_pptx(Path("/fake/deck.pptx"))

        assert "--- Slide 1 ---" in result.text
        assert "Slide Title" in result.text
        assert "Bullet point" in result.text
        assert result.metadata["format"] == "pptx"
        assert result.metadata["filename"] == "deck.pptx"
        assert result.metadata["slide_count"] == 1
        assert result.page_count == 1

    async def test_parse_pptx_multiple_slides(self):
        """Multiple slides are extracted with correct numbering."""
        import sys

        def make_slide(text: str) -> MagicMock:
            mock_para = MagicMock()
            mock_para.text = text
            mock_tf = MagicMock()
            mock_tf.paragraphs = [mock_para]
            mock_shape = MagicMock()
            mock_shape.has_text_frame = True
            mock_shape.text_frame = mock_tf
            mock_slide = MagicMock()
            mock_slide.shapes = [mock_shape]
            return mock_slide

        slide1 = make_slide("Intro")
        slide2 = make_slide("Conclusion")

        mock_slides = MagicMock()
        mock_slides.__iter__ = MagicMock(return_value=iter([slide1, slide2]))
        mock_slides.__len__ = MagicMock(return_value=2)

        mock_presentation = MagicMock()
        mock_presentation.slides = mock_slides

        mock_pptx_module = MagicMock()
        mock_pptx_module.Presentation.return_value = mock_presentation

        with patch.dict(sys.modules, {"pptx": mock_pptx_module}):
            parser = DocumentParserService()
            result = await parser._parse_pptx(Path("/fake/multi.pptx"))

        assert "--- Slide 1 ---" in result.text
        assert "--- Slide 2 ---" in result.text
        assert "Intro" in result.text
        assert "Conclusion" in result.text
        assert result.page_count == 2

    async def test_parse_pptx_shape_without_text_frame(self):
        """Shapes without text frames are skipped."""
        import sys

        mock_shape_no_text = MagicMock()
        mock_shape_no_text.has_text_frame = False

        mock_shape_with_text = MagicMock()
        mock_shape_with_text.has_text_frame = True
        mock_para = MagicMock()
        mock_para.text = "Only text shape"
        mock_tf = MagicMock()
        mock_tf.paragraphs = [mock_para]
        mock_shape_with_text.text_frame = mock_tf

        mock_slide = MagicMock()
        mock_slide.shapes = [mock_shape_no_text, mock_shape_with_text]

        mock_slides = MagicMock()
        mock_slides.__iter__ = MagicMock(return_value=iter([mock_slide]))
        mock_slides.__len__ = MagicMock(return_value=1)

        mock_presentation = MagicMock()
        mock_presentation.slides = mock_slides

        mock_pptx_module = MagicMock()
        mock_pptx_module.Presentation.return_value = mock_presentation

        with patch.dict(sys.modules, {"pptx": mock_pptx_module}):
            parser = DocumentParserService()
            result = await parser._parse_pptx(Path("/fake/mixed.pptx"))

        assert "Only text shape" in result.text

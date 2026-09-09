"""Multi-format document parsing pipeline."""

from __future__ import annotations

import asyncio
import csv
import io
from pathlib import Path
from typing import Any

import structlog
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.api.middleware.error_handler import DocumentParseError, UnsupportedFormatError
from app.config import settings
from app.models.enums import DocumentFormat

logger = structlog.get_logger(__name__)


class ParsedDocument:
    """Result of parsing a document."""

    def __init__(
        self,
        text: str,
        tables: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
        page_count: int | None = None,
    ) -> None:
        self.text = text
        self.tables = tables or []
        self.metadata = metadata or {}
        self.page_count = page_count

    @property
    def word_count(self) -> int:
        return len(self.text.split())


class DocumentParserService:
    """Parse documents in all supported formats with format-specific handlers.

    Pipeline:
        1. Detect format from file extension (validated against allowed set).
        2. Route to format-specific parser.
        3. Return structured ParsedDocument with text, tables, metadata.

    Design decisions:
        - PyMuPDF for PDFs (fast, reliable, good text extraction).
        - pdfplumber for table extraction from PDFs.
        - python-docx, openpyxl, python-pptx for Office formats.
        - BeautifulSoup for HTML.
        - markdown library for Markdown -> plaintext.
        - Images are returned with metadata for OCR processing downstream.
        - All synchronous file I/O and parsing is offloaded to a thread via
          asyncio.to_thread() to avoid blocking the event loop.
    """

    def __init__(self) -> None:
        self._text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=settings.rag_chunk_size,
            chunk_overlap=settings.rag_chunk_overlap,
            separators=["\n\n", "\n", ". ", " ", ""],
        )

    async def parse(self, file_path: Path, format: DocumentFormat) -> ParsedDocument:
        """Parse a document file and extract text and tables.

        Args:
            file_path: Path to the file on disk.
            format: The detected document format.

        Returns:
            A ParsedDocument with extracted content.

        Raises:
            DocumentParseError: If parsing fails.
            UnsupportedFormatError: If the format has no handler.
        """
        logger.info("parsing_document", path=str(file_path), format=format)
        try:
            if format == DocumentFormat.PDF:
                return await self._parse_pdf(file_path)
            elif format in (DocumentFormat.DOCX,):
                return await self._parse_docx(file_path)
            elif format in (DocumentFormat.XLSX,):
                return await self._parse_xlsx(file_path)
            elif format in (DocumentFormat.PPTX,):
                return await self._parse_pptx(file_path)
            elif format == DocumentFormat.CSV:
                return await self._parse_csv(file_path)
            elif format == DocumentFormat.HTML:
                return await self._parse_html(file_path)
            elif format in (DocumentFormat.MARKDOWN, DocumentFormat.TEXT):
                return await self._parse_text(file_path)
            elif format.is_image:
                return await self._parse_image(file_path)
            else:
                raise UnsupportedFormatError(format.value)
        except (DocumentParseError, UnsupportedFormatError):
            raise
        except Exception as exc:
            logger.error("parse_failed", path=str(file_path), error=str(exc))
            raise DocumentParseError(
                f"Failed to parse {file_path.name}: {exc}",
                details={"filename": file_path.name, "format": format.value},
            ) from exc

    def chunk_text(
        self,
        text: str,
        metadata: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Split text into chunks suitable for embedding.

        Args:
            text: The full document text.
            metadata: Base metadata to attach to each chunk.

        Returns:
            List of dicts with 'text' and 'metadata' keys.
        """
        base_meta = metadata or {}
        docs = self._text_splitter.create_documents(
            [text],
            metadatas=[base_meta],
        )
        return [
            {
                "text": doc.page_content,
                "metadata": {**doc.metadata, "chunk_index": i},
            }
            for i, doc in enumerate(docs)
        ]

    # ── Format-specific parsers ─────────────────────────────────────

    async def _parse_pdf(self, file_path: Path) -> ParsedDocument:
        """Parse PDF using PyMuPDF with pdfplumber for tables."""

        def _sync_parse() -> ParsedDocument:
            import fitz  # PyMuPDF

            doc = fitz.open(str(file_path))
            pages_text: list[str] = []
            for page in doc:
                pages_text.append(page.get_text())

            full_text = "\n\n".join(pages_text)

            # Extract tables with pdfplumber
            tables = []
            try:
                import pdfplumber

                with pdfplumber.open(str(file_path)) as pdf:
                    for page_num, page in enumerate(pdf.pages):
                        page_tables = page.extract_tables()
                        for table in page_tables:
                            if table and len(table) > 1:
                                headers = [str(h or "") for h in table[0]]
                                rows = [[str(c or "") for c in row] for row in table[1:]]
                                tables.append(
                                    {
                                        "page": page_num + 1,
                                        "headers": headers,
                                        "rows": rows,
                                    }
                                )
            except Exception as exc:
                logger.warning("pdf_table_extraction_failed", error=str(exc))

            doc.close()
            return ParsedDocument(
                text=full_text,
                tables=tables,
                metadata={"format": "pdf", "filename": file_path.name},
                page_count=len(pages_text),
            )

        return await asyncio.to_thread(_sync_parse)

    async def _parse_docx(self, file_path: Path) -> ParsedDocument:
        """Parse DOCX using python-docx."""

        def _sync_parse() -> ParsedDocument:
            from docx import Document as DocxDocument

            doc = DocxDocument(str(file_path))
            paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
            full_text = "\n\n".join(paragraphs)

            # Extract tables
            tables = []
            for table in doc.tables:
                rows_data = []
                for row in table.rows:
                    rows_data.append([cell.text.strip() for cell in row.cells])
                if rows_data and len(rows_data) > 1:
                    tables.append(
                        {
                            "headers": rows_data[0],
                            "rows": rows_data[1:],
                        }
                    )

            return ParsedDocument(
                text=full_text,
                tables=tables,
                metadata={"format": "docx", "filename": file_path.name},
            )

        return await asyncio.to_thread(_sync_parse)

    async def _parse_xlsx(self, file_path: Path) -> ParsedDocument:
        """Parse XLSX using openpyxl."""

        def _sync_parse() -> ParsedDocument:
            from openpyxl import load_workbook

            wb = load_workbook(str(file_path), data_only=True)
            all_text: list[str] = []
            tables = []

            for sheet_name in wb.sheetnames:
                ws = wb[sheet_name]
                all_text.append(f"## Sheet: {sheet_name}")
                rows_data = []
                for row in ws.iter_rows(values_only=True):
                    row_strs = [str(c) if c is not None else "" for c in row]
                    rows_data.append(row_strs)
                    all_text.append(" | ".join(row_strs))

                if rows_data and len(rows_data) > 1:
                    tables.append(
                        {
                            "headers": rows_data[0],
                            "rows": rows_data[1:],
                            "sheet": sheet_name,
                        }
                    )

            return ParsedDocument(
                text="\n".join(all_text),
                tables=tables,
                metadata={"format": "xlsx", "filename": file_path.name},
            )

        return await asyncio.to_thread(_sync_parse)

    async def _parse_pptx(self, file_path: Path) -> ParsedDocument:
        """Parse PPTX using python-pptx."""

        def _sync_parse() -> ParsedDocument:
            from pptx import Presentation

            prs = Presentation(str(file_path))
            slides_text: list[str] = []

            for slide_num, slide in enumerate(prs.slides, 1):
                slide_parts = [f"--- Slide {slide_num} ---"]
                for shape in slide.shapes:
                    if shape.has_text_frame:
                        for paragraph in shape.text_frame.paragraphs:
                            text = paragraph.text.strip()
                            if text:
                                slide_parts.append(text)
                slides_text.append("\n".join(slide_parts))

            return ParsedDocument(
                text="\n\n".join(slides_text),
                metadata={
                    "format": "pptx",
                    "filename": file_path.name,
                    "slide_count": len(prs.slides),
                },
                page_count=len(prs.slides),
            )

        return await asyncio.to_thread(_sync_parse)

    async def _parse_csv(self, file_path: Path) -> ParsedDocument:
        """Parse CSV files."""

        def _sync_parse() -> ParsedDocument:
            with open(file_path, newline="", encoding="utf-8-sig") as f:
                # Sniff dialect
                sample = f.read(8192)
                f.seek(0)
                try:
                    dialect = csv.Sniffer().sniff(sample)
                except csv.Error:
                    dialect = csv.excel

                reader = csv.reader(f, dialect)
                rows = list(reader)

            if not rows:
                return ParsedDocument(text="", metadata={"format": "csv"})

            headers = rows[0]
            data_rows = rows[1:]
            text_lines = [" | ".join(headers)]
            for row in data_rows:
                text_lines.append(" | ".join(row))

            tables = [{"headers": headers, "rows": data_rows}]
            return ParsedDocument(
                text="\n".join(text_lines),
                tables=tables,
                metadata={
                    "format": "csv",
                    "filename": file_path.name,
                    "row_count": len(data_rows),
                },
            )

        return await asyncio.to_thread(_sync_parse)

    async def _parse_html(self, file_path: Path) -> ParsedDocument:
        """Parse HTML using BeautifulSoup."""

        def _sync_parse() -> ParsedDocument:
            from bs4 import BeautifulSoup

            with open(file_path, encoding="utf-8") as f:
                soup = BeautifulSoup(f.read(), "html.parser")

            # Remove script and style elements
            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.decompose()

            text = soup.get_text(separator="\n", strip=True)
            title = soup.title.string if soup.title else None

            return ParsedDocument(
                text=text,
                metadata={"format": "html", "filename": file_path.name, "title": title},
            )

        return await asyncio.to_thread(_sync_parse)

    async def _parse_text(self, file_path: Path) -> ParsedDocument:
        """Parse plain text and markdown files."""

        def _sync_parse() -> ParsedDocument:
            with open(file_path, encoding="utf-8") as f:
                text = f.read()

            fmt = "markdown" if file_path.suffix.lower() in (".md", ".markdown") else "text"
            return ParsedDocument(
                text=text,
                metadata={"format": fmt, "filename": file_path.name},
            )

        return await asyncio.to_thread(_sync_parse)

    async def _parse_image(self, file_path: Path) -> ParsedDocument:
        """Handle image files -- returns minimal text, OCR happens downstream."""
        return ParsedDocument(
            text=f"[Image file: {file_path.name}]",
            metadata={
                "format": file_path.suffix.lstrip(".").lower(),
                "filename": file_path.name,
                "requires_ocr": True,
            },
        )


# Module-level singleton
document_parser_service = DocumentParserService()

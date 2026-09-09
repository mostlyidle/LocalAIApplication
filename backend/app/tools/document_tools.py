"""Document tools for parsing, OCR, and structured data extraction.

These tools wrap the DocumentParserService and OCRService for use
by the Document Agent and other LangGraph agents.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import structlog
from langchain_core.tools import tool

from app.api.middleware.error_handler import DocumentParseError, NotFoundError
from app.config import settings
from app.models.enums import DocumentFormat
from app.services.document_parser import ParsedDocument, document_parser_service
from app.services.ocr import ocr_service

logger = structlog.get_logger(__name__)


async def parse_document_file(file_path: Path) -> ParsedDocument:
    """Parse a document from a file path, auto-detecting format.

    Args:
        file_path: Path to the document on disk.

    Returns:
        ParsedDocument with extracted text, tables, and metadata.

    Raises:
        DocumentParseError: If parsing fails.
        ValueError: If the file extension is unsupported.
    """
    if not file_path.exists():
        raise NotFoundError("File", str(file_path))

    ext = file_path.suffix.lstrip(".").lower()
    doc_format = DocumentFormat.from_extension(ext)
    return await document_parser_service.parse(file_path, doc_format)


async def extract_text_with_ocr(image_path: Path) -> str:
    """Extract text from an image using OCR.

    Args:
        image_path: Path to the image file.

    Returns:
        Extracted text string.
    """
    if not image_path.exists():
        raise NotFoundError("Image file", str(image_path))

    return await ocr_service.extract_text(image_path)


def chunk_document(
    text: str,
    metadata: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Split document text into chunks for embedding.

    Args:
        text: Full document text.
        metadata: Base metadata to attach to each chunk.

    Returns:
        List of dicts with 'text' and 'metadata' keys.
    """
    return document_parser_service.chunk_text(text, metadata)


# ── LangChain tool wrappers ────────────────────────────────────────────


@tool
async def document_parse_tool(file_path: str) -> str:
    """Parse a document and extract its text content.

    Supports PDF, DOCX, XLSX, PPTX, CSV, HTML, Markdown, and plain text.
    For images, use the document_ocr_tool instead.

    Args:
        file_path: Absolute path to the document file.

    Returns:
        The extracted text content from the document.
    """
    path = Path(file_path)
    parsed = await parse_document_file(path)

    summary_parts = [parsed.text[:8000]]  # Cap text for LLM context
    if parsed.tables:
        summary_parts.append(f"\n\n[{len(parsed.tables)} table(s) extracted]")
    if parsed.page_count:
        summary_parts.append(f"\n[{parsed.page_count} page(s)]")
    summary_parts.append(f"\n[{parsed.word_count} words]")

    return "".join(summary_parts)


@tool
async def document_ocr_tool(image_path: str) -> str:
    """Extract text from an image file using OCR (Optical Character Recognition).

    Supports PNG, JPG, JPEG, TIFF, and BMP image formats.

    Args:
        image_path: Absolute path to the image file.

    Returns:
        The OCR-extracted text from the image.
    """
    path = Path(image_path)
    text = await extract_text_with_ocr(path)
    if not text.strip():
        return "No text could be extracted from the image."
    return text


@tool
async def document_extract_tables_tool(file_path: str) -> str:
    """Extract tables from a document (PDF, DOCX, XLSX, CSV).

    Args:
        file_path: Absolute path to the document file.

    Returns:
        Formatted table data as text, or a message if no tables found.
    """
    path = Path(file_path)
    parsed = await parse_document_file(path)

    if not parsed.tables:
        return "No tables found in this document."

    parts = []
    for i, table in enumerate(parsed.tables, 1):
        headers = table.get("headers", [])
        rows = table.get("rows", [])
        page = table.get("page")
        sheet = table.get("sheet")

        location = ""
        if page:
            location = f" (Page {page})"
        elif sheet:
            location = f" (Sheet: {sheet})"

        header_str = " | ".join(headers)
        sep = "-" * len(header_str)
        rows_str = "\n".join(" | ".join(row) for row in rows[:20])
        truncated = f"\n... ({len(rows)} total rows)" if len(rows) > 20 else ""

        parts.append(f"Table {i}{location}:\n{header_str}\n{sep}\n{rows_str}{truncated}")

    return "\n\n".join(parts)


@tool
async def document_info_tool(file_path: str) -> str:
    """Get metadata and summary information about a document.

    Args:
        file_path: Absolute path to the document file.

    Returns:
        Document metadata including format, size, word count, and page count.
    """
    path = Path(file_path)
    if not path.exists():
        return f"File not found: {file_path}"

    stat = path.stat()
    parsed = await parse_document_file(path)

    info_lines = [
        f"Filename: {path.name}",
        f"Size: {stat.st_size / 1024:.1f} KB",
        f"Format: {parsed.metadata.get('format', 'unknown')}",
        f"Word count: {parsed.word_count}",
    ]
    if parsed.page_count:
        info_lines.append(f"Pages: {parsed.page_count}")
    if parsed.tables:
        info_lines.append(f"Tables: {len(parsed.tables)}")

    return "\n".join(info_lines)


# All document tools for agent binding
document_tools = [
    document_parse_tool,
    document_ocr_tool,
    document_extract_tables_tool,
    document_info_tool,
]

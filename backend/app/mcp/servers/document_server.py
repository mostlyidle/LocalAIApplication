"""MCP Server for document processing tools.

Exposes document parsing, OCR, table extraction, and metadata tools as an
MCP server using the FastMCP high-level API.

Usage:
    python -m app.mcp.servers.document_server
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import structlog

from mcp.server.fastmcp import FastMCP

logger = structlog.get_logger(__name__)

document_mcp = FastMCP(
    "Document Tools",
    instructions="Document parsing, OCR, table extraction, and analysis tools.",
)


@document_mcp.tool()
async def parse_document(file_path: str) -> str:
    """Parse a document and extract its full text content.

    Supports PDF, DOCX, XLSX, PPTX, CSV, HTML, Markdown, and plain text.

    Args:
        file_path: Absolute path to the document file.
    """
    from app.models.enums import DocumentFormat
    from app.services.document_parser import document_parser_service

    path = Path(file_path)
    if not path.exists():
        return f"File not found: {file_path}"

    try:
        doc_format = DocumentFormat.from_extension(path.suffix)
    except ValueError as exc:
        return str(exc)

    try:
        parsed = await document_parser_service.parse(path, doc_format)
        result = {
            "text": parsed.text[:5000],
            "word_count": parsed.word_count,
            "page_count": parsed.page_count,
            "table_count": len(parsed.tables),
            "metadata": parsed.metadata,
        }
        if len(parsed.text) > 5000:
            result["truncated"] = True
            result["total_characters"] = len(parsed.text)
        return json.dumps(result, indent=2)
    except Exception as exc:
        return f"Parse error: {exc}"


@document_mcp.tool()
async def extract_text_ocr(file_path: str) -> str:
    """Extract text from an image using OCR.

    Supports PNG, JPG, JPEG, TIFF, and BMP image formats.

    Args:
        file_path: Absolute path to the image file.
    """
    from app.services.ocr import ocr_service

    path = Path(file_path)
    if not path.exists():
        return f"File not found: {file_path}"

    try:
        text = await ocr_service.extract_text(path)
        return text if text else "No text detected in the image."
    except Exception as exc:
        return f"OCR error: {exc}"


@document_mcp.tool()
async def extract_tables(file_path: str) -> str:
    """Extract tables from a document (PDF, DOCX, XLSX, CSV).

    Returns tables as JSON with headers and rows.

    Args:
        file_path: Absolute path to the document file.
    """
    from app.models.enums import DocumentFormat
    from app.services.document_parser import document_parser_service

    path = Path(file_path)
    if not path.exists():
        return f"File not found: {file_path}"

    try:
        doc_format = DocumentFormat.from_extension(path.suffix)
    except ValueError as exc:
        return str(exc)

    try:
        parsed = await document_parser_service.parse(path, doc_format)
        if not parsed.tables:
            return "No tables found in the document."
        return json.dumps(parsed.tables, indent=2)
    except Exception as exc:
        return f"Table extraction error: {exc}"


@document_mcp.tool()
async def document_info(file_path: str) -> str:
    """Get metadata about a document without full parsing.

    Returns file size, format, and basic properties.

    Args:
        file_path: Absolute path to the document file.
    """
    path = Path(file_path)
    if not path.exists():
        return f"File not found: {file_path}"

    stat = path.stat()
    info = {
        "filename": path.name,
        "extension": path.suffix,
        "size_bytes": stat.st_size,
        "size_mb": round(stat.st_size / (1024 * 1024), 2),
        "modified": stat.st_mtime,
    }

    try:
        from app.models.enums import DocumentFormat

        doc_format = DocumentFormat.from_extension(path.suffix)
        info["format"] = doc_format.value
        info["is_image"] = doc_format.is_image
        info["is_office"] = doc_format.is_office
    except ValueError:
        info["format"] = "unknown"

    return json.dumps(info, indent=2)


@document_mcp.resource("formats://supported")
async def supported_formats() -> str:
    """List all supported document formats."""
    from app.models.enums import DocumentFormat

    formats = [
        {
            "name": f.value,
            "is_image": f.is_image,
            "is_office": f.is_office,
        }
        for f in DocumentFormat
    ]
    return json.dumps(formats, indent=2)


if __name__ == "__main__":
    document_mcp.run()

"""OCR engine abstraction using EasyOCR."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import structlog

logger = structlog.get_logger(__name__)

if TYPE_CHECKING:
    from pathlib import Path

# EasyOCR is heavy — lazy-load to avoid import-time delays.
_reader: Any = None


def _get_reader(languages: list[str] | None = None) -> Any:
    """Lazy-initialize the EasyOCR reader.

    EasyOCR downloads models on first use (~100MB for English).
    We cache the reader to avoid re-initialization on every call.
    """
    global _reader
    if _reader is None:
        import easyocr

        langs = languages or ["en"]
        logger.info("initializing_ocr_reader", languages=langs)
        _reader = easyocr.Reader(langs, gpu=False)  # CPU on Apple Silicon is fine
    return _reader


class OCRService:
    """Extract text from images using EasyOCR.

    Design decisions:
        - EasyOCR chosen for broad language support and no API keys.
        - GPU=False because Apple Silicon Metal isn't supported by EasyOCR;
          CPU performance is acceptable for document-scale images.
        - Lazy initialization to avoid startup delay.
        - All heavy OCR operations run in asyncio.to_thread() to avoid
          blocking the event loop.
    """

    async def extract_text(
        self,
        image_path: Path,
        languages: list[str] | None = None,
    ) -> str:
        """Extract text from an image file.

        Args:
            image_path: Path to the image file.
            languages: ISO language codes (default: ["en"]).

        Returns:
            Extracted text as a single string.
        """
        logger.info("ocr_processing", path=str(image_path))

        def _sync_extract() -> str:
            reader = _get_reader(languages)
            results = reader.readtext(str(image_path))
            lines: list[str] = []
            for _bbox, text, confidence in results:
                if confidence > 0.3:  # Filter low-confidence noise
                    lines.append(text)
            return "\n".join(lines)

        extracted = await asyncio.to_thread(_sync_extract)
        logger.info(
            "ocr_complete",
            path=str(image_path),
            chars=len(extracted),
        )
        return extracted

    async def extract_structured(
        self,
        image_path: Path,
        languages: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Extract text with bounding box and confidence info.

        Returns:
            List of dicts with keys: text, confidence, bbox.
        """

        def _sync_extract() -> list[dict[str, Any]]:
            reader = _get_reader(languages)
            results = reader.readtext(str(image_path))
            return [
                {
                    "text": text,
                    "confidence": round(float(confidence), 4),
                    "bbox": [list(map(float, point)) for point in bbox],
                }
                for bbox, text, confidence in results
                if confidence > 0.3
            ]

        return await asyncio.to_thread(_sync_extract)

    async def extract_structured_image(
        self,
        image: Any,
        languages: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Extract every OCR line from an in-memory image with its box and confidence.

        Unlike the document-analysis helpers, this retains low-confidence results so
        redaction review can show uncertain text instead of silently dropping it.
        """

        def _sync_extract() -> list[dict[str, Any]]:
            reader = _get_reader(languages)
            results = reader.readtext(image)
            return [
                {
                    "text": text,
                    "confidence": round(float(confidence), 4),
                    "bbox": [list(map(float, point)) for point in bbox],
                }
                for bbox, text, confidence in results
            ]

        return await asyncio.to_thread(_sync_extract)


# Module-level singleton
ocr_service = OCRService()

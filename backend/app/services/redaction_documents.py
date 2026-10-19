"""Coordinate-preserving extraction and safe raster export for redaction jobs."""

from __future__ import annotations

import asyncio
import math
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np
import pymupdf

MAX_RENDER_PIXELS = 16_000_000
REVIEW_DPI = 180
REDACTION_DPI = 200
REDACTION_MARGIN_POINTS = 1.5
OCR_DPI = 300

if TYPE_CHECKING:
    from pathlib import Path

    from app.services.ocr import OCRService


class RedactionDocumentError(ValueError):
    """A source page or requested redaction region cannot be processed safely."""


@dataclass(frozen=True)
class WordRegion:
    """A word's character offsets in normalized page text and its page rectangle."""

    start: int
    end: int
    rect: tuple[float, float, float, float]
    line: tuple[int, int]
    source: str = "pdf"
    confidence: float | None = None


@dataclass(frozen=True)
class ExtractedPage:
    """Native page text and source geometry in the displayed page coordinate space."""

    number: int
    width: float
    height: float
    text: str
    words: tuple[WordRegion, ...]


def extract_native_page(page: pymupdf.Page, page_number: int) -> ExtractedPage:
    """Extract all native words, preserving reading order and page-point geometry."""
    parts: list[str] = []
    words: list[WordRegion] = []
    offset = 0
    previous_line: tuple[int, int] | None = None
    rotation = page.rotation_matrix

    for item in page.get_text("words", sort=True):
        word = str(item[4])
        if not word:
            continue
        line = (int(item[5]), int(item[6]))
        if parts:
            separator = "\n" if line != previous_line else " "
            parts.append(separator)
            offset += len(separator)
        start = offset
        parts.append(word)
        offset += len(word)
        rect = pymupdf.Rect(item[:4]) * rotation
        words.append(
            WordRegion(
                start=start,
                end=offset,
                rect=(rect.x0, rect.y0, rect.x1, rect.y1),
                line=line,
            )
        )
        previous_line = line

    bounds = page.rect
    return ExtractedPage(
        number=page_number,
        width=bounds.width,
        height=bounds.height,
        text="".join(parts),
        words=tuple(words),
    )


def _normalized_ocr_text(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.casefold())


def add_ocr_regions(
    page: ExtractedPage,
    detections: list[dict[str, Any]],
    *,
    image_width: int,
    image_height: int,
) -> ExtractedPage:
    """Append OCR line spans and convert pixel polygons to displayed page points."""
    parts = [page.text] if page.text else []
    words = list(page.words)
    offset = len(page.text)
    native_text = _normalized_ocr_text(page.text)
    line_index = 0
    for detection in detections:
        text = str(detection.get("text", "")).strip()
        confidence = float(detection.get("confidence", 0.0))
        polygon = detection.get("bbox", [])
        if (
            not text
            or len(polygon) < 3
            or not math.isfinite(confidence)
            or len({len(point) for point in polygon}) != 1
            or any(len(point) < 2 for point in polygon)
        ):
            continue
        normalized_text = _normalized_ocr_text(text)
        if not normalized_text or normalized_text in native_text:
            continue
        if parts:
            parts.append("\n")
            offset += 1
        start = offset
        parts.append(text)
        offset += len(text)
        try:
            x_values = [float(point[0]) for point in polygon]
            y_values = [float(point[1]) for point in polygon]
        except (TypeError, ValueError, IndexError):
            continue
        if not all(math.isfinite(value) for value in (*x_values, *y_values)):
            continue
        rect = pymupdf.Rect(
            min(x_values) * page.width / image_width,
            min(y_values) * page.height / image_height,
            max(x_values) * page.width / image_width,
            max(y_values) * page.height / image_height,
        )
        rect &= pymupdf.Rect(0, 0, page.width, page.height)
        if rect.is_empty:
            continue
        words.append(
            WordRegion(
                start=start,
                end=offset,
                rect=(rect.x0, rect.y0, rect.x1, rect.y1),
                line=(-1, line_index),
                source="ocr",
                confidence=confidence,
            )
        )
        line_index += 1
    return ExtractedPage(
        number=page.number,
        width=page.width,
        height=page.height,
        text="".join(parts),
        words=tuple(words),
    )


async def extract_document_pages(
    source: Path,
    ocr_service: OCRService,
) -> list[ExtractedPage]:
    """Extract PDF/image pages and OCR scanned or image-containing page content."""
    document = await asyncio.to_thread(pymupdf.open, source)
    pages: list[ExtractedPage] = []
    try:
        for page_number in range(len(document)):
            page = document[page_number]
            extracted = await asyncio.to_thread(extract_native_page, page, page_number)
            has_images, has_widgets = await asyncio.to_thread(_page_requires_ocr, page)
            if extracted.words and not has_images and not has_widgets:
                pages.append(extracted)
                continue

            dpi = page_render_dpi(page, OCR_DPI)
            pixmap = await asyncio.to_thread(
                page.get_pixmap,
                dpi=dpi,
                colorspace=pymupdf.csRGB,
                alpha=False,
                annots=True,
            )
            channels = pixmap.n
            image = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(
                pixmap.height, pixmap.width, channels
            )
            detections = await ocr_service.extract_structured_image(image)
            pages.append(
                add_ocr_regions(
                    extracted,
                    detections,
                    image_width=pixmap.width,
                    image_height=pixmap.height,
                )
            )
    finally:
        await asyncio.to_thread(document.close)
    return pages


def _page_requires_ocr(page: pymupdf.Page) -> tuple[bool, bool]:
    return bool(page.get_image_info()), bool(list(page.widgets() or []))


def boxes_for_span(
    page: ExtractedPage,
    start: int,
    end: int,
    *,
    margin: float = REDACTION_MARGIN_POINTS,
) -> list[tuple[float, float, float, float]]:
    """Map a text span to one padded rectangle per visual text line."""
    if start < 0 or end <= start or end > len(page.text):
        raise RedactionDocumentError("The detected text span is outside the extracted page.")

    line_boxes: dict[tuple[int, int], pymupdf.Rect] = {}
    for word in page.words:
        if word.start >= end or word.end <= start:
            continue
        rect = pymupdf.Rect(word.rect)
        if word.line in line_boxes:
            line_boxes[word.line] |= rect
        else:
            line_boxes[word.line] = rect

    if not line_boxes:
        raise RedactionDocumentError("The detected text span has no source geometry.")

    page_bounds = pymupdf.Rect(0, 0, page.width, page.height)
    boxes = []
    for line_box in line_boxes.values():
        padded = pymupdf.Rect(
            max(page_bounds.x0, line_box.x0 - margin),
            max(page_bounds.y0, line_box.y0 - margin),
            min(page_bounds.x1, line_box.x1 + margin),
            min(page_bounds.y1, line_box.y1 + margin),
        )
        boxes.append((padded.x0, padded.y0, padded.x1, padded.y1))
    return boxes


def page_render_dpi(page: pymupdf.Page, preferred_dpi: int) -> int:
    """Cap render memory by lowering DPI when a source page has large dimensions."""
    if preferred_dpi < 72:
        raise RedactionDocumentError("Render resolution must be at least 72 DPI.")
    page_area = page.rect.width * page.rect.height
    if page_area <= 0:
        raise RedactionDocumentError("The document contains a page with invalid dimensions.")
    maximum_dpi = math.floor(72 * math.sqrt(MAX_RENDER_PIXELS / page_area))
    dpi = max(72, min(preferred_dpi, maximum_dpi))
    while (
        math.ceil(page.rect.width * dpi / 72) * math.ceil(page.rect.height * dpi / 72)
        > MAX_RENDER_PIXELS
        and dpi > 72
    ):
        dpi -= 1
    if page_area > MAX_RENDER_PIXELS:
        raise RedactionDocumentError("A page exceeds the safe render pixel limit.")
    return dpi


def validate_boxes(
    page: ExtractedPage,
    boxes: list[tuple[float, float, float, float]],
) -> list[pymupdf.Rect]:
    """Reject malformed or out-of-page client boxes before they reach the renderer."""
    page_bounds = pymupdf.Rect(0, 0, page.width, page.height)
    validated = []
    for values in boxes:
        if len(values) != 4 or not all(math.isfinite(value) for value in values):
            raise RedactionDocumentError("A redaction box has invalid coordinates.")
        x0, y0, x1, y1 = values
        if x1 <= x0 or y1 <= y0:
            raise RedactionDocumentError("A redaction box must have positive width and height.")
        rect = pymupdf.Rect(x0, y0, x1, y1)
        if not page_bounds.contains(rect):
            raise RedactionDocumentError("A redaction box must fit within its source page.")
        validated.append(rect)
    return validated


def render_page_image(page: pymupdf.Page, *, dpi: int = REVIEW_DPI) -> bytes:
    """Render one displayed page to PNG bytes, including visible annotations."""
    pixmap = page.get_pixmap(
        dpi=page_render_dpi(page, dpi),
        colorspace=pymupdf.csRGB,
        alpha=False,
        annots=True,
    )
    return pixmap.tobytes("png")


def redact_to_image_pdf(
    source: Path,
    output: Path,
    redactions: dict[int, list[tuple[float, float, float, float]]],
) -> int:
    """Create a new text-free PDF by painting boxes into source page pixels."""
    original = pymupdf.open(source)
    result = pymupdf.open()
    try:
        for page_number, page in enumerate(original):
            source_page = extract_native_page(page, page_number)
            boxes = validate_boxes(source_page, redactions.get(page_number, []))
            dpi = page_render_dpi(page, REDACTION_DPI)
            pixmap = page.get_pixmap(
                dpi=dpi,
                colorspace=pymupdf.csRGB,
                alpha=False,
                annots=True,
            )
            scale_x = pixmap.width / page.rect.width
            scale_y = pixmap.height / page.rect.height
            for rect in boxes:
                pixel_rect = pymupdf.IRect(
                    math.floor(rect.x0 * scale_x),
                    math.floor(rect.y0 * scale_y),
                    math.ceil(rect.x1 * scale_x),
                    math.ceil(rect.y1 * scale_y),
                )
                pixmap.set_rect(pixel_rect, (0, 0, 0))

            output_page = result.new_page(
                width=source_page.width,
                height=source_page.height,
            )
            output_page.insert_image(output_page.rect, stream=pixmap.tobytes("png"))

        output.parent.mkdir(parents=True, exist_ok=True)
        result.save(output, garbage=4, deflate=True)
        return len(original)
    finally:
        result.close()
        original.close()

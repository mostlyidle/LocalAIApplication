"""Tests for coordinate-safe document extraction and irreversible PDF export."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import pymupdf
import pytest

from app.services.redaction_documents import (
    ExtractedPage,
    RedactionDocumentError,
    add_ocr_regions,
    boxes_for_span,
    extract_native_page,
    page_render_dpi,
    redact_to_image_pdf,
    validate_boxes,
)

if TYPE_CHECKING:
    from pathlib import Path


def make_text_pdf(path: Path) -> Path:
    """Write a fixture with repeated, multiline, and redaction-worthy text."""
    document = pymupdf.open()
    page = document.new_page(width=300, height=400)
    page.insert_text((24, 60), "Employee Name: Alex Example", fontsize=14)
    page.insert_text((24, 96), "Account Number: EXAMPLE-14027", fontsize=14)
    document.save(path)
    document.close()
    return path


def test_extract_native_page_maps_text_ranges_to_words() -> None:
    """Text offsets identify only the words in a value, with its original page box."""
    document = pymupdf.open()
    page = document.new_page(width=300, height=400)
    page.insert_text((24, 60), "Employee Name: Alex Example", fontsize=14)
    page.insert_text((24, 96), "Account Number: EXAMPLE-14027", fontsize=14)

    extracted = extract_native_page(page, 0)
    start = extracted.text.index("Alex Example")
    boxes = boxes_for_span(extracted, start, start + len("Alex Example"))

    assert extracted.text == "Employee Name: Alex Example\nAccount Number: EXAMPLE-14027"
    assert len(boxes) == 1
    assert boxes[0][0] > 100
    assert boxes[0][2] < 250
    assert boxes[0][3] < 80
    document.close()


def test_boxes_for_multiline_span_returns_separate_line_boxes() -> None:
    """A multiline value does not redact the space between its source lines."""
    document = pymupdf.open()
    page = document.new_page(width=300, height=400)
    page.insert_text((24, 60), "Address: 101 Example Street", fontsize=14)
    page.insert_text((24, 96), "Toronto, ON M5H 2N2", fontsize=14)
    extracted = extract_native_page(page, 0)
    start = extracted.text.index("101 Example Street")
    end = extracted.text.index("M5H 2N2") + len("M5H 2N2")

    boxes = boxes_for_span(extracted, start, end)

    assert len(boxes) == 2
    assert boxes[1][1] - boxes[0][3] > 10
    document.close()


@pytest.mark.parametrize(
    "box",
    [(-1.0, 5.0, 20.0, 25.0), (10.0, 10.0, 10.0, 20.0), (1.0, 1.0, math.inf, 4.0)],
)
def test_validate_boxes_rejects_invalid_or_out_of_page_regions(
    box: tuple[float, float, float, float],
) -> None:
    """Client coordinates cannot escape page bounds or form degenerate rectangles."""
    page = ExtractedPage(number=0, width=100, height=100, text="", words=())

    with pytest.raises(RedactionDocumentError):
        validate_boxes(page, [box])


def test_render_resolution_is_capped_for_large_pages() -> None:
    """Large page dimensions lower the DPI rather than exceeding the pixel cap."""
    document = pymupdf.open()
    page = document.new_page(width=5_000, height=3_000)
    dpi = page_render_dpi(page, preferred_dpi=200)

    assert dpi < 200
    assert (
        math.ceil(page.rect.width * dpi / 72) * math.ceil(page.rect.height * dpi / 72) <= 16_000_000
    )
    document.close()


def test_ocr_regions_keep_low_confidence_text_and_map_pixels_to_points() -> None:
    """Review can surface uncertain OCR with geometry scaled to page points."""
    page = ExtractedPage(number=2, width=300, height=400, text="", words=())

    extracted = add_ocr_regions(
        page,
        [
            {
                "text": "EXAMPLE-ID",
                "confidence": 0.12,
                "bbox": [[100, 200], [200, 200], [200, 240], [100, 240]],
            }
        ],
        image_width=600,
        image_height=800,
    )

    assert extracted.text == "EXAMPLE-ID"
    assert extracted.words[0].source == "ocr"
    assert extracted.words[0].confidence == 0.12
    assert extracted.words[0].rect == (50, 100, 100, 120)


def test_render_resolution_rejects_pages_too_large_even_at_72_dpi() -> None:
    """A page that exceeds the pixel budget at the minimum DPI fails explicitly."""
    document = pymupdf.open()
    page = document.new_page(width=7_200, height=3_000)

    with pytest.raises(RedactionDocumentError, match="pixel limit"):
        page_render_dpi(page, preferred_dpi=200)
    document.close()


def test_export_contains_only_sanitized_page_images(tmp_path: Path) -> None:
    """The source stays readable while the new export has no source text or attachments."""
    source = make_text_pdf(tmp_path / "source.pdf")
    original = pymupdf.open(source)
    original[0].set_rotation(90)
    extracted = extract_native_page(original[0], 0)
    start = extracted.text.index("Alex Example")
    redactions = {0: boxes_for_span(extracted, start, start + len("Alex Example"))}
    original.embfile_add("fixture.txt", b"attachment")
    original.set_metadata({"title": "Sensitive synthetic title"})
    original.saveIncr()
    original.close()

    result = tmp_path / "redacted.pdf"
    assert redact_to_image_pdf(source, result, redactions) == 1

    source_check = pymupdf.open(source)
    exported = pymupdf.open(result)
    pixmap = exported[0].get_pixmap(dpi=200, alpha=False)
    rect = pymupdf.Rect(redactions[0][0])
    center_x = int(((rect.x0 + rect.x1) / 2) * pixmap.width / exported[0].rect.width)
    center_y = int(((rect.y0 + rect.y1) / 2) * pixmap.height / exported[0].rect.height)

    assert "Alex Example" in source_check[0].get_text()
    assert source_check.embfile_count() == 1
    assert exported[0].get_text().strip() == ""
    assert exported[0].get_images()
    assert exported.embfile_count() == 0
    assert pixmap.pixel(center_x, center_y) == (0, 0, 0)
    assert not exported.metadata.get("title")
    source_check.close()
    exported.close()

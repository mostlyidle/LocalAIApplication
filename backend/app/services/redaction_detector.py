"""Local PII candidate detection for document redaction."""

from __future__ import annotations

import asyncio
import re
import threading
from typing import TYPE_CHECKING, Any

import structlog

from app.services.redaction_documents import ExtractedPage

if TYPE_CHECKING:
    from pathlib import Path

logger = structlog.get_logger(__name__)
MODEL_ID = "nvidia/gliner-PII"
MODEL_REVISION = "bd23e8ef4425fd04e34c5204ab49ffaa706eae79"
CHUNK_SIZE = 4_000
CHUNK_OVERLAP = 250

DEFAULT_CATEGORIES = (
    "person name",
    "employee number",
    "email address",
    "phone number",
    "street address",
    "salary",
    "government identification number",
    "social security number",
    "social insurance number",
    "passport number",
    "driver license number",
    "date of birth",
    "bank account number",
    "credit card number",
)

_RULES: dict[str, re.Pattern[str]] = {
    "email address": re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"),
    "phone number": re.compile(r"(?<!\w)(?:\+?\d[\d ().-]{7,}\d)(?!\w)"),
    "social security number": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "social insurance number": re.compile(r"\b\d{3}[ -]?\d{3}[ -]?\d{3}\b"),
    "credit card number": re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)"),
}
_LABEL_ALIASES = {
    "person name": ("name", "employee name", "staff name"),
    "employee number": ("employee number", "employee id", "staff number", "staff id"),
    "email address": ("email", "email address", "e-mail"),
    "phone number": ("phone", "phone number", "mobile number"),
    "street address": ("address", "street address", "home address", "mailing address"),
    "salary": ("salary", "compensation", "annual pay"),
    "government identification number": ("government id", "government number", "id number"),
    "social security number": ("social security number", "ssn"),
    "social insurance number": ("social insurance number", "sin"),
    "passport number": ("passport number", "passport"),
    "driver license number": ("driver license number", "driver's license", "driving licence"),
    "date of birth": ("date of birth", "birth date", "dob"),
    "bank account number": ("bank account number", "account number"),
    "credit card number": ("credit card number", "card number"),
}

_model: Any = None
_model_lock = threading.Lock()


class RedactionModelUnavailableError(RuntimeError):
    """The pinned GLiNER model is not installed in the local cache."""


def _get_model(cache_dir: Path) -> Any:
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                from gliner import GLiNER

                try:
                    _model = GLiNER.from_pretrained(
                        MODEL_ID,
                        revision=MODEL_REVISION,
                        cache_dir=cache_dir,
                        local_files_only=True,
                        map_location="cpu",
                    )
                except (OSError, ValueError) as exc:
                    raise RedactionModelUnavailableError(
                        "The local redaction model is not installed. Run "
                        "`uv run python ../scripts/download_redaction_model.py` from backend/."
                    ) from exc
                logger.info("redaction_model_loaded", model=MODEL_ID, revision=MODEL_REVISION)
    return _model


def _chunks(text: str) -> list[tuple[int, str]]:
    if len(text) <= CHUNK_SIZE:
        return [(0, text)]
    result = []
    start = 0
    while start < len(text):
        end = min(start + CHUNK_SIZE, len(text))
        if end < len(text):
            boundary = text.rfind("\n", start, end)
            if boundary > start + CHUNK_SIZE // 2:
                end = boundary
        result.append((start, text[start:end]))
        if end == len(text):
            break
        start = max(start + 1, end - CHUNK_OVERLAP)
    return result


def _detect_sync(
    text: str,
    categories: list[str],
    cache_dir: Path,
) -> list[dict[str, Any]]:
    import torch

    model = _get_model(cache_dir)
    label_to_category = {
        ("person" if category == "person name" else category).casefold(): category
        for category in categories
    }
    labels = list(dict.fromkeys(label_to_category))
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    model.to(device)
    model.eval()
    candidates: dict[tuple[int, int, str], dict[str, Any]] = {}
    with torch.inference_mode():
        for offset, chunk in _chunks(text):
            for match in model.predict_entities(chunk, labels, threshold=0.3):
                start = offset + int(match["start"])
                end = offset + int(match["end"])
                model_label = str(match.get("label", "other")).casefold()
                label = label_to_category.get(model_label)
                if label is None:
                    continue
                if start < 0 or end <= start or end > len(text):
                    continue
                key = (start, end, label)
                candidates[key] = {
                    "start": start,
                    "end": end,
                    "text": text[start:end],
                    "category": label,
                    "confidence": float(match.get("score", 0.0)),
                    "source": "gliner",
                    "selected": True,
                }

    for category in categories:
        aliases = _LABEL_ALIASES.get(category, (category,))
        pattern = re.compile(
            rf"(?im)^\s*(?:{'|'.join(re.escape(alias) for alias in aliases)})"
            rf"\s*:\s*(?P<value>.+?)\s*$"
        )
        for match in pattern.finditer(text):
            start, end = match.span("value")
            key = (start, end, category)
            candidates.setdefault(
                key,
                {
                    "start": start,
                    "end": end,
                    "text": match.group("value"),
                    "category": category,
                    "confidence": 1.0,
                    "source": "label_rule",
                    "selected": True,
                },
            )

    for category, pattern in _RULES.items():
        if category not in categories:
            continue
        for match in pattern.finditer(text):
            key = (match.start(), match.end(), category)
            candidates.setdefault(
                key,
                {
                    "start": match.start(),
                    "end": match.end(),
                    "text": match.group(),
                    "category": category,
                    "confidence": 1.0,
                    "source": "rule",
                    "selected": True,
                },
            )

    ordered = sorted(candidates.values(), key=lambda item: (item["start"], -item["end"]))
    merged: list[dict[str, Any]] = []
    for candidate in ordered:
        containing = next(
            (
                item
                for item in merged
                if item["category"] == candidate["category"]
                and item["start"] <= candidate["start"]
                and candidate["end"] <= item["end"]
            ),
            None,
        )
        if containing is not None:
            continue
        merged = [
            item
            for item in merged
            if not (
                item["category"] == candidate["category"]
                and candidate["start"] <= item["start"]
                and item["end"] <= candidate["end"]
            )
        ]
        merged.append(candidate)
    return sorted(merged, key=lambda item: (item["start"], item["end"]))


async def detect_candidates(
    page: ExtractedPage,
    categories: list[str],
    *,
    cache_dir: Path,
) -> list[dict[str, Any]]:
    """Detect requested PII spans without sending document contents off-device."""
    if not page.text:
        return []
    return await asyncio.to_thread(_detect_sync, page.text, categories, cache_dir)


def page_data(page: ExtractedPage) -> dict[str, Any]:
    """Serialize source geometry needed for review and approved export."""
    return {
        "number": page.number,
        "width": page.width,
        "height": page.height,
        "text": page.text,
        "error": page.error,
        "words": [
            {
                "start": word.start,
                "end": word.end,
                "rect": list(word.rect),
                "line": list(word.line),
                "source": word.source,
                "confidence": word.confidence,
            }
            for word in page.words
        ],
    }


def page_from_data(data: dict[str, Any]) -> ExtractedPage:
    from app.services.redaction_documents import WordRegion

    return ExtractedPage(
        number=int(data["number"]),
        width=float(data["width"]),
        height=float(data["height"]),
        text=str(data["text"]),
        words=tuple(
            WordRegion(
                start=int(word["start"]),
                end=int(word["end"]),
                rect=tuple(float(value) for value in word["rect"]),
                line=tuple(int(value) for value in word["line"]),
                source=str(word["source"]),
                confidence=(float(word["confidence"]) if word["confidence"] is not None else None),
            )
            for word in data["words"]
        ),
        error=(str(data["error"]) if data.get("error") is not None else None),
    )

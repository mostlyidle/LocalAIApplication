"""Parsing and conservative interpretation helpers for lab report extraction."""

from __future__ import annotations

import io
import json
import math
import re
from collections import defaultdict
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.models.enums import DocumentFormat

if TYPE_CHECKING:
    from pathlib import Path

MEDICAL_LAB_PROFILE = "medical_lab_explainer"
MAX_LAB_PAGES = 20
MAX_PAGE_TEXT_CHARS = 12_000
OUT_OF_SCOPE_EXPLANATION = re.compile(
    r"\b(?:should|must|recommend\w*|diagnos\w*|treat\w*|urgent\w*|emergency|"
    r"call|contact|seek|take|start|stop|increase|decrease|normal|abnormal|healthy|"
    r"unhealthy|indicat\w*|suggest\w*|caus\w*|risk|disease|disorder|condition|"
    r"infection|cancer|diabetes|anemia|anaemia|you|your|patient|result|high|low|"
    r"interpret\w*|mean\w*|likely|possibly|might|could|often|usually|elevat\w*|"
    r"increas\w*|decreas\w*|associat\w*|link\w*|marker|indicator|with|for|"
    r"hypothyroid\w*|hyperthyroid\w*|syndrome|tumou?r|leukemia|leukaemia)\b",
    re.IGNORECASE,
)
EDUCATIONAL_EXPLANATION = re.compile(
    r"this test (?:measures|counts) "
    r"(?:(?:the )?(?:amount|number|level|concentration|proportion|size) of )?"
    r"[a-z0-9α-ωµμ]+(?:[-/' ][a-z0-9α-ωµμ]+){0,6} in "
    r"(?:a |the )?(?:blood|urine|serum|plasma|saliva|stool|sample|specimen)"
    r"(?: sample| specimen)?[.]?(?:\s+it is (?:commonly )?used to "
    r"(?:check|monitor|assess) [a-z0-9α-ωµμ]+(?:[-/' ][a-z0-9α-ωµμ]+){0,5}[.]?)?",
    re.IGNORECASE,
)
GENERIC_EXPLANATION_FALLBACKS = {
    # MedlinePlus: https://medlineplus.gov/lab-tests/hemoglobin-test/
    "hemoglobin": "This test measures hemoglobin in a blood sample.",
}
POPULATION_QUALIFIER = re.compile(
    r"\b(?:age|years? old|male|female|sex|pregnan\w*|trimester|"
    r"pediatric|paediatric|adult|child|children|infant|neonate|newborn|"
    r"adolescent|women|woman|men|man|postmenopausal|gestational)\b",
    re.IGNORECASE,
)
REPORT_ALERT = re.compile(
    r"\b(?:critical|panic)\b|"
    r"\b(?:call|contact|consult|notify|seek|speak to|reach out to)\b.{0,120}"
    r"\b(?:doctor|provider|clinician|physician|nurse|health\s*care|medical\s+"
    r"professional|emergency services)\b|\b(?:call|dial)\s+(?:911|999|112)\b",
    re.IGNORECASE,
)


class LabObservation(BaseModel):
    model_config = ConfigDict(extra="ignore")

    test_name: str = Field(min_length=1, max_length=160)
    result: str | None = Field(default=None, max_length=100)
    unit: str | None = Field(default=None, max_length=80)
    reference_interval: str | None = Field(default=None, max_length=120)
    reference_qualifier: str | None = Field(default=None, max_length=160)
    report_flag: str | None = Field(default=None, max_length=120)
    critical_wording: str | None = Field(default=None, max_length=240)
    source_excerpt: str | None = Field(default=None, max_length=600)
    explanation: str | None = Field(default=None, max_length=600)


@dataclass(frozen=True)
class LabPage:
    number: int
    text: str
    image_bytes: bytes | None = None
    image_format: str | None = None
    truncated: bool = False


async def add_local_ocr(page: LabPage) -> LabPage:
    """Use the app's installed local OCR assets to corroborate a rendered scan."""
    if not page.image_bytes:
        return page
    try:
        import numpy as np
        from PIL import Image

        from app.services.ocr import ocr_service

        image = np.array(Image.open(io.BytesIO(page.image_bytes)).convert("RGB"))
        lines = await ocr_service.extract_structured_image(image)
    except (ImportError, OSError, RuntimeError, ValueError):
        return page
    ocr_text = "\n".join(
        str(line["text"])
        for line in lines
        if isinstance(line.get("text"), str) and float(line.get("confidence", 0)) > 0.3
    )
    if not ocr_text.strip() or _normalized_text(ocr_text) in _normalized_text(page.text):
        return page
    text = "\n".join(part for part in (page.text, ocr_text) if part.strip())
    return replace(
        page,
        text=text[:MAX_PAGE_TEXT_CHARS],
        truncated=page.truncated or len(text) > MAX_PAGE_TEXT_CHARS,
    )


def prepare_lab_pages(
    file_path: Path | None,
    doc_format: DocumentFormat | None,
    parsed: Any | None,
    *,
    vision: bool,
    pasted_text: str = "",
) -> list[LabPage]:
    """Create page-scoped input, rendering PDF/image pages only for vision models."""
    if file_path is None:
        return [
            LabPage(
                number=1,
                text=pasted_text[:MAX_PAGE_TEXT_CHARS],
                truncated=len(pasted_text) > MAX_PAGE_TEXT_CHARS,
            )
        ]

    if doc_format is None:
        raise ValueError("A document format is required for an uploaded lab report.")
    if doc_format == DocumentFormat.PDF:
        import fitz

        parsed_pages: dict[int, list[str]] = defaultdict(list)
        for block in getattr(parsed, "blocks", []):
            page_number = block.get("page")
            if isinstance(page_number, int) and isinstance(block.get("text"), str):
                parsed_pages[page_number].append(block["text"])
        for table in getattr(parsed, "tables", []):
            page_number = table.get("page")
            if not isinstance(page_number, int):
                continue
            headers = [str(cell) for cell in table.get("headers", [])]
            rows = table.get("rows", [])
            existing_page_text = _normalized_text("\n".join(parsed_pages.get(page_number, [])))
            row_cells = [str(cell) for row in rows for cell in row]
            if row_cells and all(
                not cell.strip() or _normalized_text(cell) in existing_page_text
                for cell in row_cells
            ):
                if headers and not all(
                    not header.strip() or _normalized_text(header) in existing_page_text
                    for header in headers
                ):
                    parsed_pages[page_number].append(" | ".join(headers))
                continue
            parsed_pages[page_number].append(" | ".join(headers))
            parsed_pages[page_number].extend(
                " | ".join(str(cell) for cell in row) for row in rows
            )

        pages: list[LabPage] = []
        with fitz.open(str(file_path)) as pdf:
            if len(pdf) > MAX_LAB_PAGES:
                raise ValueError(f"This prototype supports up to {MAX_LAB_PAGES} PDF pages.")
            for index, page in enumerate(pdf, 1):
                page_text = "\n".join(parsed_pages.get(index, []))
                truncated = len(page_text) > MAX_PAGE_TEXT_CHARS
                page_text = page_text[:MAX_PAGE_TEXT_CHARS]
                image_bytes = None
                if vision:
                    scale = min(1.6, 2000 / max(page.rect.width, page.rect.height))
                    pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
                    image_bytes = pixmap.tobytes("png")
                pages.append(
                    LabPage(
                        number=index,
                        text=page_text,
                        image_bytes=image_bytes,
                        image_format="png" if image_bytes else None,
                        truncated=truncated,
                    )
                )
        return pages

    if doc_format.is_image:
        raw_text = str(getattr(parsed, "text", ""))
        text = raw_text[:MAX_PAGE_TEXT_CHARS]
        image_bytes = _normalize_image(file_path) if vision else None
        return [
            LabPage(
                number=1,
                text=text,
                image_bytes=image_bytes,
                image_format="png" if image_bytes else None,
                truncated=len(raw_text) > MAX_PAGE_TEXT_CHARS,
            )
        ]

    if doc_format in {DocumentFormat.TEXT, DocumentFormat.MARKDOWN, DocumentFormat.CSV}:
        raw_text = str(getattr(parsed, "text", ""))
        return [
            LabPage(
                number=1,
                text=raw_text[:MAX_PAGE_TEXT_CHARS],
                truncated=len(raw_text) > MAX_PAGE_TEXT_CHARS,
            )
        ]

    raise ValueError("Use a PDF, image, CSV, Markdown, or text lab report.")


def parse_page_observations(raw: str, page: LabPage) -> tuple[list[dict[str, Any]], bool]:
    """Parse one page's JSON response; malformed output becomes an abstention."""
    try:
        payload = _json_payload(raw)
    except (json.JSONDecodeError, ValueError):
        return [], False
    if not isinstance(payload, dict) or not isinstance(payload.get("tests"), list):
        return [], False

    observations: list[dict[str, Any]] = []
    for raw_row in payload["tests"]:
        try:
            row = LabObservation.model_validate(raw_row)
        except (ValidationError, TypeError):
            continue
        if not any(
            (
                row.result,
                row.reference_interval,
                row.report_flag,
                row.critical_wording,
            )
        ):
            continue
        excerpt = (row.source_excerpt or "").strip()
        excerpt_text = _normalized_text(excerpt)
        quoted_fields = (
            row.test_name,
            row.result,
            row.unit,
            row.reference_interval,
            row.reference_qualifier,
            row.report_flag,
            row.critical_wording,
        )
        verified = bool(
            not page.truncated
            and excerpt
            and excerpt_text in _normalized_text(page.text)
            and all(
                _normalized_text(value) in excerpt_text
                for value in quoted_fields
                if value
            )
        )
        values = row.model_dump()
        if row.explanation:
            explanation = row.explanation.strip()
            values["explanation"] = (
                explanation
                if EDUCATIONAL_EXPLANATION.fullmatch(explanation)
                and not OUT_OF_SCOPE_EXPLANATION.search(explanation)
                else None
            )
        observations.append(
            {
                **values,
                "page": page.number,
                "page_text": page.text,
                "source_verified": verified,
                "source_kind": "image" if page.image_bytes else "text",
            }
        )
    return observations, True


def assemble_lab_results(observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Join only unique same-report observations with exact normalized name and unit."""
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for index, row in enumerate(observations):
        name_key = _normalized_key(str(row.get("test_name") or ""))
        unit = str(row.get("unit") or "").strip()
        unit_key = _normalized_unit(unit)
        if not name_key:
            continue
        # Missing units cannot safely join observations from different pages.
        key = (name_key, unit_key, "" if unit_key else str(index))
        groups.setdefault(key, []).append(row)

    results: list[dict[str, Any]] = []
    for rows in groups.values():
        results.append(_assemble_group(rows))
    return results


def _assemble_group(rows: list[dict[str, Any]]) -> dict[str, Any]:
    results = [(row, row.get("result")) for row in rows if row.get("result")]
    ranges = [(row, row.get("reference_interval")) for row in rows if row.get("reference_interval")]
    result_conflict = len(results) > 1
    range_conflict = len(ranges) > 1
    result_row, result_text = results[0] if len(results) == 1 else (None, None)
    range_row, interval = ranges[0] if len(ranges) == 1 else (None, None)
    chosen = result_row or range_row or rows[0]
    unit = str(chosen.get("unit") or "").strip()
    qualifier = next(
        (str(row["reference_qualifier"]).strip() for row in rows if row.get("reference_qualifier")),
        None,
    )
    if qualifier is None:
        qualifier = next(
            (
                "Detected population qualifier in source page"
                for row in rows
                if POPULATION_QUALIFIER.search(
                    str(row.get("source_excerpt") or "")
                    + " "
                    + str(row.get("page_text") or "")
                )
            ),
            None,
        )
    sources = [
        {
            "page": row["page"],
            "excerpt": row.get("source_excerpt"),
            "verified": row["source_verified"],
            "kind": row["source_kind"],
        }
        for row in rows
        if row.get("source_excerpt")
    ]
    comparison = "needs_review"
    reason = "Result, interval, unit, or source evidence is incomplete or ambiguous."
    comparison_calculation = None
    if result_conflict or range_conflict:
        reason = "More than one result or reference interval matched this test and unit."
    elif qualifier:
        reason = "The report includes a population-specific reference qualifier."
    elif result_row and range_row and unit and result_row["source_verified"] and range_row["source_verified"]:
        numeric_text = _numeric_literal(str(result_text), unit)
        numeric = _parse_decimal(str(result_text), unit)
        bounds = _parse_interval(str(interval), unit)
        if numeric_text is not None and numeric is not None and bounds is not None:
            low, high = bounds
            interval_parts = _interval_parts(str(interval), unit)
            low_text, high_text = interval_parts or (str(low), str(high))
            if numeric < low:
                comparison = "below_reported_range"
                comparison_calculation = f"{numeric_text} < {low_text}"
            elif numeric > high:
                comparison = "above_reported_range"
                comparison_calculation = f"{numeric_text} > {high_text}"
            else:
                comparison = "within_reported_range"
                comparison_calculation = f"{low_text} ≤ {numeric_text} ≤ {high_text}"
            reason = "Compared with the reference interval printed on this report."
        else:
            reason = "The result or interval is not an unambiguous numeric format."

    critical = []
    for row in rows:
        wording = str(row.get("critical_wording") or "").strip()
        if not wording:
            continue
        source_verified = row["source_verified"] and _normalized_text(wording) in _normalized_text(
            str(row.get("source_excerpt") or "")
        )
        critical.append(
            {
                "wording": wording,
                "page": row["page"],
                "verified": source_verified,
            }
        )

    explanation = next(
        (
            str(row["explanation"]).strip()
            for row in rows
            if row.get("explanation") and row.get("source_verified") is True
        ),
        None,
    )
    if explanation is None and chosen.get("source_verified") is True:
        explanation = GENERIC_EXPLANATION_FALLBACKS.get(
            _normalized_key(str(chosen.get("test_name") or ""))
        )
    return {
        "test_name": str(chosen.get("test_name") or "").strip(),
        "result": result_text,
        "unit": unit or None,
        "reference_interval": interval,
        "reference_qualifier": qualifier,
        "report_flags": [
            {
                "text": str(row["report_flag"]).strip(),
                "page": row["page"],
                "verified": row["source_verified"]
                and _normalized_text(str(row["report_flag"]))
                in _normalized_text(str(row.get("source_excerpt") or "")),
            }
            for row in rows
            if row.get("report_flag")
        ],
        "critical_wording": critical,
        "comparison": comparison,
        "comparison_calculation": comparison_calculation,
        "comparison_reason": reason,
        "explanation": explanation,
        "sources": sources,
    }


def extract_report_alerts(pages: list[LabPage]) -> list[dict[str, Any]]:
    """Find exact critical or provider-contact wording in available page text."""
    alerts: list[dict[str, Any]] = []
    seen: set[tuple[int, str]] = set()
    for page in pages:
        lines = page.text.splitlines()
        matching_lines = [
            bool(REPORT_ALERT.search(_normalized_text(line.strip()))) for line in lines
        ]
        candidates = [
            line.strip()
            for line, matches in zip(lines, matching_lines, strict=True)
            if matches
        ]
        covered_lines = {index for index, matches in enumerate(matching_lines) if matches}
        for size in (2, 3):
            for start in range(max(0, len(lines) - size + 1)):
                window_lines = set(range(start, start + size))
                if window_lines & covered_lines:
                    continue
                wording = " ".join(line.strip() for line in lines[start : start + size]).strip()
                if len(wording) > 240 or not REPORT_ALERT.search(_normalized_text(wording)):
                    continue
                candidates.append(wording)
                covered_lines.update(window_lines)
        for wording in candidates:
            if len(wording) > 240:
                continue
            key = (page.number, _normalized_text(wording))
            if key not in seen:
                seen.add(key)
                alerts.append({"page": page.number, "wording": wording})
    return alerts


def render_lab_answer(
    results: list[dict[str, Any]], report_alerts: list[dict[str, Any]] | None = None
) -> str:
    if not results:
        answer = (
            "This is not medical advice. I could not extract lab values with enough source evidence to compare. "
            "Check the uploaded report or paste its lab table as text. No range comparison was made."
        )
        if report_alerts:
            answer += "\n\n" + _render_report_alerts(report_alerts)
        return answer

    labels = {
        "within_reported_range": "Within the report's interval",
        "below_reported_range": "Below the report's interval",
        "above_reported_range": "Above the report's interval",
        "needs_review": "Needs review; no comparison made",
    }
    lines = [
        "## Lab report explanation",
        "This is not medical advice. This is an educational extraction. A result inside a lab interval does not prove that a person is healthy, and a result outside it does not by itself establish a health problem.",
        "",
        "| Test | Result | Unit | Report interval | Comparison |",
        "| --- | --- | --- | --- | --- |",
    ]
    if report_alerts:
        lines[2:2] = [_render_report_alerts(report_alerts), ""]
    for result in results:
        lines.append(
            "| {test} | {value} | {unit} | {interval} | {comparison} |".format(
                test=_markdown_cell(result["test_name"]),
                value=_markdown_cell(result.get("result") or "Not extracted"),
                unit=_markdown_cell(result.get("unit") or "Not shown"),
                interval=_markdown_cell(result.get("reference_interval") or "Not extracted"),
                comparison=(
                    f"{labels[result['comparison']]} ({result['comparison_calculation']})"
                    if result.get("comparison_calculation")
                    else labels[result["comparison"]]
                ),
            )
        )
    lines.append("")

    for result in results:
        lines.append(f"### {result['test_name']}")
        if result.get("explanation"):
            lines.append(str(result["explanation"]))
        for flag in result["report_flags"]:
            marker = "Lab report flag" if flag["verified"] else "Check this flag on the report"
            lines.append(f"{marker} (page {flag['page']}): `{flag['text']}`")
        for critical in result["critical_wording"]:
            marker = "Report-stated critical wording" if critical["verified"] else "Check this page text"
            lines.append(f"**{marker} (page {critical['page']}):** `{critical['wording']}`")
        for source in result["sources"]:
            if source.get("excerpt"):
                verification = "text match" if source["verified"] else "verify against uploaded page"
                lines.append(
                    f"Source (page {source['page']}, {verification}): “{source['excerpt']}”"
                )
        if result["comparison"] == "needs_review":
            lines.append(f"No comparison was made: {result['comparison_reason']}")
        lines.append("")

    lines.extend(
        [
            "Questions to discuss with a clinician: What does this test measure, and how should this result be interpreted in my situation?",
            "This agent does not diagnose, assess urgency, or recommend treatment. Verify extracted values and source wording on the uploaded report.",
        ]
    )
    return "\n".join(lines)


def _render_report_alerts(report_alerts: list[dict[str, Any]]) -> str:
    lines = ["## Wording found in the report text"]
    for item in report_alerts:
        lines.append(f"**Check source wording (page {item['page']}):** “{item['wording']}”")
    return "\n".join(lines)


def _json_payload(raw: str) -> Any:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end < start:
        raise ValueError("Model output did not contain a JSON object.")
    return json.loads(cleaned[start : end + 1])


def _numeric_literal(value: str, unit: str) -> str | None:
    number = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)"
    match = re.fullmatch(rf"\s*({number})\s*(.*?)\s*", value)
    if match is None:
        return None
    suffix = match.group(2).strip()
    if suffix and _normalized_unit(suffix) != _normalized_unit(unit):
        return None
    return match.group(1)


def _parse_decimal(value: str, unit: str) -> float | None:
    literal = _numeric_literal(value, unit)
    if literal is None:
        return None
    number = float(literal)
    return number if math.isfinite(number) else None


def _interval_parts(value: str, unit: str) -> tuple[str, str] | None:
    number = r"([+-]?(?:\d+(?:\.\d*)?|\.\d+))"
    match = re.fullmatch(
        rf"\s*{number}\s*(?:-|–|—|to)\s*{number}\s*(.*?)\s*",
        value,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    suffix = match.group(3).strip()
    if suffix and _normalized_unit(suffix) != _normalized_unit(unit):
        return None
    return match.group(1), match.group(2)


def _parse_interval(value: str, unit: str) -> tuple[float, float] | None:
    parts = _interval_parts(value, unit)
    if parts is None:
        return None
    low, high = float(parts[0]), float(parts[1])
    return (low, high) if math.isfinite(low) and math.isfinite(high) and low <= high else None


def _normalize_image(file_path: Path) -> bytes:
    from PIL import Image

    with Image.open(file_path) as image:
        if getattr(image, "n_frames", 1) > 1:
            raise ValueError("Use one page per image file for a lab report.")
        if image.width * image.height > 20_000_000:
            raise ValueError("This prototype supports images up to 20 megapixels.")
        image = image.convert("RGB")
        image.thumbnail((2000, 2000))
        output = io.BytesIO()
        image.save(output, format="PNG")
        return output.getvalue()


def _normalized_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _normalized_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _normalized_unit(value: str) -> str:
    """Normalize spacing and micro symbols while preserving case-sensitive prefixes."""
    return re.sub(r"\s+", "", value.strip().replace("μ", "u").replace("µ", "u"))


def _markdown_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").strip()

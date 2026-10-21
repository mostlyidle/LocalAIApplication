from __future__ import annotations

import json
from types import SimpleNamespace
from typing import TYPE_CHECKING

import fitz

from app.models.enums import DocumentFormat
from app.services.medical_lab import (
    LabPage,
    assemble_lab_results,
    extract_report_alerts,
    parse_page_observations,
    prepare_lab_pages,
    render_lab_answer,
)

if TYPE_CHECKING:
    from pathlib import Path


def _observation(
    *,
    page: int,
    unit: str,
    excerpt: str,
    page_text: str | None = None,
    result: str | None = None,
    interval: str | None = None,
) -> dict[str, object]:
    return {
        "test_name": "Creatinine",
        "result": result,
        "unit": unit,
        "reference_interval": interval,
        "reference_qualifier": None,
        "report_flag": None,
        "critical_wording": None,
        "source_excerpt": excerpt,
        "page": page,
        "page_text": page_text or excerpt,
        "source_verified": True,
        "source_kind": "text",
    }


def test_test_name_must_be_present_in_source_excerpt() -> None:
    raw = json.dumps(
        {
            "tests": [
                {
                    "test_name": "Glucose",
                    "result": "5.2",
                    "unit": "mmol/L",
                    "reference_interval": "3.9-5.5",
                    "source_excerpt": "Result: 5.2 mmol/L, reference interval 3.9-5.5",
                }
            ]
        }
    )

    observations, valid = parse_page_observations(
        raw,
        LabPage(1, "Glucose result 5.2 mmol/L, reference interval 3.9-5.5"),
    )

    assert valid
    assert len(observations) == 1
    assert not observations[0]["source_verified"]


def test_fenced_observation_array_after_explanatory_text_is_parsed() -> None:
    page_text = "Glucose, fasting | Result: 5.2 mmol/L | Reference interval: 3.9 - 5.5 mmol/L"
    raw = (
        'I will return `{"tests":[]}` if there are no lab tests.\n'
        "```json\n"
        "["
        '{"test_name":"Glucose, fasting","result":"5.2","unit":"mmol/L",'
        '"reference_interval":"3.9 - 5.5 mmol/L","source_excerpt":'
        '"Glucose, fasting | Result: 5.2 mmol/L | Reference interval: '
        '3.9 - 5.5 mmol/L"}'
        "]\n"
        "```"
    )

    observations, valid = parse_page_observations(raw, LabPage(1, page_text))

    assert valid
    assert len(observations) == 1
    assert observations[0]["test_name"] == "Glucose, fasting"
    assert observations[0]["source_verified"]


def test_source_name_is_required_and_explanations_must_be_generic() -> None:
    raw = json.dumps(
        {
            "tests": [
                {
                    "test_name": "Glucose",
                    "result": "5.2",
                    "unit": "mmol/L",
                    "reference_interval": "3.9-5.5",
                    "source_excerpt": "Glucose result 5.2 mmol/L, reference interval 3.9-5.5",
                    "explanation": "This test measures blood glucose, which is high in diabetes.",
                }
            ]
        }
    )

    observations, _ = parse_page_observations(
        raw,
        LabPage(1, "Glucose result 5.2 mmol/L, reference interval 3.9-5.5"),
    )

    assert observations[0]["source_verified"]
    assert observations[0]["explanation"] is None


def test_generic_measurement_explanation_is_preserved() -> None:
    raw = json.dumps(
        {
            "tests": [
                {
                    "test_name": "Glucose",
                    "result": "5.2",
                    "unit": "mmol/L",
                    "reference_interval": "3.9-5.5",
                    "source_excerpt": "Glucose result 5.2 mmol/L, reference interval 3.9-5.5",
                    "explanation": "This test measures glucose in a blood sample.",
                }
            ]
        }
    )

    observations, _ = parse_page_observations(
        raw,
        LabPage(1, "Glucose result 5.2 mmol/L, reference interval 3.9-5.5"),
    )

    assert observations[0]["explanation"] == "This test measures glucose in a blood sample."


def test_generic_test_purpose_explanation_is_preserved() -> None:
    explanation = (
        "This test measures creatinine in blood. It is commonly used to assess kidney function."
    )
    raw = json.dumps(
        {
            "tests": [
                {
                    "test_name": "Creatinine",
                    "result": "82",
                    "unit": "umol/L",
                    "source_excerpt": "Creatinine 82 umol/L",
                    "explanation": explanation,
                }
            ]
        }
    )

    observations, _ = parse_page_observations(
        raw,
        LabPage(1, "Creatinine 82 umol/L"),
    )

    assert observations[0]["explanation"] == explanation


def test_hemoglobin_has_safe_generic_explanation_when_model_omits_it() -> None:
    row = _observation(
        page=1,
        unit="g/dL",
        excerpt="Hemoglobin | Result: 11.3 g/dL",
        result="11.3",
    )
    row["test_name"] = "Hemoglobin"

    result = assemble_lab_results([row])[0]

    assert result["explanation"] == "This test measures hemoglobin in a blood sample."
    assert result["explanation"] in render_lab_answer([result])


def test_hemoglobin_fallback_requires_verified_source_name() -> None:
    row = _observation(
        page=1,
        unit="g/dL",
        excerpt="Unidentified result: 11.3 g/dL",
        result="11.3",
    )
    row["test_name"] = "Hemoglobin"
    row["source_verified"] = False

    result = assemble_lab_results([row])[0]

    assert result["explanation"] is None


def test_model_explanation_requires_verified_test_name() -> None:
    row = _observation(
        page=1,
        unit="g/dL",
        excerpt="Unidentified result: 11.3 g/dL",
        result="11.3",
    )
    row["test_name"] = "Hemoglobin"
    row["explanation"] = "This test measures hemoglobin in a blood sample."
    row["source_verified"] = False

    result = assemble_lab_results([row])[0]

    assert result["explanation"] is None


def test_unit_case_mismatch_does_not_join_across_pages() -> None:
    rows = [
        _observation(page=1, unit="U/L", excerpt="Creatinine 82 U/L", result="82"),
        _observation(
            page=2,
            unit="u/L",
            excerpt="Creatinine u/L reference interval 50-100",
            interval="50-100",
        ),
    ]

    results = assemble_lab_results(rows)

    assert len(results) == 2
    assert all(result["comparison"] == "needs_review" for result in results)


def test_population_qualifier_in_page_context_abstains() -> None:
    page_text = "Reference ranges for women\nCreatinine 82 umol/L 50-100"
    rows = [
        _observation(
            page=1,
            unit="umol/L",
            excerpt="Creatinine 82 umol/L",
            page_text=page_text,
            result="82",
        ),
        _observation(
            page=1,
            unit="umol/L",
            excerpt="Creatinine umol/L reference interval 50-100",
            page_text=page_text,
            interval="50-100",
        ),
    ]

    result = assemble_lab_results(rows)[0]

    assert result["comparison"] == "needs_review"
    assert result["reference_qualifier"]


def test_joined_sources_are_not_duplicated() -> None:
    rows = [
        _observation(page=1, unit="umol/L", excerpt="Creatinine 82 umol/L", result="82"),
        _observation(
            page=2,
            unit="umol/L",
            excerpt="Creatinine umol/L reference interval 50-100",
            interval="50-100",
        ),
    ]

    result = assemble_lab_results(rows)[0]

    assert len(result["sources"]) == 2


def test_matching_units_attached_to_values_and_ranges_are_compared() -> None:
    excerpt = "Creatinine | Result: 82 umol/L | Reference interval: 50 - 100 umol/L"
    rows = [
        _observation(
            page=1,
            unit="umol/L",
            excerpt=excerpt,
            result="82 umol/L",
            interval="50 - 100 umol/L",
        )
    ]

    result = assemble_lab_results(rows)[0]

    assert result["comparison"] == "within_reported_range"
    assert result["comparison_calculation"] == "50 ≤ 82 ≤ 100"


def test_value_with_a_different_attached_unit_is_not_compared() -> None:
    rows = [
        _observation(
            page=1,
            unit="umol/L",
            excerpt="Creatinine | Result: 82 mg/dL | Reference interval: 50 - 100 umol/L",
            result="82 mg/dL",
            interval="50 - 100 umol/L",
        )
    ]

    result = assemble_lab_results(rows)[0]

    assert result["comparison"] == "needs_review"


def test_range_with_a_different_attached_unit_is_not_compared() -> None:
    rows = [
        _observation(
            page=1,
            unit="umol/L",
            excerpt="Creatinine | Result: 82 umol/L | Reference interval: 50 - 100 mg/dL",
            result="82 umol/L",
            interval="50 - 100 mg/dL",
        )
    ]

    result = assemble_lab_results(rows)[0]

    assert result["comparison"] == "needs_review"


def test_report_alerts_are_found_without_model_output() -> None:
    pages = [
        LabPage(2, "Potassium 6.8 mmol/L\nCRITICAL RESULT"),
        LabPage(3, "Instruction:\nContact your\nprovider immediately."),
    ]

    alerts = extract_report_alerts(pages)
    answer = render_lab_answer([], alerts)

    assert alerts == [
        {"page": 2, "wording": "CRITICAL RESULT"},
        {"page": 3, "wording": "Contact your provider immediately."},
    ]
    assert "CRITICAL RESULT" in answer
    assert "page 2" in answer


def test_pdf_table_cells_already_in_page_text_are_not_duplicated(tmp_path: Path) -> None:
    pdf_path = tmp_path / "report.pdf"
    pdf = fitz.open()
    pdf.new_page()
    pdf.save(pdf_path)
    pdf.close()
    parsed = SimpleNamespace(
        blocks=[{"page": 1, "text": "Glucose 5.2 mmol/L 3.9-5.5"}],
        tables=[
            {
                "page": 1,
                "headers": ["Test", "Result", "Unit", "Reference interval"],
                "rows": [["Glucose", "5.2", "mmol/L", "3.9-5.5"]],
            }
        ],
    )

    pages = prepare_lab_pages(
        pdf_path,
        DocumentFormat.PDF,
        parsed,
        vision=False,
    )

    assert pages[0].text.splitlines() == [
        "Glucose 5.2 mmol/L 3.9-5.5",
        "Test | Result | Unit | Reference interval",
    ]


def test_medgemma_renders_scanned_pdf_even_when_parser_supplies_ocr_text(
    tmp_path: Path,
) -> None:
    pdf_path = tmp_path / "mixed-report.pdf"
    source = fitz.open()
    source_page = source.new_page()
    source_page.insert_text((50, 50), "Potassium 6.8 mmol/L 3.5-5.1")
    scan = source_page.get_pixmap().tobytes("png")
    source.close()

    pdf = fitz.open()
    text_page = pdf.new_page()
    text_page.insert_text((50, 50), "Glucose 5.2 mmol/L 3.9-5.5")
    scanned_page = pdf.new_page()
    scanned_page.insert_image(scanned_page.rect, stream=scan)
    pdf.save(pdf_path)
    pdf.close()

    pages = prepare_lab_pages(
        pdf_path,
        DocumentFormat.PDF,
        SimpleNamespace(
            blocks=[
                {"page": 1, "text": "Glucose 5.2 mmol/L 3.9-5.5"},
                {"page": 2, "text": "Potassium 6.8 mmol/L 3.5-5.1"},
            ],
            tables=[],
        ),
        vision=True,
    )

    assert pages[0].text == "Glucose 5.2 mmol/L 3.9-5.5"
    assert pages[0].image_bytes is None
    assert pages[1].text == "Potassium 6.8 mmol/L 3.5-5.1"
    assert pages[1].image_bytes is not None

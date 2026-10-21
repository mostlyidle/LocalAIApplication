"""Run the synthetic medical lab extraction set against local Ollama profiles."""

from __future__ import annotations

import asyncio
import json
import tempfile
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import fitz

from app.agents.registry import AgentRegistry
from app.models.enums import DocumentFormat
from app.models.profile_schemas import TaskRequest
from app.prompt_store import PromptStore
from app.services.document_parser import DocumentParserService
from app.services.llm import llm_service
from app.services.medical_lab import MEDICAL_LAB_PROFILE
from app.services.task_runner import TaskRunner

MODEL_TAGS = ("medgemma1.5:4b", "qwen2.5:7b")
FIELDS = (
    "test_name",
    "result",
    "unit",
    "reference_interval",
    "reference_qualifier",
    "comparison",
    "report_flags",
    "critical_wording",
)


def _write_pdf(path: Path, pages: list[str], *, scanned: bool = False) -> None:
    source_document = fitz.open()
    for text in pages:
        page = source_document.new_page(width=612, height=792)
        page.insert_textbox(
            fitz.Rect(42, 42, 570, 740),
            "SYNTHETIC LAB REPORT\n\n" + text,
            fontname="helv",
            fontsize=20,
            lineheight=1.5,
        )
    if scanned:
        images = [
            page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False).tobytes("png")
            for page in source_document
        ]
        source_document.close()
        document = fitz.open()
        for image in images:
            page = document.new_page(width=612, height=792)
            page.insert_image(page.rect, stream=image)
    else:
        document = source_document
    document.save(path)
    document.close()


def _create_fixtures(root: Path) -> list[dict[str, Any]]:
    text_report = """SYNTHETIC LAB REPORT
Glucose | Result: 5.2 | Unit: mmol/L | Reference interval: 3.9-5.5
Hemoglobin | Result: 11.3 | Unit: g/dL | Reference interval: 12.0-16.0 | Flag: L
"""
    (root / "text_report.txt").write_text(text_report, encoding="utf-8")
    _write_pdf(
        root / "native_report.pdf",
        ["Sodium | Result: 140 | Unit: mmol/L | Reference interval: 135-145"],
    )
    _write_pdf(
        root / "cross_page_report.pdf",
        [
            "Creatinine | Result: 82 | Unit: umol/L",
            "Creatinine | Unit: umol/L | Reference interval: 50-100",
        ],
    )
    _write_pdf(
        root / "scanned_report.pdf",
        [
            "Potassium | Result: 6.8 | Unit: mmol/L | Reference interval: 3.5-5.1\n"
            "CRITICAL RESULT"
        ],
        scanned=True,
    )
    scan = fitz.open(root / "scanned_report.pdf")
    scan[0].get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False).save(root / "report_image.png")
    scan.close()
    (root / "ambiguous_locale.txt").write_text(
        "Calcium | Result: 2,5 | Unit: mmol/L | Reference interval: 2,1-2,6\n",
        encoding="utf-8",
    )
    (root / "qualified_range.txt").write_text(
        "TSH | Result: 2.1 | Unit: mIU/L | Reference interval: 0.4-4.0 | Qualifier: age 65+\n",
        encoding="utf-8",
    )

    return [
        {
            "name": "pasted_text",
            "path": root / "text_report.txt",
            "format": "text",
            "expected": [
                {"test_name": "Glucose", "result": "5.2", "unit": "mmol/L", "reference_interval": "3.9-5.5", "comparison": "within_reported_range", "report_flags": []},
                {"test_name": "Hemoglobin", "result": "11.3", "unit": "g/dL", "reference_interval": "12.0-16.0", "comparison": "below_reported_range", "report_flags": [{"text": "L", "page": 1}]},
            ],
        },
        {
            "name": "native_pdf",
            "path": root / "native_report.pdf",
            "format": "pdf",
            "expected": [
                {"test_name": "Sodium", "result": "140", "unit": "mmol/L", "reference_interval": "135-145", "comparison": "within_reported_range", "report_flags": []},
            ],
        },
        {
            "name": "cross_page_unique_match",
            "path": root / "cross_page_report.pdf",
            "format": "pdf",
            "expected": [
                {"test_name": "Creatinine", "result": "82", "unit": "umol/L", "reference_interval": "50-100", "comparison": "within_reported_range", "report_flags": []},
            ],
        },
        {
            "name": "scanned_pdf",
            "path": root / "scanned_report.pdf",
            "format": "pdf",
            "expected": [
                {"test_name": "Potassium", "result": "6.8", "unit": "mmol/L", "reference_interval": "3.5-5.1", "report_flags": [], "critical_wording": ["CRITICAL RESULT"]},
            ],
        },
        {
            "name": "image_ocr_and_vision",
            "path": root / "report_image.png",
            "format": "png",
            "expected": [
                {"test_name": "Potassium", "result": "6.8", "unit": "mmol/L", "reference_interval": "3.5-5.1", "report_flags": [], "critical_wording": ["CRITICAL RESULT"]},
            ],
        },
        {
            "name": "ambiguous_locale",
            "path": root / "ambiguous_locale.txt",
            "format": "text",
            "expected": [
                {"test_name": "Calcium", "result": "2,5", "unit": "mmol/L", "reference_interval": "2,1-2,6", "comparison": "needs_review", "report_flags": []},
            ],
        },
        {
            "name": "qualified_reference_interval",
            "path": root / "qualified_range.txt",
            "format": "text",
            "expected": [
                {"test_name": "TSH", "result": "2.1", "unit": "mIU/L", "reference_interval": "0.4-4.0", "reference_qualifier": "age 65+", "comparison": "needs_review", "report_flags": []},
            ],
        },
    ]


def _field_metrics(expected: list[dict[str, Any]], predicted: list[dict[str, Any]]) -> dict[str, Any]:
    matches: dict[str, int] = {field: 0 for field in FIELDS}
    missing: dict[str, int] = {field: 0 for field in FIELDS}
    for expected_row in expected:
        match = next(
            (
                row
                for row in predicted
                if str(row.get("test_name", "")).casefold()
                == str(expected_row["test_name"]).casefold()
            ),
            None,
        )
        for field in FIELDS:
            if field not in expected_row:
                continue
            actual = match.get(field) if match is not None else None
            expected_value = expected_row[field]
            if field == "critical_wording":
                actual = [item["wording"] for item in (actual or [])]
            if field == "report_flags":
                actual = [
                    {"text": item["text"], "page": item["page"]}
                    for item in (actual or [])
                ]
            if actual == expected_value:
                matches[field] += 1
            else:
                missing[field] += 1
    expected_flags = {
        (row["test_name"].casefold(), flag["text"].casefold())
        for row in expected
        for flag in row.get("report_flags", [])
    }
    predicted_flags = {
        (row.get("test_name", "").casefold(), flag.get("text", "").casefold())
        for row in predicted
        for flag in row.get("report_flags", [])
    }
    expected_names = {row["test_name"].casefold() for row in expected}
    unexpected_tests = sorted(
        {
            str(row.get("test_name", ""))
            for row in predicted
            if str(row.get("test_name", "")).casefold() not in expected_names
        }
    )
    return {
        "exact_field_matches": matches,
        "field_mismatches": missing,
        "unexpected_tests": unexpected_tests,
        "abstentions": sum(row.get("comparison") == "needs_review" for row in predicted),
        "false_negative_flags": sorted([list(item) for item in expected_flags - predicted_flags]),
        "false_positive_flags": sorted([list(item) for item in predicted_flags - expected_flags]),
    }


async def evaluate() -> dict[str, Any]:
    prompt_dir = Path(__file__).parent / "prompts"
    prompts = PromptStore(prompt_dir)
    registry = AgentRegistry(prompt_dir, prompts)
    runner = TaskRunner(registry, prompts, market_data=None, comfyui=None)  # type: ignore[arg-type]
    parser = DocumentParserService()
    available = await llm_service.list_models(raise_on_error=True)
    inventory = {
        str(model.get("name")): model.get("digest")
        for model in available
        if isinstance(model.get("name"), str)
    }

    with tempfile.TemporaryDirectory(prefix="medical-lab-eval-") as temp_dir:
        fixtures = _create_fixtures(Path(temp_dir))
        evaluations: list[dict[str, Any]] = []
        for model in MODEL_TAGS:
            if model not in inventory:
                evaluations.append({"model": model, "skipped": "not installed in local Ollama"})
                continue
            cases: list[dict[str, Any]] = []
            for case in fixtures:
                path = Path(case["path"])
                if model == "qwen2.5:7b":
                    parsed = await parser.parse(path, DocumentFormat(case["format"]))
                    if not parsed.text.strip():
                        cases.append(
                            {"case": case["name"], "skipped": "no text from current parser"}
                        )
                        continue
                document = SimpleNamespace(
                    id=case["name"],
                    filename=path.name,
                    storage_path=str(path),
                    format=case["format"],
                )
                result = await runner.run(
                    TaskRequest(
                        prompt="Extract the lab values and explain what each test measures.",
                        agent_name=MEDICAL_LAB_PROFILE,
                        target="document",
                        inference={"model": model},
                    ),
                    request_id=str(uuid.uuid4()),
                    document=document,
                )
                predicted = result.artifacts.get("tests", [])
                expected = case["expected"]
                cases.append(
                    {
                        "case": case["name"],
                        "metrics": _field_metrics(expected, predicted),
                        "expected": expected,
                        "predicted": predicted,
                    }
                )
            evaluations.append(
                {
                    "model": model,
                    "digest": inventory[model],
                    "inference": registry.resolve_inference(
                        registry.get(MEDICAL_LAB_PROFILE),
                        TaskRequest(
                            prompt="Evaluation metadata",
                            agent_name=MEDICAL_LAB_PROFILE,
                            target="document",
                            inference={"model": model},
                        ),
                    ).model_dump(),
                    "cases": cases,
                }
            )
    return {"clinical_validation": False, "evaluations": evaluations}


def main() -> None:
    print(json.dumps(asyncio.run(evaluate()), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

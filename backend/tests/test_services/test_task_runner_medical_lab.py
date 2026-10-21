from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.agents.registry import AgentRegistry
from app.models.profile_schemas import TaskRequest
from app.prompt_store import PromptStore
from app.services.task_runner import TaskRunner


def _runner() -> TaskRunner:
    prompt_dir = Path(__file__).resolve().parents[2] / "app" / "prompts"
    prompts = PromptStore(prompt_dir)
    return TaskRunner(
        AgentRegistry(prompt_dir, prompts),
        prompts,
        market_data=SimpleNamespace(snapshot=AsyncMock()),
        comfyui=SimpleNamespace(submit=AsyncMock()),
    )


async def test_medical_lab_profile_generates_advice_from_verified_findings_only() -> None:
    source = "Glucose 12 mmol/L reference interval 3.9-5.5"
    extracted = {
        "tests": [
            {
                "test_name": "Glucose",
                "result": "12",
                "unit": "mmol/L",
                "reference_interval": "3.9-5.5",
                "source_excerpt": source,
            }
        ]
    }
    model = SimpleNamespace(
        ainvoke=AsyncMock(
            side_effect=[
                SimpleNamespace(content=json.dumps(extracted)),
                SimpleNamespace(
                    content=(
                        "Likely diagnosis: possible diabetes mellitus, to be confirmed. "
                        "Treatment advice: a clinician may consider nutrition and activity "
                        "changes and glucose-lowering medicines depending on the full history."
                    )
                ),
            ]
        )
    )

    with patch("app.services.task_runner.llm_service.get_chat_model", return_value=model):
        result = await _runner().run(
            TaskRequest(
                prompt="What might this indicate, and what treatment options are common?",
                agent_name="medical_lab_explainer",
                context=source,
            ),
            request_id="medical-lab-advice",
        )

    assert model.ainvoke.await_count == 2
    interpretation_messages = model.ainvoke.call_args_list[1].args[0]
    assert "likely diagnoses and treatment advice" in interpretation_messages[0].content
    assert "treatment advice for this situation" in interpretation_messages[0].content
    assert source in interpretation_messages[1].content
    assert result.artifacts["interpretation_findings"] == 1
    assert "Likely diagnosis and treatment advice" in result.answer
    assert "Treatment advice: a clinician may consider" in result.answer
    assert "This is not medical advice" in result.answer


async def test_medical_lab_profile_skips_advice_without_verified_findings() -> None:
    model = SimpleNamespace(
        ainvoke=AsyncMock(return_value=SimpleNamespace(content="not valid JSON"))
    )

    with patch("app.services.task_runner.llm_service.get_chat_model", return_value=model):
        result = await _runner().run(
            TaskRequest(
                prompt="What diagnosis and treatment do you recommend?",
                agent_name="medical_lab_explainer",
                context="Unreadable report content",
            ),
            request_id="medical-lab-abstain",
        )

    model.ainvoke.assert_awaited_once()
    assert result.artifacts["interpretation_findings"] == 0
    assert "did not generate diagnosis or treatment advice" in result.limitations[-1]


async def test_medical_interpretation_receives_context_from_each_report_page(tmp_path) -> None:
    import fitz

    report = tmp_path / "synthetic-history-and-repeat-tests.pdf"
    pdf = fitz.open()
    for _ in range(3):
        pdf.new_page()
    pdf.save(report)
    pdf.close()

    page_text = [
        "SYNTHETIC ONLY",
        "Fasting plasma glucose 146 mg/dL 70 - 99\nHemoglobin A1c 7.2 % 4.0 - 5.6",
        "Fasting plasma glucose, repeat 143 mg/dL 70 - 99\nHemoglobin A1c, repeat 7.1 % 4.0 - 5.6",
    ]
    parsed = SimpleNamespace(
        blocks=[{"page": index, "text": text} for index, text in enumerate(page_text, 1)],
        tables=[],
    )
    model = SimpleNamespace(
        ainvoke=AsyncMock(
            side_effect=[
                SimpleNamespace(content='{"tests":[]}'),
                SimpleNamespace(
                    content=json.dumps(
                        {
                            "tests": [
                                {
                                    "test_name": "Fasting plasma glucose",
                                    "result": "146",
                                    "unit": "mg/dL",
                                    "reference_interval": "70 - 99",
                                    "source_excerpt": page_text[1].splitlines()[0],
                                },
                                {
                                    "test_name": "Hemoglobin A1c",
                                    "result": "7.2",
                                    "unit": "%",
                                    "reference_interval": "4.0 - 5.6",
                                    "source_excerpt": page_text[1].splitlines()[1],
                                },
                            ]
                        }
                    )
                ),
                SimpleNamespace(
                    content=json.dumps(
                        {
                            "tests": [
                                {
                                    "test_name": "Fasting plasma glucose, repeat",
                                    "result": "143",
                                    "unit": "mg/dL",
                                    "reference_interval": "70 - 99",
                                    "source_excerpt": page_text[2].splitlines()[0],
                                },
                                {
                                    "test_name": "Hemoglobin A1c, repeat",
                                    "result": "7.1",
                                    "unit": "%",
                                    "reference_interval": "4.0 - 5.6",
                                    "source_excerpt": page_text[2].splitlines()[1],
                                },
                            ]
                        }
                    )
                ),
                SimpleNamespace(
                    content=(
                        "<unused94>thought internal reasoning<unused95>"
                        "Likely diagnosis: diabetes mellitus. Treatment advice: clinician-guided care."
                    )
                ),
            ]
        )
    )
    runner = _runner()

    async def add_ocr_history(page):
        if page.number == 1:
            return replace(
                page,
                text=page.text
                + "\n47-year-old woman with six weeks of increased thirst and urination.",
            )
        return page

    with (
        patch.object(runner._parser, "parse", new=AsyncMock(return_value=parsed)),
        patch(
            "app.services.task_runner.add_local_ocr",
            new=AsyncMock(side_effect=add_ocr_history),
        ),
        patch("app.services.task_runner.llm_service.get_chat_model", return_value=model),
    ):
        result = await runner.run(
            TaskRequest(
                prompt="Give the likely diagnosis and treatment suggestions.",
                agent_name="medical_lab_explainer",
                target="document",
                inference={"model": "medgemma1.5:4b"},
            ),
            request_id="medical-report-context",
            document=SimpleNamespace(
                id="synthetic-context",
                filename=report.name,
                storage_path=str(report),
                format="pdf",
            ),
        )

    interpretation_messages = model.ainvoke.call_args_list[-1].args[0]
    interpretation_prompt = interpretation_messages[1].content
    assert "47-year-old woman" in interpretation_prompt
    assert "repeat 143 mg/dL" in interpretation_prompt
    assert "repeat 7.1 %" in interpretation_prompt
    assert "internal reasoning" not in result.answer
    assert "Likely diagnosis: diabetes mellitus" in result.answer

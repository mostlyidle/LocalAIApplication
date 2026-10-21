from __future__ import annotations

import json
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

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from PIL import Image

from app.agents.registry import AgentRegistry
from app.models.db_models import Document
from app.models.profile_schemas import TaskRequest
from app.prompt_store import PromptStore
from app.services.task_runner import TaskRunner


def _runner(market_data=None, comfyui=None) -> TaskRunner:
    prompt_dir = Path(__file__).resolve().parents[2] / "app" / "prompts"
    prompts = PromptStore(prompt_dir)
    return TaskRunner(
        AgentRegistry(prompt_dir, prompts),
        prompts,
        market_data=market_data or SimpleNamespace(snapshot=AsyncMock()),
        comfyui=comfyui or SimpleNamespace(submit=AsyncMock()),
    )


def _image_document(tmp_path: Path) -> Document:
    image_path = tmp_path / "sample.png"
    Image.new("RGB", (12, 8), color=(50, 100, 150)).save(image_path)
    return Document(
        id="uploaded-image-id",
        filename="sample.png",
        format="png",
        size_bytes=image_path.stat().st_size,
        storage_path=str(image_path),
    )


async def test_image_analysis_uses_profile_model_and_uploaded_image_bytes(
    tmp_path: Path,
) -> None:
    document = _image_document(tmp_path)
    model = SimpleNamespace(
        ainvoke=AsyncMock(return_value=SimpleNamespace(content="A blue swatch."))
    )
    with patch(
        "app.services.task_runner.llm_service.get_chat_model", return_value=model
    ) as get_model:
        result = await _runner().run(
            TaskRequest(
                prompt="Describe the image.",
                agent_name="image_analysis",
                asset_id=document.id,
            ),
            request_id="request-1",
            document=document,
        )

    get_model.assert_called_once()
    assert get_model.call_args.kwargs["model"] == "qwen2.5vl:7b"
    assert result.agent == "image_analysis"
    assert result.answer == "A blue swatch."
    assert result.artifacts["asset_id"] == document.id
    assert result.artifacts["width"] == 12
    human_content = model.ainvoke.call_args.args[0][1].content
    assert human_content[1]["image_url"].startswith("data:image/png;base64,")
    assert result.metadata is not None
    assert result.metadata.request_id == "request-1"


async def test_image_fraud_reports_triage_limitations_without_calling_a_model(
    tmp_path: Path,
) -> None:
    document = _image_document(tmp_path)
    with patch("app.services.task_runner.llm_service.get_chat_model") as get_model:
        result = await _runner().run(
            TaskRequest(
                prompt="Check the image.",
                target="image_fraud",
                asset_id=document.id,
            ),
            request_id="request-2",
            document=document,
        )

    get_model.assert_not_called()
    assert result.agent == "image_fraud"
    assert result.artifacts["metadata"]["format"] == "PNG"
    assert result.artifacts["ela_score"] is None
    assert len(result.limitations) == 2


async def test_image_specialist_rejects_a_document_asset(tmp_path: Path) -> None:
    path = tmp_path / "note.txt"
    path.write_text("not an image", encoding="utf-8")
    document = Document(
        id="text-id",
        filename=path.name,
        format="text",
        size_bytes=path.stat().st_size,
        storage_path=str(path),
    )
    with pytest.raises(HTTPException) as error:
        await _runner().run(
            TaskRequest(prompt="Describe", target="image_analysis", asset_id=document.id),
            request_id="request-3",
            document=document,
        )
    assert error.value.status_code == 422


async def test_stock_research_combines_live_snapshot_and_user_context() -> None:
    market_data = SimpleNamespace(
        snapshot=AsyncMock(
            return_value={"provider": "Finnhub", "symbol": "AAPL", "quote": {"current": 1}}
        )
    )
    model = SimpleNamespace(ainvoke=AsyncMock(return_value=SimpleNamespace(content="Research.")))
    with patch("app.services.task_runner.llm_service.get_chat_model", return_value=model):
        result = await _runner(market_data=market_data).run(
            TaskRequest(prompt="Assess risks.", target="stock_research", symbol="aapl", context="Company notes."),
            request_id="request-stock",
        )

    market_data.snapshot.assert_awaited_once_with("aapl")
    prompt = model.ainvoke.call_args.args[0][1].content
    assert "Finnhub" in prompt
    assert "Company notes." in prompt
    assert result.artifacts["market_data"]["symbol"] == "AAPL"


async def test_image_generation_submits_bounded_workflow() -> None:
    comfyui = SimpleNamespace(submit=AsyncMock(return_value={"prompt_id": "job-123"}))
    result = await _runner(comfyui=comfyui).run(
        TaskRequest(
            prompt="Render the scene.",
            target="image_generation",
            workflow={"1": {"class_type": "SaveImage", "inputs": {}}},
        ),
        request_id="request-image-generation",
    )

    comfyui.submit.assert_awaited_once()
    assert result.artifacts["prompt_id"] == "job-123"


async def test_software_engineer_reviews_only_configured_workspace_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "review.py"
    source.write_text("def calculate():\n    return 42\n", encoding="utf-8")
    monkeypatch.setattr("app.services.task_runner.settings.agent_workspace_root", tmp_path)
    model = SimpleNamespace(ainvoke=AsyncMock(return_value=SimpleNamespace(content="Looks good.")))
    with patch("app.services.task_runner.llm_service.get_chat_model", return_value=model):
        result = await _runner().run(
            TaskRequest(prompt="Review this project.", target="software_engineer"),
            request_id="request-review",
        )

    prompt = model.ainvoke.call_args.args[0][1].content
    assert "return 42" in prompt
    assert result.artifacts["source_files"] == ["review.py"]
    assert len(result.limitations) == 2

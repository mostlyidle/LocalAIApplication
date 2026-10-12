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


def _runner() -> TaskRunner:
    prompt_dir = Path(__file__).resolve().parents[2] / "app" / "prompts"
    prompts = PromptStore(prompt_dir)
    return TaskRunner(AgentRegistry(prompt_dir, prompts), prompts)


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

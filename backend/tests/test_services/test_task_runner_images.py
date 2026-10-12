from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from PIL import Image

from app.agents.registry import AgentRegistry
from app.models.db_models import LEGACY_ACCOUNT_ID, Document
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
        owner_id=LEGACY_ACCOUNT_ID,
        id="uploaded-image-id",
        filename="sample.png",
        format="png",
        size_bytes=image_path.stat().st_size,
        storage_path=str(image_path),
    )


@pytest.mark.parametrize("agent", ["image_analysis", "image_fraud"])
async def test_image_specialists_normalize_pillow_size_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, agent: str
) -> None:
    document = _image_document(tmp_path)
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 10)
    with pytest.raises(HTTPException) as error:
        await _runner().run(
            TaskRequest(prompt="Inspect image", agent_name=agent, asset_id=document.id),
            request_id="oversized",
            document=document,
        )
    assert error.value.status_code == 422
    assert "pixel processing limit" in error.value.detail


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


async def test_image_analysis_receives_approved_memory_as_separate_prompt_context(
    tmp_path: Path,
) -> None:
    document = _image_document(tmp_path)
    model = SimpleNamespace(
        ainvoke=AsyncMock(return_value=SimpleNamespace(content="A blue swatch."))
    )
    with (
        patch("app.services.task_runner.llm_service.get_chat_model", return_value=model),
        patch(
            "app.services.memory_context.load_account_memory_context",
            new_callable=AsyncMock,
            return_value='[{"type":"preference","content":"Concise"}]',
        ),
    ):
        result = await _runner().run(
            TaskRequest(
                prompt="Describe the image.",
                agent_name="image_analysis",
                asset_id=document.id,
            ),
            request_id="request-memory",
            document=document,
            owner_id=LEGACY_ACCOUNT_ID,
        )

    prompt_messages = model.ainvoke.call_args.args[0]
    system_messages = [message for message in prompt_messages if message.type == "system"]
    assert result.answer == "A blue swatch."
    assert len(system_messages) == 2
    assert "Concise" in system_messages[1].content


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
        owner_id=LEGACY_ACCOUNT_ID,
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
            return_value={
                "provider": "Finnhub",
                "symbol": "AAPL",
                "quote": {"current": 1},
                "warnings": ["News is unavailable"],
            }
        )
    )
    model = SimpleNamespace(ainvoke=AsyncMock(return_value=SimpleNamespace(content="Research.")))
    with patch("app.services.task_runner.llm_service.get_chat_model", return_value=model):
        result = await _runner(market_data=market_data).run(
            TaskRequest(
                prompt="Assess risks.",
                target="stock_research",
                symbol="aapl",
                context="Company notes.",
            ),
            request_id="request-stock",
        )

    market_data.snapshot.assert_awaited_once_with("aapl")
    prompt = model.ainvoke.call_args.args[0][1].content
    assert "Finnhub" in prompt
    assert "Company notes." in prompt
    assert result.artifacts["market_data"]["symbol"] == "AAPL"
    assert result.limitations == ["News is unavailable"]


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
    account_id = "11111111-1111-4111-8111-111111111111"
    account_workspace = tmp_path / account_id
    account_workspace.mkdir()
    other_workspace = tmp_path / "22222222-2222-4222-8222-222222222222"
    other_workspace.mkdir()
    source = account_workspace / "review.py"
    source.write_text("def calculate():\n    return 42\n", encoding="utf-8")
    (other_workspace / "private.py").write_text("other-account-secret", encoding="utf-8")
    monkeypatch.setattr("app.services.task_runner.settings.agent_workspace_root", tmp_path)
    model = SimpleNamespace(ainvoke=AsyncMock(return_value=SimpleNamespace(content="Looks good.")))
    with patch("app.services.task_runner.llm_service.get_chat_model", return_value=model):
        result = await _runner().run(
            TaskRequest(prompt="Review this project.", target="software_engineer"),
            request_id="request-review",
            owner_id=account_id,
        )

    prompt = model.ainvoke.call_args.args[0][1].content
    assert "return 42" in prompt
    assert "other-account-secret" not in prompt
    assert result.artifacts["source_files"] == ["review.py"]
    assert len(result.limitations) == 2


async def test_software_engineer_rejects_unassigned_account_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "another-account").mkdir()
    monkeypatch.setattr("app.services.task_runner.settings.agent_workspace_root", tmp_path)

    with pytest.raises(HTTPException, match="No workspace is assigned"):
        await _runner().run(
            TaskRequest(prompt="Review this project.", target="software_engineer"),
            request_id="request-review-unassigned",
            owner_id="unassigned-account",
        )


async def test_rag_task_preserves_hybrid_citation_provenance() -> None:
    search = SimpleNamespace(
        passages=[
            {
                "content": "Relevant evidence.",
                "score": 0.04,
                "score_type": "rrf",
                "metadata": {
                    "filename": "guide.pdf",
                    "page": 3,
                    "source_chunk_id": "chunk-3",
                },
            }
        ],
        retrieval={"strategy": "hybrid_rrf"},
    )
    model = SimpleNamespace(
        ainvoke=AsyncMock(return_value=SimpleNamespace(content="Grounded answer."))
    )
    with (
        patch(
            "app.services.hybrid_vector_store.hybrid_vector_store_service.search_with_provenance",
            new_callable=AsyncMock,
            return_value=search,
        ) as search_with_provenance,
        patch("app.services.task_runner.llm_service.get_chat_model", return_value=model),
    ):
        result = await _runner().run(
            TaskRequest(prompt="What is relevant?", agent_name="rag_v2", collection="manuals"),
            request_id="request-rag",
        )

    search_with_provenance.assert_awaited_once()
    assert search_with_provenance.call_args.kwargs["collection"] == "manuals"
    assert search_with_provenance.call_args.kwargs["agent_name"] == "rag_v2"
    assert result.artifacts["citations"][0]["filename"] == "guide.pdf"
    assert result.artifacts["citations"][0]["page"] == 3
    assert result.artifacts["citations"][0]["score_type"] == "rrf"

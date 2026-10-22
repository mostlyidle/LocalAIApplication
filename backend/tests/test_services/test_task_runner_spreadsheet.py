from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.agents.registry import AgentRegistry
from app.models.db_models import LEGACY_ACCOUNT_ID, Document
from app.models.profile_schemas import TaskRequest
from app.prompt_store import PromptStore
from app.services.spreadsheet import SpreadsheetPlan
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


async def test_spreadsheet_profile_executes_structured_plan(tmp_path: Path) -> None:
    path = tmp_path / "sales.csv"
    path.write_text("Team,Revenue\nWest,10\nEast,25\nWest,15\n", encoding="utf-8")
    document = Document(
        owner_id=LEGACY_ACCOUNT_ID,
        id="spreadsheet-id",
        filename="sales.csv",
        format="csv",
        size_bytes=path.stat().st_size,
        storage_path=str(path),
    )
    chain = SimpleNamespace(
        ainvoke=AsyncMock(
            return_value=SpreadsheetPlan(
                group_by=["Team"], aggregate="sum", column="Revenue", limit=10
            )
        )
    )
    model = SimpleNamespace(with_structured_output=lambda schema: chain)

    with patch("app.services.task_runner.llm_service.get_chat_model", return_value=model):
        result = await _runner().run(
            TaskRequest(prompt="Total revenue by team", asset_id=document.id, target="auto"),
            request_id="spreadsheet-test",
            document=document,
        )

    assert result.metadata is not None
    assert result.metadata.target == "spreadsheet"
    assert result.agent == "spreadsheet_analyst"
    assert result.artifacts["rows"] == [
        {"Team": "West", "sum_Revenue": 25.0},
        {"Team": "East", "sum_Revenue": 25.0},
    ]
    assert "Source rows" in result.answer
    chain.ainvoke.assert_awaited_once()


async def test_spreadsheet_profile_abstains_on_unsupported_plan(tmp_path: Path) -> None:
    path = tmp_path / "data.csv"
    path.write_text("Name\nA\n", encoding="utf-8")
    document = Document(
        owner_id=LEGACY_ACCOUNT_ID,
        id="spreadsheet-id",
        filename="data.csv",
        format="csv",
        size_bytes=path.stat().st_size,
        storage_path=str(path),
    )
    chain = SimpleNamespace(ainvoke=AsyncMock(return_value=SpreadsheetPlan(supported=False)))
    model = SimpleNamespace(with_structured_output=lambda schema: chain)

    with patch("app.services.task_runner.llm_service.get_chat_model", return_value=model):
        result = await _runner().run(
            TaskRequest(prompt="Invent a chart", agent_name="spreadsheet_analyst"),
            request_id="unsupported-test",
            document=document,
        )

    assert result.limitations
    assert "couldn't safely translate" in result.answer
    assert "rows" not in result.artifacts

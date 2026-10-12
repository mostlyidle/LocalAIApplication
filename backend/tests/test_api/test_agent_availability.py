from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.registry import AgentRegistry
from app.api.middleware.error_handler import LLMConnectionError
from app.prompt_store import PromptStore


@pytest.mark.parametrize("inventory, expected", [
    ([{"name": "llama3.2:3b"}], {"qwen2.5:7b": False, "llama3.2:3b": True}),
    ([], {"qwen2.5:7b": False, "llama3.2:3b": False}),
    (None, {"qwen2.5:7b": None, "llama3.2:3b": None}),
])
async def test_catalog_separates_profile_enablement_from_model_availability(client, inventory, expected) -> None:
    directory = Path(__file__).resolve().parents[2] / "app" / "prompts"
    client._transport.app.state.agent_registry = AgentRegistry(directory, PromptStore(directory))
    fetch = AsyncMock(return_value=inventory, side_effect=LLMConnectionError() if inventory is None else None)
    with patch("app.api.routes.agents.llm_service.list_models", fetch):
        response = await client.get("/api/v1/agents")
    assert response.status_code == 200
    agents = {agent["name"]: agent for agent in response.json()["agents"]}
    assert agents["rag"]["model_availability"] == expected
    assert agents["image_generation"]["model_availability"] == {}
    assert len(agents) == 11
    fetch.assert_awaited_once_with(raise_on_error=True)

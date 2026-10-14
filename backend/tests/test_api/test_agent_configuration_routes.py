"""Shared agent profile prompt management routes."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest

from app.agents.registry import AgentRegistry
from app.prompt_store import PromptStore
from app.services.llm import llm_service

if TYPE_CHECKING:
    from fastapi import FastAPI
    from httpx import AsyncClient


@pytest.fixture
def configured_registry(app: FastAPI) -> AgentRegistry:
    prompt_dir = Path(__file__).resolve().parents[2] / "app" / "prompts"
    registry = AgentRegistry(prompt_dir, PromptStore(prompt_dir))
    app.state.agent_registry = registry
    return registry


@pytest.mark.asyncio
async def test_create_edit_and_archive_custom_agent(
    client: AsyncClient,
    configured_registry: AgentRegistry,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(llm_service, "list_models", AsyncMock(return_value=[]))
    headers = {"X-CSRF-Token": "test-csrf-token"}

    prompt_edit = await client.patch(
        "/api/v1/agents/chat",
        json={"system_prompt": "Speak like a careful editor."},
        headers=headers,
    )
    assert prompt_edit.status_code == 200
    assert configured_registry.system_prompt("chat") == "Speak like a careful editor."
    prompt_reset = await client.patch(
        "/api/v1/agents/chat",
        json={"system_prompt": None},
        headers=headers,
    )
    assert prompt_reset.status_code == 200
    assert "helpful, knowledgeable AI assistant" in configured_registry.system_prompt("chat")
    prompt_not_applicable = await client.patch(
        "/api/v1/agents/image_fraud",
        json={"system_prompt": "Unused."},
        headers=headers,
    )
    assert prompt_not_applicable.status_code == 422

    created_response = await client.post(
        "/api/v1/agents",
        json={
            "source_agent": "chat",
            "display_name": "Brief Helper",
            "description": "Answers in brief sentences.",
        },
        headers=headers,
    )
    assert created_response.status_code == 200
    created = next(
        item for item in created_response.json()["agents"] if item["name"] == "brief_helper"
    )
    assert created["is_custom"] is True
    assert created["target"] == "chat"

    update_response = await client.patch(
        "/api/v1/agents/brief_helper",
        json={"system_prompt": "Use short sentences."},
        headers=headers,
    )
    assert update_response.status_code == 200
    assert configured_registry.system_prompt("brief_helper") == "Use short sentences."

    archive_response = await client.patch(
        "/api/v1/agents/brief_helper",
        json={"archived": True},
        headers=headers,
    )
    assert archive_response.status_code == 200
    listed = await client.get("/api/v1/agents")
    assert all(item["name"] != "brief_helper" for item in listed.json()["agents"])
    archived = await client.get("/api/v1/agents?include_archived=true")
    record = next(item for item in archived.json()["agents"] if item["name"] == "brief_helper")
    assert record["archived"] is True

    restore_response = await client.patch(
        "/api/v1/agents/brief_helper",
        json={"archived": False},
        headers=headers,
    )
    assert restore_response.status_code == 200
    assert configured_registry.get("brief_helper") is not None

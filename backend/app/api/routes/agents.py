"""Agent catalog and local agent configuration endpoints."""

from __future__ import annotations

import re
import unicodedata

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: TC002

from app.agents.registry import INFERENCE_TARGETS, AgentCatalogResponse, AgentManifest
from app.api.middleware.error_handler import LLMConnectionError
from app.dependencies import get_authenticated_session, get_db
from app.models.db_models import AgentConfiguration
from app.services.auth import AuthenticatedSession  # noqa: TC001
from app.services.llm import llm_service

router = APIRouter()


class AgentCreateRequest(BaseModel):
    """Validated fields for creating a specialist from an existing agent."""

    source_agent: str = Field(pattern=r"^[a-z][a-z0-9_]{0,62}$")
    display_name: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=500)


class AgentUpdateRequest(BaseModel):
    """Optional fields for updating a prompt or custom agent profile."""

    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, min_length=1, max_length=500)
    system_prompt: str | None = Field(default=None, max_length=20_000)
    archived: bool | None = None


async def _refresh_registry(request: Request, db: AsyncSession) -> None:
    rows = (await db.execute(select(AgentConfiguration))).scalars().all()
    request.app.state.agent_registry.apply_configurations(list(rows))


@router.get("/agents", response_model=AgentCatalogResponse)
async def list_agents(
    request: Request,
    include_archived: bool = False,
    _authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> AgentCatalogResponse:
    """List available agents and their editable behavioral prompts."""
    await _refresh_registry(request, db)
    catalog = request.app.state.agent_registry.capabilities(include_archived=include_archived)
    try:
        models = await llm_service.list_models(raise_on_error=True)
        installed = {
            model["name"] if ":" in model["name"] else model["name"] + ":latest" for model in models
        }
    except LLMConnectionError:
        installed = None
    for agent in catalog.agents:
        if agent.inference:
            agent.model_availability = {
                model: None
                if installed is None
                else (model if ":" in model else model + ":latest") in installed
                for model in agent.inference.allowed_models
            }
    return catalog


@router.post("/agents", response_model=AgentCatalogResponse)
async def create_agent(
    body: AgentCreateRequest,
    request: Request,
    _authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> AgentCatalogResponse:
    """Create a specialist by copying one existing LLM agent profile."""
    registry = request.app.state.agent_registry
    await _refresh_registry(request, db)
    source = registry.get(body.source_agent)
    if source is None or source.target not in INFERENCE_TARGETS:
        raise HTTPException(status_code=422, detail="Choose an available LLM agent to copy.")

    slug = _agent_slug(body.display_name)
    if registry.get(slug) or any(item.name == slug for item in registry.capabilities(include_archived=True).agents):
        raise HTTPException(status_code=409, detail="An agent with this name already exists.")

    profile = AgentManifest.model_validate(
        source.model_dump()
        | {"name": slug, "description": body.description, "default_for_target": False}
    )
    db.add(
        AgentConfiguration(
            name=slug,
            display_name=body.display_name.strip(),
            target=profile.target,
            description=body.description,
            system_prompt=registry.system_prompt(source.name),
            base_agent=registry.prompt_source(source.name),
            manifest_json=profile.model_dump_json(),
            is_custom=True,
        )
    )
    await db.commit()
    await _refresh_registry(request, db)
    return registry.capabilities(include_archived=True)


@router.patch("/agents/{agent_name}", response_model=AgentCatalogResponse)
async def update_agent(
    agent_name: str,
    body: AgentUpdateRequest,
    request: Request,
    _authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> AgentCatalogResponse:
    """Update a prompt, reset it to default, or archive a custom agent."""
    registry = request.app.state.agent_registry
    await _refresh_registry(request, db)
    profile = registry.get(agent_name, include_archived=True)
    if profile is None:
        raise HTTPException(status_code=404, detail="Agent not found.")
    result = await db.execute(
        select(AgentConfiguration).where(AgentConfiguration.name == agent_name)
    )
    config = result.scalar_one_or_none()
    is_custom = bool(config and config.is_custom)
    if body.archived is not None and not is_custom:
        raise HTTPException(status_code=422, detail="Built-in agents cannot be archived.")
    if (body.display_name is not None or body.description is not None) and not is_custom:
        raise HTTPException(status_code=422, detail="Built-in agent details cannot be changed.")
    if profile.inference is None and "system_prompt" in body.model_fields_set:
        raise HTTPException(status_code=422, detail="This agent does not use a system prompt.")
    if body.display_name is not None and not body.display_name.strip():
        raise HTTPException(status_code=422, detail="Agent name cannot be blank.")
    if body.description is not None and not body.description.strip():
        raise HTTPException(status_code=422, detail="Agent description cannot be blank.")

    if config is None:
        config = AgentConfiguration(
            name=agent_name,
            display_name=agent_name.replace("_", " ").title(),
            target=profile.target,
            description=profile.description,
        )
        db.add(config)
    if body.display_name is not None:
        config.display_name = body.display_name.strip()
    if body.description is not None:
        config.description = body.description
    if "system_prompt" in body.model_fields_set:
        config.system_prompt = body.system_prompt.strip() if body.system_prompt is not None else None
    if body.archived is not None:
        config.archived = body.archived
    await db.commit()
    await _refresh_registry(request, db)
    return registry.capabilities(include_archived=True)


def _agent_slug(display_name: str) -> str:
    normalized = unicodedata.normalize("NFKD", display_name.strip().lower())
    ascii_name = normalized.encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "_", ascii_name).strip("_")[:63].strip("_")
    if not slug or not slug[0].isalpha():
        raise HTTPException(status_code=422, detail="Agent name must contain a letter.")
    return slug

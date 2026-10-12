"""Agent profile discovery endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.agents.registry import AgentCatalogResponse
from app.api.middleware.error_handler import LLMConnectionError
from app.dependencies import get_authenticated_session
from app.services.auth import AuthenticatedSession  # noqa: TC001
from app.services.llm import llm_service

router = APIRouter()


@router.get("/agents", response_model=AgentCatalogResponse)
async def list_agents(
    request: Request,
    _authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
) -> AgentCatalogResponse:
    """List enabled profile names and their approved configuration bounds."""
    catalog = request.app.state.agent_registry.capabilities()
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

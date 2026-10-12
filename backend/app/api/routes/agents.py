"""Agent profile discovery endpoint."""

from fastapi import APIRouter, Request

from app.agents.registry import AgentCatalogResponse

router = APIRouter()


@router.get("/agents", response_model=AgentCatalogResponse)
async def list_agents(request: Request) -> AgentCatalogResponse:
    """List enabled profile names and their approved configuration bounds."""
    return request.app.state.agent_registry.capabilities()

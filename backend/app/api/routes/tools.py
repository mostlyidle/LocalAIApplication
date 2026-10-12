"""Tool registry, direct tool execution, and health check endpoints.

Provides:
    GET  /tools          — List all available tools with metadata.
    POST /tools/execute  — Execute a tool directly by name.
    GET  /health         — Health check for all dependent services.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx
import structlog
from fastapi import APIRouter, Request

from app.api.middleware.rate_limiting import limiter
from app.config import settings
from app.models.enums import AgentType
from app.models.schemas import (
    HealthResponse,
    ServiceHealth,
    ToolExecuteRequest,
    ToolExecuteResponse,
    ToolInfo,
)
from app.tools import (
    all_tools,
    calculator_tools,
    document_tools,
    filesystem_tools,
    rag_tools,
    sql_tools,
    web_tools,
)

logger = structlog.get_logger(__name__)
router = APIRouter()

REQUIRED_READINESS_TIMEOUT_SECONDS = 5.0

# Map tool names to their agent domain
_TOOL_AGENT_MAP: dict[str, AgentType] = {}
for tool in sql_tools:
    _TOOL_AGENT_MAP[tool.name] = AgentType.SQL
for tool in document_tools:
    _TOOL_AGENT_MAP[tool.name] = AgentType.DOCUMENT
for tool in rag_tools:
    _TOOL_AGENT_MAP[tool.name] = AgentType.RAG
for tool in web_tools:
    _TOOL_AGENT_MAP[tool.name] = AgentType.WEB
for tool in filesystem_tools:
    _TOOL_AGENT_MAP[tool.name] = AgentType.CHAT
for tool in calculator_tools:
    _TOOL_AGENT_MAP[tool.name] = AgentType.CHAT

# Build a name -> tool lookup
_TOOL_LOOKUP = {tool.name: tool for tool in all_tools}


# ---------------------------------------------------------------------------
# GET /tools — list all tools
# ---------------------------------------------------------------------------


@router.get("/tools", response_model=list[ToolInfo])
async def list_tools() -> list[ToolInfo]:
    """List all available tools with their metadata and parameter schemas."""
    result = []
    for tool in all_tools:
        # Extract parameter schema from the tool's args_schema
        params: dict[str, Any] = {}
        if hasattr(tool, "args_schema") and tool.args_schema is not None:
            try:
                params = tool.args_schema.model_json_schema()
            except Exception:
                pass

        result.append(
            ToolInfo(
                name=tool.name,
                description=tool.description or "",
                parameters=params,
                agent=_TOOL_AGENT_MAP.get(tool.name),
            )
        )
    return result


# ---------------------------------------------------------------------------
# POST /tools/execute — direct tool execution
# ---------------------------------------------------------------------------


@router.post("/tools/execute", response_model=ToolExecuteResponse)
@limiter.limit(settings.rate_limit_embedding)
async def execute_tool(
    request: Request,
    body: ToolExecuteRequest,
) -> ToolExecuteResponse:
    """Execute a tool directly by name with the provided arguments.

    This bypasses agent routing and directly invokes the tool function.
    Useful for debugging, testing, and programmatic tool access.
    """
    from app.api.middleware.error_handler import InputValidationError, NotFoundError

    tool = _TOOL_LOOKUP.get(body.tool_name)
    if tool is None:
        raise NotFoundError("Tool", body.tool_name)

    start_time = time.perf_counter()

    try:
        output = await tool.ainvoke(body.arguments)
    except Exception as exc:
        logger.error(
            "tool_execution_failed",
            tool=body.tool_name,
            error=str(exc),
        )
        raise InputValidationError(f"Tool execution failed: {exc}")

    elapsed_ms = (time.perf_counter() - start_time) * 1000

    logger.info(
        "tool_executed",
        tool=body.tool_name,
        duration_ms=round(elapsed_ms, 2),
    )

    return ToolExecuteResponse(
        tool_name=body.tool_name,
        output=output,
        duration_ms=round(elapsed_ms, 2),
    )


# ---------------------------------------------------------------------------
# GET /health — service health check
# ---------------------------------------------------------------------------


@router.get("/health/ready", response_model=HealthResponse)
async def required_readiness_check() -> HealthResponse:
    """Check only bounded services required before a meeting can start.

    Optional Ollama and Chroma probes intentionally belong only to ``/health``;
    they must not delay the launcher's required ``meeting_ready`` gate.
    """

    async def check_asr() -> ServiceHealth:
        start = time.perf_counter()
        try:
            from app.services.transcription import check_local_asr_readiness

            healthy, message = await check_local_asr_readiness(
                timeout_seconds=REQUIRED_READINESS_TIMEOUT_SECONDS
            )
        except Exception as exc:
            healthy, message = False, str(exc)
        return ServiceHealth(
            name="local_asr",
            healthy=healthy,
            message=message,
            latency_ms=round((time.perf_counter() - start) * 1000, 2),
            required_for_meeting=True,
        )

    async def check_database() -> ServiceHealth:
        start = time.perf_counter()

        async def probe() -> None:
            from app.services.database import get_app_engine

            engine = get_app_engine()
            async with engine.connect() as conn:
                await conn.execute(__import__("sqlalchemy").text("SELECT 1"))

        try:
            await asyncio.wait_for(probe(), timeout=REQUIRED_READINESS_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            return ServiceHealth(
                name="app_database",
                healthy=False,
                message="Required database readiness check timed out",
                latency_ms=round((time.perf_counter() - start) * 1000, 2),
                required_for_meeting=True,
            )
        except Exception as exc:
            return ServiceHealth(
                name="app_database",
                healthy=False,
                message=str(exc),
                latency_ms=round((time.perf_counter() - start) * 1000, 2),
                required_for_meeting=True,
            )
        return ServiceHealth(
            name="app_database",
            healthy=True,
            message="OK",
            latency_ms=round((time.perf_counter() - start) * 1000, 2),
            required_for_meeting=True,
        )

    try:
        services = list(
            await asyncio.wait_for(
                asyncio.gather(check_asr(), check_database()),
                timeout=REQUIRED_READINESS_TIMEOUT_SECONDS,
            )
        )
    except asyncio.TimeoutError:
        services = [
            ServiceHealth(
                name=name,
                healthy=False,
                message="Required readiness check timed out",
                required_for_meeting=True,
            )
            for name in ("local_asr", "app_database")
        ]

    meeting_ready = all(service.healthy for service in services)
    if meeting_ready:
        status = "healthy"
    elif any(service.healthy for service in services):
        status = "degraded"
    else:
        status = "unhealthy"
    return HealthResponse(status=status, services=services, meeting_ready=meeting_ready)


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Check meeting-required and optional answer dependencies."""
    services: list[ServiceHealth] = []

    # Local ASR is required before a meeting can capture authoritative audio.
    try:
        start = time.perf_counter()
        from app.services.transcription import check_local_asr_readiness

        healthy, message = await check_local_asr_readiness()
        services.append(
            ServiceHealth(
                name="local_asr",
                healthy=healthy,
                message=message,
                latency_ms=round((time.perf_counter() - start) * 1000, 2),
                required_for_meeting=True,
            )
        )
    except Exception as exc:
        services.append(
            ServiceHealth(
                name="local_asr",
                healthy=False,
                message=str(exc),
                required_for_meeting=True,
            )
        )

    # Ollama is optional for capture; it only improves private answer suggestions.
    try:
        start = time.perf_counter()
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{settings.ollama_base_url}/api/tags")
            latency = (time.perf_counter() - start) * 1000
            if resp.status_code == 200:
                data = resp.json()
                model_count = len(data.get("models", []))
                services.append(
                    ServiceHealth(
                        name="ollama",
                        healthy=True,
                        message=f"OK — {model_count} models available",
                        latency_ms=round(latency, 2),
                        optional_for_answers=True,
                    )
                )
            else:
                services.append(
                    ServiceHealth(
                        name="ollama",
                        healthy=False,
                        message=f"Unexpected status: {resp.status_code}",
                        latency_ms=round(latency, 2),
                        optional_for_answers=True,
                    )
                )
    except httpx.ConnectError:
        services.append(
            ServiceHealth(
                name="ollama",
                healthy=False,
                message="Ollama is not running",
                optional_for_answers=True,
            )
        )
    except httpx.TimeoutException:
        services.append(
            ServiceHealth(
                name="ollama",
                healthy=False,
                message="Health check timed out",
                optional_for_answers=True,
            )
        )

    # Optional specialists are surfaced separately from enabled profiles.
    # Finnhub reports configuration only; no rate-limited market request is made here.
    services.append(
        ServiceHealth(
            name="finnhub_market_data",
            healthy=bool(settings.finnhub_api_key),
            message=(
                "API key configured"
                if settings.finnhub_api_key
                else "FINNHUB_API_KEY is not configured"
            ),
            optional_for_answers=True,
        )
    )
    try:
        start = time.perf_counter()
        async with httpx.AsyncClient(timeout=2.5) as client:
            response = await client.get(f"{settings.comfyui_url.rstrip('/')}/system_stats")
        healthy = response.status_code == 200
        services.append(
            ServiceHealth(
                name="comfyui",
                healthy=healthy,
                message="ComfyUI is reachable" if healthy else f"Unexpected status: {response.status_code}",
                latency_ms=round((time.perf_counter() - start) * 1000, 2),
                optional_for_answers=True,
            )
        )
    except httpx.HTTPError as exc:
        services.append(
            ServiceHealth(
                name="comfyui",
                healthy=False,
                message=str(exc),
                optional_for_answers=True,
            )
        )

    # Check Qdrant
    try:
        start = time.perf_counter()
        from app.services.hybrid_vector_store import hybrid_vector_store_service as vector_store_service

        collections = await vector_store_service.list_collections()
        latency = (time.perf_counter() - start) * 1000
        services.append(
            ServiceHealth(
                name="qdrant",
                healthy=True,
                message=f"OK — {len(collections)} collections",
                latency_ms=round(latency, 2),
                optional_for_answers=True,
            )
        )
    except Exception as exc:
        services.append(
            ServiceHealth(
                name="qdrant",
                healthy=False,
                message=str(exc),
                optional_for_answers=True,
            )
        )

    # Check Application Database
    try:
        start = time.perf_counter()
        from app.services.database import get_app_engine

        engine = get_app_engine()
        async with engine.connect() as conn:
            await conn.execute(__import__("sqlalchemy").text("SELECT 1"))
        latency = (time.perf_counter() - start) * 1000
        services.append(
            ServiceHealth(
                name="app_database",
                healthy=True,
                message="OK",
                latency_ms=round(latency, 2),
                required_for_meeting=True,
            )
        )
    except Exception as exc:
        services.append(
            ServiceHealth(
                name="app_database",
                healthy=False,
                message=str(exc),
                required_for_meeting=True,
            )
        )

    # Determine overall status
    all_healthy = all(s.healthy for s in services)
    any_healthy = any(s.healthy for s in services)

    if all_healthy:
        status = "healthy"
    elif any_healthy:
        status = "degraded"
    else:
        status = "unhealthy"

    meeting_ready = all(
        service.healthy
        for service in services
        if service.required_for_meeting
    )
    return HealthResponse(status=status, services=services, meeting_ready=meeting_ready)

"""Run one prompt-backed specialist against an uploaded application asset."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select

from app.api.middleware.error_handler import NotFoundError
from app.api.middleware.rate_limiting import limiter
from app.config import settings
from app.dependencies import get_db
from app.models.db_models import Document
from app.models.profile_schemas import AgentResult, TaskRequest

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


@router.post("/tasks", response_model=AgentResult)
@limiter.limit(settings.rate_limit_llm)
async def run_task(
    body: TaskRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> AgentResult:
    """Execute a bounded agent task; uploaded assets are resolved by database ID."""
    document = None
    if body.asset_id:
        result = await db.execute(select(Document).where(Document.id == body.asset_id))
        document = result.scalar_one_or_none()
        if document is None:
            raise NotFoundError("Document", body.asset_id)
    runner = getattr(request.app.state, "task_runner", None)
    if runner is None:
        raise RuntimeError("Task services are not initialized.")
    return await runner.run(body, request_id=str(uuid.uuid4()), document=document)

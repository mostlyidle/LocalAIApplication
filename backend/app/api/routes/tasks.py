"""Run one prompt-backed specialist against an uploaded application asset."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select

from app.api.middleware.error_handler import NotFoundError
from app.api.middleware.rate_limiting import limiter
from app.config import settings
from app.dependencies import get_authenticated_session, get_db
from app.models.db_models import Document
from app.models.profile_schemas import AgentResult, TaskRequest
from app.services.auth import AuthenticatedSession  # noqa: TC001

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


@router.post("/tasks", response_model=AgentResult)
@limiter.limit(settings.rate_limit_llm)
async def run_task(
    body: TaskRequest,
    request: Request,
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> AgentResult:
    """Execute a bounded agent task; uploaded assets are resolved by database ID."""
    document = None
    if body.asset_id:
        result = await db.execute(
            select(Document).where(
                Document.id == body.asset_id,
                Document.owner_id == authenticated.account.id,
            )
        )
        document = result.scalar_one_or_none()
        if document is None:
            raise NotFoundError("Document", body.asset_id)
    registry = getattr(request.app.state, "agent_registry", None)
    profile = registry.get(body.agent_name) if registry and body.agent_name else None
    if body.target == "document_redaction" or (
        profile is not None and profile.target == "document_redaction"
    ):
        if document is None:
            raise HTTPException(status_code=422, detail="Attach one PDF or image to redact.")
        from app.models.redaction_schemas import RedactionJobCreate
        from app.services.redaction_detector import DEFAULT_CATEGORIES
        from app.services.redaction_job_worker import queue_redaction_job

        categories = DEFAULT_CATEGORIES
        if body.workflow and "categories" in body.workflow:
            categories = body.workflow["categories"]
        try:
            job_request = RedactionJobCreate(
                document_id=document.id,
                categories=categories,
                instructions=body.prompt,
            )
            job = await queue_redaction_job(
                db,
                document,
                authenticated.account.id,
                job_request,
            )
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        review_url = f"/redaction?job_id={job.id}"
        return AgentResult(
            agent="document_redaction",
            answer=f"Redaction job queued. [Open the review workspace]({review_url}).",
            artifacts={"redaction_job_id": job.id, "review_url": review_url},
        )
    runner = getattr(request.app.state, "task_runner", None)
    if runner is None:
        raise RuntimeError("Task services are not initialized.")
    return await runner.run(
        body,
        request_id=str(uuid.uuid4()),
        document=document,
        owner_id=authenticated.account.id,
    )

"""Account-private CRUD endpoints for planner action items."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, update

from app.api.middleware.error_handler import NotFoundError
from app.dependencies import get_authenticated_session, get_db
from app.models.action_item_schemas import (
    ActionItemCreate,
    ActionItemListResponse,
    ActionItemResponse,
    ActionItemUpdate,
)
from app.models.db_models import ActionItem, Conversation, Document, Meeting
from app.services.auth import AuthenticatedSession  # noqa: TC001

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


async def _validate_source(
    body: ActionItemCreate, owner_id: str, db: AsyncSession
) -> None:
    """Require referenced local source records to belong to the signed-in account."""
    if body.source_id is None:
        return
    models = {"chat": Conversation, "meeting": Meeting, "document": Document}
    model = models.get(body.source_type or "")
    if model is None or await db.scalar(
        select(model.id).where(model.id == body.source_id, model.owner_id == owner_id)
    ) is None:
        raise NotFoundError("Source", body.source_id)


@router.get("/action-items", response_model=ActionItemListResponse)
async def list_action_items(
    status: str | None = Query(default=None, pattern="^(next|in_progress|done)$"),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> ActionItemListResponse:
    """List action items belonging only to the current account."""
    filters = [ActionItem.owner_id == authenticated.account.id]
    if status:
        filters.append(ActionItem.status == status)
    total = await db.scalar(select(func.count(ActionItem.id)).where(*filters)) or 0
    rows = await db.scalars(
        select(ActionItem)
        .where(*filters)
        .order_by(ActionItem.due_date.is_(None), ActionItem.due_date, ActionItem.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return ActionItemListResponse(items=list(rows.all()), total=total)


@router.post("/action-items", response_model=ActionItemResponse, status_code=201)
async def create_action_item(
    body: ActionItemCreate,
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> ActionItem:
    """Create an action item after verifying its optional source ownership."""
    owner_id = authenticated.account.id
    await _validate_source(body, owner_id, db)
    item = ActionItem(owner_id=owner_id, **body.model_dump())
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


@router.patch("/action-items/{item_id}", response_model=ActionItemResponse)
async def update_action_item(
    item_id: str,
    body: ActionItemUpdate,
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> ActionItem:
    """Update an owned item only when its revision is current."""
    values = body.model_dump(exclude={"revision"}, exclude_unset=True)
    if "title" in values:
        values["title"] = values["title"].strip()
    if "description" in values and values["description"] is not None:
        values["description"] = values["description"].strip() or None
    result = await db.execute(
        update(ActionItem)
        .where(
            ActionItem.id == item_id,
            ActionItem.owner_id == authenticated.account.id,
            ActionItem.revision == body.revision,
        )
        .values(**values, revision=ActionItem.revision + 1, updated_at=datetime.now(UTC))
    )
    if result.rowcount != 1:
        await db.rollback()
        existing = await db.scalar(
            select(ActionItem.id).where(
                ActionItem.id == item_id, ActionItem.owner_id == authenticated.account.id
            )
        )
        if existing is None:
            raise NotFoundError("Action item", item_id)
        raise HTTPException(status_code=409, detail="Action item changed; reload before editing.")
    await db.commit()
    return await db.scalar(
        select(ActionItem).where(
            ActionItem.id == item_id, ActionItem.owner_id == authenticated.account.id
        )
    )


@router.delete("/action-items/{item_id}", status_code=204)
async def delete_action_item(
    item_id: str,
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> None:
    """Delete an action item only if it belongs to the current account."""
    item = await db.scalar(
        select(ActionItem).where(
            ActionItem.id == item_id, ActionItem.owner_id == authenticated.account.id
        )
    )
    if item is None:
        raise NotFoundError("Action item", item_id)
    await db.delete(item)
    await db.commit()

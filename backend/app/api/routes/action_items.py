"""Account-private CRUD endpoints for planner action items."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select, update

from app.api.middleware.error_handler import NotFoundError
from app.api.middleware.rate_limiting import limiter
from app.config import settings
from app.dependencies import get_authenticated_session, get_db, get_document_parser
from app.models.action_item_schemas import (
    ActionItemCreate,
    ActionItemListResponse,
    ActionItemProposalResponse,
    ActionItemResponse,
    ActionItemUpdate,
    ProposalSourceRequest,
)
from app.models.db_models import (
    ActionItem,
    Conversation,
    Document,
    GitHubConnection,
    GitHubRepositorySelection,
    Meeting,
    Message,
    TranscriptSegment,
)
from app.models.enums import DocumentFormat
from app.services.auth import AuthenticatedSession  # noqa: TC001
from app.services.document_parser import DocumentParserService  # noqa: TC001
from app.services.github_oauth import github_oauth_client

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


async def _load_owned_source(
    source_type: str,
    source_id: str,
    owner_id: str,
    db: AsyncSession,
    parser: DocumentParserService,
    source_repository_id: str | None = None,
) -> tuple[str, str]:
    """Load bounded, readable source text only after checking its account owner."""
    if source_type == "chat":
        conversation = await db.scalar(
            select(Conversation).where(
                Conversation.id == source_id, Conversation.owner_id == owner_id
            )
        )
        if conversation is None:
            raise NotFoundError("Conversation", source_id)
        rows = await db.scalars(
            select(Message)
            .where(Message.conversation_id == source_id, Message.role.in_(["user", "assistant"]))
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(40)
        )
        messages = list(reversed(rows.all()))
        return conversation.title, "\n".join(message.content for message in messages)

    if source_type == "meeting":
        meeting = await db.scalar(
            select(Meeting).where(Meeting.id == source_id, Meeting.owner_id == owner_id)
        )
        if meeting is None:
            raise NotFoundError("Meeting", source_id)
        if meeting.status == "active":
            raise HTTPException(status_code=409, detail="Stop the meeting before creating suggestions.")
        rows = await db.scalars(
            select(TranscriptSegment)
            .where(TranscriptSegment.meeting_id == source_id)
            .order_by(TranscriptSegment.sequence)
        )
        text = "\n".join(segment.text for segment in rows.all())
        return f"Meeting {meeting.id[:8]}", text

    if source_type == "document":
        document = await db.scalar(
            select(Document).where(Document.id == source_id, Document.owner_id == owner_id)
        )
        if document is None:
            raise NotFoundError("Document", source_id)
        from pathlib import Path

        path = Path(document.storage_path)
        if not path.is_file():
            raise NotFoundError("Document file", source_id)
        parsed = await parser.parse(path, DocumentFormat(document.format))
        return document.filename, parsed.text

    if source_type == "github":
        if not source_repository_id or not source_id.isdecimal():
            raise HTTPException(status_code=422, detail="A GitHub issue source needs its selected repository.")
        repository = await db.scalar(
            select(GitHubRepositorySelection).where(
                GitHubRepositorySelection.owner_id == owner_id,
                GitHubRepositorySelection.repository_id == source_repository_id,
            )
        )
        if repository is None:
            raise NotFoundError("Selected GitHub repository", source_repository_id)
        connection = await db.scalar(
            select(GitHubConnection).where(GitHubConnection.owner_id == owner_id)
        )
        if connection is None:
            raise HTTPException(status_code=409, detail="Connect a GitHub account first.")
        token = await github_oauth_client.access_token(connection, db)
        parts = repository.full_name.split("/")
        if len(parts) != 2 or any(not part for part in parts):
            raise HTTPException(status_code=409, detail="The selected repository metadata is invalid.")
        from urllib.parse import quote

        payload = await github_oauth_client.api_get_json(
            f"/repos/{quote(parts[0], safe='')}/{quote(parts[1], safe='')}/issues/{source_id}",
            token,
        )
        if not isinstance(payload, dict) or payload.get("number") != int(source_id):
            raise NotFoundError("GitHub issue", source_id)
        title, body = payload.get("title"), payload.get("body")
        if not isinstance(title, str):
            raise HTTPException(status_code=502, detail="GitHub returned an invalid issue.")
        return title, f"Issue #{source_id}: {title}\n{body if isinstance(body, str) else ''}"

    raise HTTPException(status_code=422, detail="Unsupported planner source type.")


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
    parser: DocumentParserService = Depends(get_document_parser),  # noqa: B008
) -> ActionItem:
    """Create an action item after verifying its optional source ownership."""
    owner_id = authenticated.account.id
    if body.source_id:
        _, source_text = await _load_owned_source(
            body.source_type or "",
            body.source_id,
            owner_id,
            db,
            parser,
            body.source_repository_id,
        )
        if not body.source_quote or body.source_quote not in source_text[:24_000]:
            raise HTTPException(
                status_code=422,
                detail="A linked action item requires an exact quote from its source.",
            )
    item = ActionItem(owner_id=owner_id, **body.model_dump())
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


@router.post("/action-items/proposals", response_model=ActionItemProposalResponse)
@limiter.limit(settings.rate_limit_llm)
async def propose_action_items(
    body: ProposalSourceRequest,
    request: Request,
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
    parser: DocumentParserService = Depends(get_document_parser),  # noqa: B008
) -> ActionItemProposalResponse:
    """Draft suggestions from a source owned by the current account; save nothing."""
    source_title, source_text = await _load_owned_source(
        body.source_type, body.source_id, authenticated.account.id, db, parser
    )
    bounded_text = source_text[:24_000]
    if not bounded_text.strip():
        raise HTTPException(status_code=422, detail="This source has no readable text.")
    from app.services.planner_agent import draft_action_items

    suggestions = await draft_action_items(bounded_text)
    return ActionItemProposalResponse(
        source_type=body.source_type,
        source_id=body.source_id,
        source_title=source_title,
        suggestions=suggestions,
    )


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

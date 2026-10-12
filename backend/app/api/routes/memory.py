"""Account-owned explicit memory records and controls."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: TC002

from app.api.middleware.error_handler import NotFoundError
from app.dependencies import get_authenticated_session, get_db
from app.models.db_models import (
    Account,
    Conversation,
    ConversationRecallSummary,
    Memory,
    MemoryOutboxJob,
    Message,
)
from app.models.memory_schemas import (
    ConversationMemorySettingsUpdate,
    MemoryCreate,
    MemoryDeleteAllResponse,
    MemoryListResponse,
    MemoryResponse,
    MemorySettingsResponse,
    MemorySettingsUpdate,
    MemoryUpdate,
)
from app.services.auth import AuthenticatedSession  # noqa: TC001

router = APIRouter()


@router.patch("/memory/conversations/{conversation_id}/settings")
async def update_conversation_memory_settings(
    conversation_id: str,
    body: ConversationMemorySettingsUpdate,
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> dict[str, bool]:
    """Set recall eligibility only for a conversation owned by this account."""
    conversation = await db.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.owner_id == authenticated.account.id,
        )
    )
    if conversation is None:
        raise NotFoundError("Conversation", conversation_id)
    conversation.exclude_from_memory = body.exclude_from_memory
    await db.commit()
    return {"exclude_from_memory": conversation.exclude_from_memory}


@router.get("/memory", response_model=MemoryListResponse)
async def list_memories(
    q: str | None = Query(default=None, max_length=256),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> MemoryListResponse:
    """List only active memories owned by the signed-in account."""
    filters = [
        Memory.owner_id == authenticated.account.id,
        Memory.deleted_at.is_(None),
        Memory.approved.is_(True),
    ]
    if q:
        filters.append(Memory.content.ilike(f"%{q.strip()}%"))
    total = await db.scalar(select(func.count(Memory.id)).where(*filters)) or 0
    records = await db.scalars(
        select(Memory)
        .where(*filters)
        .order_by(Memory.updated_at.desc(), Memory.id)
        .limit(limit)
        .offset(offset)
    )
    return MemoryListResponse(memories=list(records.all()), total=total, limit=limit, offset=offset)


@router.post("/memory", response_model=MemoryResponse, status_code=201)
async def create_memory(
    body: MemoryCreate,
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> Memory:
    """Store a memory only after the user explicitly submits it."""
    owner_id = authenticated.account.id
    conversation_id = body.source_conversation_id
    source_message_id = body.source_message_id
    if body.source_message_id:
        source = await db.scalar(
            select(Message)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(
                Message.id == body.source_message_id,
                Conversation.owner_id == owner_id,
            )
        )
        if source is None:
            raise NotFoundError("Message", body.source_message_id)
        if conversation_id is not None and conversation_id != source.conversation_id:
            raise NotFoundError("Message", body.source_message_id)
        conversation_id = source.conversation_id
    elif body.source_client_turn_id:
        source_filters = [
            Message.client_turn_id == body.source_client_turn_id,
            Message.role == "user",
            Conversation.owner_id == owner_id,
        ]
        if conversation_id is not None:
            source_filters.append(Message.conversation_id == conversation_id)
        source = await db.scalar(
            select(Message)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(*source_filters)
        )
        if source is None:
            raise NotFoundError("Message", body.source_client_turn_id)
        conversation_id = source.conversation_id
        source_message_id = source.id
    elif conversation_id is not None:
        owned = await db.scalar(
            select(Conversation.id).where(
                Conversation.id == conversation_id,
                Conversation.owner_id == owner_id,
            )
        )
        if owned is None:
            raise NotFoundError("Conversation", conversation_id)

    memory = Memory(
        owner_id=owner_id,
        kind=body.kind,
        content=body.content.strip(),
        project_scope=body.project_scope.strip() if body.project_scope else None,
        source_conversation_id=conversation_id,
        source_message_id=source_message_id,
        origin_agent=body.origin_agent,
        approved=True,
    )
    db.add(memory)
    await db.commit()
    await db.refresh(memory)
    return memory


@router.get("/memory/settings", response_model=MemorySettingsResponse)
async def get_memory_settings(
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> Account:
    """Return the signed-in account's independent memory controls."""
    account = await db.scalar(select(Account).where(Account.id == authenticated.account.id))
    return account


@router.patch("/memory/settings", response_model=MemorySettingsResponse)
async def update_memory_settings(
    body: MemorySettingsUpdate,
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> Account:
    """Change memory controls for the signed-in account only."""
    account = await db.scalar(select(Account).where(Account.id == authenticated.account.id))
    if body.memory_enabled is not None:
        account.memory_enabled = body.memory_enabled
    if body.past_chat_recall_enabled is not None:
        account.past_chat_recall_enabled = body.past_chat_recall_enabled
    await db.commit()
    await db.refresh(account)
    return account


@router.patch("/memory/{memory_id}", response_model=MemoryResponse)
async def update_memory(
    memory_id: str,
    body: MemoryUpdate,
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> Memory:
    """Correct an owned memory only when its revision still matches."""
    values = body.model_dump(exclude={"revision"}, exclude_unset=True)
    if "content" in values:
        values["content"] = values["content"].strip()
    if "project_scope" in values and values["project_scope"] is not None:
        values["project_scope"] = values["project_scope"].strip() or None
    values.update(revision=Memory.revision + 1, updated_at=datetime.now(UTC))
    result = await db.execute(
        update(Memory)
        .where(
            Memory.id == memory_id,
            Memory.owner_id == authenticated.account.id,
            Memory.deleted_at.is_(None),
            Memory.revision == body.revision,
        )
        .values(values)
    )
    if result.rowcount != 1:
        await db.rollback()
        existing = await db.scalar(
            select(Memory.id).where(
                Memory.id == memory_id,
                Memory.owner_id == authenticated.account.id,
                Memory.deleted_at.is_(None),
            )
        )
        if existing is None:
            raise NotFoundError("Memory", memory_id)
        raise HTTPException(status_code=409, detail="Memory changed; reload before editing.")
    await db.commit()
    memory = await db.scalar(
        select(Memory).where(
            Memory.id == memory_id,
            Memory.owner_id == authenticated.account.id,
        )
    )
    return memory


@router.delete("/memory/{memory_id}", status_code=204)
async def delete_memory(
    memory_id: str,
    revision: int = Query(ge=1),
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> Response:
    """Immediately exclude a memory from recall using a soft-delete marker."""
    result = await db.execute(
        update(Memory)
        .where(
            Memory.id == memory_id,
            Memory.owner_id == authenticated.account.id,
            Memory.deleted_at.is_(None),
            Memory.revision == revision,
        )
        .values(
            deleted_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            revision=Memory.revision + 1,
        )
    )
    if result.rowcount != 1:
        await db.rollback()
        existing = await db.scalar(
            select(Memory.id).where(
                Memory.id == memory_id,
                Memory.owner_id == authenticated.account.id,
                Memory.deleted_at.is_(None),
            )
        )
        if existing is None:
            raise NotFoundError("Memory", memory_id)
        raise HTTPException(status_code=409, detail="Memory changed; reload before deleting.")
    await db.commit()
    return Response(status_code=204)


@router.delete("/memory", response_model=MemoryDeleteAllResponse)
async def delete_all_memories(
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> MemoryDeleteAllResponse:
    """Invalidate all current memories and turn off past-chat recall."""
    now = datetime.now(UTC)
    account = await db.scalar(select(Account).where(Account.id == authenticated.account.id))
    result = await db.execute(
        update(Memory)
        .where(Memory.owner_id == account.id, Memory.deleted_at.is_(None))
        .values(deleted_at=now, updated_at=now, revision=Memory.revision + 1)
    )
    await db.execute(
        delete(ConversationRecallSummary).where(ConversationRecallSummary.owner_id == account.id)
    )
    await db.execute(delete(MemoryOutboxJob).where(MemoryOutboxJob.owner_id == account.id))
    account.memory_epoch += 1
    account.past_chat_recall_enabled = False
    await db.commit()
    return MemoryDeleteAllResponse(
        deleted_count=result.rowcount or 0,
        memory_epoch=account.memory_epoch,
        past_chat_recall_enabled=account.past_chat_recall_enabled,
    )

"""Load a small, account-scoped set of approved memories for one inference."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import select

from app.models.db_models import Account, Memory

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

MAX_MEMORY_CONTEXT_CHARS = 4_000
MAX_MEMORY_ITEMS = 20
MAX_MEMORY_ITEM_CHARS = 800
MAX_MEMORY_SOURCES = 4
logger = structlog.get_logger(__name__)


def memory_sources_from_context(context: str | None) -> list[dict[str, str]]:
    """Return conversation labels and IDs for recalled chat entries only."""
    if not context:
        return []
    try:
        items = json.loads(context)
    except (TypeError, ValueError):
        return []
    if not isinstance(items, list):
        return []

    sources: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict) or item.get("type") != "past_conversation":
            continue
        conversation_id = item.get("conversation_id")
        if not isinstance(conversation_id, str) or not conversation_id or conversation_id in seen:
            continue
        title = item.get("title")
        sources.append(
            {
                "conversation_id": conversation_id,
                "title": title[:160] if isinstance(title, str) and title else "Past conversation",
            }
        )
        seen.add(conversation_id)
        if len(sources) == MAX_MEMORY_SOURCES:
            break
    return sources


async def load_account_memory_context(
    owner_id: str | None,
    *,
    query: str | None = None,
    exclude_conversation_id: str | None = None,
    db: AsyncSession | None = None,
) -> str:
    """Return bounded approved memory data only when that account opted in."""
    if not owner_id:
        return ""
    if db is not None:
        return await _load_context(
            db, owner_id, query=query, exclude_conversation_id=exclude_conversation_id
        )

    from app.services.database import get_app_session_factory

    try:
        async with get_app_session_factory()() as session:
            return await _load_context(
                session,
                owner_id,
                query=query,
                exclude_conversation_id=exclude_conversation_id,
            )
    except Exception:
        # Memory is supplementary; a database hiccup must not prevent chat.
        return ""


async def _load_context(
    db: AsyncSession,
    owner_id: str,
    *,
    query: str | None = None,
    exclude_conversation_id: str | None = None,
) -> str:
    account = await db.scalar(select(Account).where(Account.id == owner_id))
    if account is None:
        return ""

    now = datetime.now(UTC)
    items = []
    if account.memory_enabled:
        rows = await db.scalars(
            select(Memory)
            .where(
                Memory.owner_id == owner_id,
                Memory.approved.is_(True),
                Memory.deleted_at.is_(None),
                (Memory.expires_at.is_(None) | (Memory.expires_at > now)),
            )
            .order_by(Memory.updated_at.desc(), Memory.id)
            .limit(MAX_MEMORY_ITEMS)
        )
        items.extend(
            {
                "type": memory.kind,
                "project": memory.project_scope,
                "content": memory.content[:MAX_MEMORY_ITEM_CHARS],
            }
            for memory in rows
        )
    if account.past_chat_recall_enabled and query and query.strip():
        try:
            from app.services.memory_vector_index import memory_vector_index

            items.extend(
                await memory_vector_index.search_summaries(
                    db,
                    owner_id=owner_id,
                    memory_epoch=account.memory_epoch,
                    query=query[:4_000],
                    exclude_conversation_id=exclude_conversation_id,
                    limit=4,
                )
            )
        except Exception as exc:
            logger.warning("past_chat_recall_unavailable", error_type=type(exc).__name__)
    if not items:
        return ""
    bounded: list[dict[str, str | None]] = []
    for item in items:
        candidate = [*bounded, item]
        encoded = json.dumps(candidate, ensure_ascii=False, separators=(",", ":"))
        if len(encoded) > MAX_MEMORY_CONTEXT_CHARS:
            break
        bounded = candidate
    return json.dumps(bounded, ensure_ascii=False, separators=(",", ":"))

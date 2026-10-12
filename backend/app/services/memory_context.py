"""Load a small, account-scoped set of approved memories for one inference."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select

from app.models.db_models import Account, Memory

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

MAX_MEMORY_CONTEXT_CHARS = 4_000
MAX_MEMORY_ITEMS = 20
MAX_MEMORY_ITEM_CHARS = 800


async def load_account_memory_context(
    owner_id: str | None,
    *,
    db: AsyncSession | None = None,
) -> str:
    """Return bounded approved memory data only when that account opted in."""
    if not owner_id:
        return ""
    if db is not None:
        return await _load_context(db, owner_id)

    from app.services.database import get_app_session_factory

    try:
        async with get_app_session_factory()() as session:
            return await _load_context(session, owner_id)
    except Exception:
        # Memory is supplementary; a database hiccup must not prevent chat.
        return ""


async def _load_context(db: AsyncSession, owner_id: str) -> str:
    account = await db.scalar(select(Account).where(Account.id == owner_id))
    if account is None or not account.memory_enabled:
        return ""

    now = datetime.now(UTC)
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
    items = [
        {
            "type": memory.kind,
            "project": memory.project_scope,
            "content": memory.content[:MAX_MEMORY_ITEM_CHARS],
        }
        for memory in rows
    ]
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

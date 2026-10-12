"""Account-level ownership checks for named SQL connections."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from sqlalchemy.exc import IntegrityError

from app.models.db_models import SqlConnection

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

SqlConnectionAccess = Literal["owned", "shared", "missing", "unassigned", "foreign", "inactive"]


async def sql_connection_access(
    db: AsyncSession,
    *,
    name: str,
    owner_id: str,
    reserve: bool = False,
    require_active: bool = True,
) -> SqlConnectionAccess:
    """Allow the configured default, and isolate API-registered names by owner."""
    if name == "default":
        return "shared"

    from app.services.database import _sql_engines

    registry = await db.get(SqlConnection, name)
    if registry is not None:
        if registry.owner_id != owner_id:
            return "foreign"
        if require_active and name not in _sql_engines:
            return "inactive"
        return "owned"
    if name in _sql_engines:
        return "unassigned"
    if not reserve:
        return "missing"

    db.add(SqlConnection(name=name, owner_id=owner_id))
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        registry = await db.get(SqlConnection, name)
        if registry is not None and registry.owner_id == owner_id:
            return "owned" if (not require_active or name in _sql_engines) else "inactive"
        if registry is not None:
            return "foreign"
        raise
    return "owned"

"""Account-level access checks for application-managed RAG collections."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from sqlalchemy.exc import IntegrityError

from app.models.db_models import RagCollection
from app.services.rag_store import ACCOUNT_MEMORY_COLLECTION, CollectionCapabilities

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.services.vector_store import VectorStoreService

CollectionAccess = Literal["owned", "shared", "missing", "unassigned", "foreign"]


async def collection_access(
    db: AsyncSession,
    vector_store: VectorStoreService,
    *,
    name: str,
    owner_id: str,
    reserve: bool = False,
) -> CollectionAccess:
    """Resolve access without assigning existing collections to a new account."""
    if name == ACCOUNT_MEMORY_COLLECTION:
        return "unassigned"
    registry = await db.get(RagCollection, name)
    if registry is not None:
        return "owned" if registry.owner_id == owner_id else "foreign"

    capabilities = None
    inspect_collection = getattr(vector_store, "collection_capabilities", None)
    if inspect_collection is not None:
        result = await inspect_collection(name)
        if isinstance(result, CollectionCapabilities):
            capabilities = result
    if capabilities is not None:
        return "shared" if capabilities.loader_owned else "unassigned"

    if not reserve:
        return "missing"

    db.add(RagCollection(name=name, owner_id=owner_id))
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        registry = await db.get(RagCollection, name)
        if registry is not None and registry.owner_id == owner_id:
            return "owned"
        if registry is not None:
            return "foreign"
        raise
    return "owned"

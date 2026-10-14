"""Private Qdrant index for account-owned past-chat summaries."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog
from qdrant_client import AsyncQdrantClient, models
from qdrant_client.http.exceptions import (
    ApiException,
    ResponseHandlingException,
    UnexpectedResponse,
)
from sqlalchemy import select

from app.config import settings
from app.models.db_models import Account, Conversation, ConversationRecallSummary
from app.services.embeddings import embedding_service
from app.services.rag_store import ACCOUNT_MEMORY_COLLECTION

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)
MEMORY_COLLECTION = ACCOUNT_MEMORY_COLLECTION
MEMORY_SEARCH_LIMIT = 20


class MemoryVectorIndex:
    """Store vectors without transcript text and validate every hit against SQL."""

    def __init__(self, client: AsyncQdrantClient | None = None) -> None:
        self._client = client or AsyncQdrantClient(
            url=settings.qdrant_url,
            cloud_inference=False,
            check_compatibility=False,
        )

    async def close(self) -> None:
        await self._client.close()

    async def upsert_summary(self, db: AsyncSession, summary: ConversationRecallSummary) -> bool:
        identity = await embedding_service.get_identity()
        vector = (await embedding_service.embed_texts([summary.content]))[0]
        if len(vector) != settings.ollama_embedding_dimension:
            raise ValueError("Memory summary embedding has an unexpected dimension.")
        if await embedding_service.get_identity() != identity:
            raise ValueError("Embedding weights changed while indexing a memory summary.")
        account = await db.get(Account, summary.owner_id, populate_existing=True)
        conversation = await db.get(Conversation, summary.conversation_id, populate_existing=True)
        current = await db.get(ConversationRecallSummary, summary.id, populate_existing=True)
        if (
            account is None
            or conversation is None
            or current is None
            or not account.is_enabled
            or not account.past_chat_recall_enabled
            or account.memory_epoch != summary.memory_epoch
            or conversation.owner_id != summary.owner_id
            or conversation.exclude_from_memory
            or current.revision != summary.revision
            or current.memory_epoch != summary.memory_epoch
        ):
            return False
        await self._ensure_collection(identity)
        await self._client.upsert(
            collection_name=MEMORY_COLLECTION,
            wait=True,
            points=[
                models.PointStruct(
                    id=summary.id,
                    vector=vector,
                    payload={
                        "owner_id": summary.owner_id,
                        "conversation_id": summary.conversation_id,
                        "summary_id": summary.id,
                        "revision": summary.revision,
                        "memory_epoch": summary.memory_epoch,
                    },
                )
            ],
        )
        account = await db.get(Account, summary.owner_id, populate_existing=True)
        conversation = await db.get(Conversation, summary.conversation_id, populate_existing=True)
        current = await db.get(ConversationRecallSummary, summary.id, populate_existing=True)
        if (
            account is None
            or conversation is None
            or current is None
            or not account.is_enabled
            or not account.past_chat_recall_enabled
            or account.memory_epoch != summary.memory_epoch
            or conversation.owner_id != summary.owner_id
            or conversation.exclude_from_memory
            or current.revision != summary.revision
        ):
            await self.delete_conversation(summary.owner_id, summary.conversation_id)
            return False
        return True

    async def search_summaries(
        self,
        db: AsyncSession,
        *,
        owner_id: str,
        memory_epoch: int,
        query: str,
        exclude_conversation_id: str | None = None,
        limit: int = 4,
    ) -> list[dict[str, str]]:
        """Search account-filtered vectors, then authorize each hit using SQL."""
        identity = await embedding_service.get_identity()
        vector = await embedding_service.embed_text(query)
        if len(vector) != settings.ollama_embedding_dimension:
            raise ValueError("Memory query embedding has an unexpected dimension.")
        if await embedding_service.get_identity() != identity:
            raise ValueError("Embedding weights changed while searching account memory.")
        if not await self._collection_matches(identity):
            return []

        response = await self._client.query_points(
            collection_name=MEMORY_COLLECTION,
            query=vector,
            query_filter=models.Filter(
                must=[
                    models.FieldCondition(key="owner_id", match=models.MatchValue(value=owner_id)),
                    models.FieldCondition(
                        key="memory_epoch", match=models.MatchValue(value=memory_epoch)
                    ),
                ]
            ),
            limit=max(limit, MEMORY_SEARCH_LIMIT),
            with_payload=True,
            with_vectors=False,
        )
        hits = [point for point in response.points if isinstance(point.payload, dict)]
        ids = [str(point.payload.get("summary_id", "")) for point in hits]
        if not ids:
            return []

        rows = (
            await db.execute(
                select(ConversationRecallSummary, Conversation)
                .join(Conversation, Conversation.id == ConversationRecallSummary.conversation_id)
                .join(Account, Account.id == ConversationRecallSummary.owner_id)
                .where(
                    ConversationRecallSummary.id.in_(ids),
                    ConversationRecallSummary.owner_id == owner_id,
                    ConversationRecallSummary.memory_epoch == memory_epoch,
                    Conversation.owner_id == owner_id,
                    Conversation.exclude_from_memory.is_(False),
                    Account.is_enabled.is_(True),
                    Account.past_chat_recall_enabled.is_(True),
                    Account.memory_epoch == memory_epoch,
                )
                .where(
                    Conversation.id != exclude_conversation_id if exclude_conversation_id else True
                )
            )
        ).all()
        by_id = {summary.id: (summary, conversation) for summary, conversation in rows}
        results: list[dict[str, str]] = []
        for point in hits:
            if point.score < 0.35:
                continue
            payload = point.payload or {}
            summary_id = str(payload.get("summary_id", ""))
            matched = by_id.get(summary_id)
            if matched is None:
                continue
            summary, conversation = matched
            if (
                payload.get("owner_id") != owner_id
                or payload.get("conversation_id") != conversation.id
                or payload.get("revision") != summary.revision
                or payload.get("memory_epoch") != memory_epoch
            ):
                continue
            results.append(
                {
                    "type": "past_conversation",
                    "conversation_id": conversation.id,
                    "title": conversation.title[:160],
                    "content": summary.content[:4_000],
                }
            )
            if len(results) >= limit:
                break
        return results

    async def delete_owner(self, owner_id: str) -> None:
        if not await self._client.collection_exists(MEMORY_COLLECTION):
            return
        await self._client.delete(
            collection_name=MEMORY_COLLECTION,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="owner_id", match=models.MatchValue(value=owner_id)
                        )
                    ]
                )
            ),
            wait=True,
        )

    async def delete_conversation(self, owner_id: str, conversation_id: str) -> None:
        if not await self._client.collection_exists(MEMORY_COLLECTION):
            return
        await self._client.delete(
            collection_name=MEMORY_COLLECTION,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="owner_id", match=models.MatchValue(value=owner_id)
                        ),
                        models.FieldCondition(
                            key="conversation_id", match=models.MatchValue(value=conversation_id)
                        ),
                    ]
                )
            ),
            wait=True,
        )

    async def _ensure_collection(self, identity: dict[str, str]) -> None:
        if await self._collection_matches(identity):
            return
        metadata = self._metadata(identity)
        try:
            await self._client.create_collection(
                collection_name=MEMORY_COLLECTION,
                vectors_config=models.VectorParams(
                    size=settings.ollama_embedding_dimension,
                    distance=models.Distance.COSINE,
                ),
                metadata=metadata,
            )
        except (ValueError, UnexpectedResponse) as exc:
            if isinstance(exc, UnexpectedResponse) and exc.status_code != 409:
                raise
            if not await self._collection_matches(identity):
                raise ValueError(
                    "The reserved account memory collection has incompatible identity."
                ) from exc
        except (ApiException, ResponseHandlingException) as exc:
            logger.warning("memory_vector_collection_unavailable", error_type=type(exc).__name__)
            raise

    async def _collection_matches(self, identity: dict[str, str]) -> bool:
        if not await self._client.collection_exists(MEMORY_COLLECTION):
            return False
        info = await self._client.get_collection(MEMORY_COLLECTION)
        vectors = info.config.params.vectors
        metadata = info.config.metadata or {}
        return (
            not isinstance(vectors, dict)
            and vectors.size == settings.ollama_embedding_dimension
            and metadata == self._metadata(identity)
        )

    @staticmethod
    def _metadata(identity: dict[str, str]) -> dict[str, Any]:
        return {
            "memory_schema_version": 1,
            "embedding_model": identity["embedding_model"],
            "embedding_digest": identity["embedding_digest"],
            "embedding_profile": identity["embedding_profile"],
        }


memory_vector_index = MemoryVectorIndex()

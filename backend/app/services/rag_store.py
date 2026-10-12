from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, TypeVar

from qdrant_client import AsyncQdrantClient, models
from qdrant_client.http.exceptions import (
    ApiException,
    ResponseHandlingException,
    UnexpectedResponse,
)

from app.services.bm25 import BM25_DEFAULTS, BM25_MODEL_NAME, Bm25Encoder, FastEmbedBm25

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence

RAG_SCHEMA_VERSION = 2
DENSE_VECTOR_NAME = "dense"
BM25_VECTOR_NAME = "bm25"
COLLECTION_OWNER_KEY = "rag_collection_owner"
LOADER_COLLECTION_OWNER = "rag-dataloader"
PROVENANCE_STRING_FIELDS = (
    "document_id",
    "source_path",
    "filename",
    "content_sha256",
    "loader_id",
    "embedding_model",
    "embedding_revision",
    "pipeline_fingerprint",
    "section",
    "source",
    "source_chunk_id",
)
PROVENANCE_PAGE_FIELDS = ("page", "page_start", "page_end")

T = TypeVar("T")


class RagStoreError(RuntimeError):
    """Base error for RAG collection operations."""


class RagCollectionConflictError(RagStoreError):
    """The selected collection cannot safely accept the requested schema."""


class RagCollectionSchemaError(RagStoreError):
    """The selected collection is not a supported RAG collection."""


class RagStoreUnavailableError(RagStoreError):
    """Qdrant could not complete a required store operation."""


@dataclass(frozen=True)
class CollectionCapabilities:
    mode: Literal["hybrid", "legacy_dense", "unsupported"]
    language: str | None = None
    bm25_options: dict[str, object] | None = None
    dense_distance: str | None = None
    dense_model: str | None = None
    embedding_revision: str | None = None
    dense_dimension: int | None = None
    loader_owned: bool = False


@dataclass
class AssetUpsertLock:
    lock: asyncio.Lock
    users: int = 0


@dataclass(frozen=True)
class RagSearchResult:
    passages: list[dict[str, object]]
    retrieval: dict[str, object]


class RagStore:
    def __init__(
        self,
        url: str,
        *,
        client: AsyncQdrantClient | None = None,
        bm25_encoder: Bm25Encoder | None = None,
    ) -> None:
        self._client = (
            client
            if client is not None
            else AsyncQdrantClient(url=url, cloud_inference=False, check_compatibility=True)
        )
        self._bm25_encoder = bm25_encoder or FastEmbedBm25()
        self._asset_locks: dict[tuple[str, str], AssetUpsertLock] = {}
        self._asset_locks_guard = asyncio.Lock()

    async def close(self) -> None:
        await self._client.close()

    async def create_hybrid_collection(
        self,
        *,
        collection: str,
        dimension: int,
        dense_model: str,
        language: str,
        embedding_revision: str,
    ) -> None:
        """Reserve a new collection; never adopt an existing destination."""
        try:
            created = await self._client.create_collection(
                collection_name=collection,
                vectors_config={
                    DENSE_VECTOR_NAME: models.VectorParams(
                        size=dimension, distance=models.Distance.COSINE
                    )
                },
                sparse_vectors_config={
                    BM25_VECTOR_NAME: models.SparseVectorParams(modifier=models.Modifier.IDF)
                },
                metadata=self._metadata(
                    dense_model=dense_model,
                    embedding_revision=embedding_revision,
                    dimension=dimension,
                    language=language,
                ),
            )
        except UnexpectedResponse as exc:
            if exc.status_code == 409:
                raise RagCollectionConflictError(
                    f"Collection '{collection}' already exists. Choose a new destination."
                ) from exc
            raise RagStoreUnavailableError("Qdrant could not create the collection.") from exc
        except ValueError as exc:
            # Qdrant's local engine reports duplicate collection creation as ValueError.
            raise RagCollectionConflictError(str(exc)) from exc
        except (ApiException, ResponseHandlingException) as exc:
            raise RagStoreUnavailableError("Qdrant could not create the collection.") from exc
        if created is False:
            raise RagCollectionConflictError(f"Collection '{collection}' was not created.")

    async def upsert(
        self,
        *,
        collection: str,
        chunks: Sequence[str],
        embeddings: Sequence[Sequence[float]],
        asset_id: str,
        dense_model: str,
        language: str,
        embedding_revision: str = "default",
        expected_dimension: int | None = None,
        provenance: Sequence[Mapping[str, object]] | None = None,
    ) -> int:
        if not chunks:
            return 0
        self._validate_upsert_inputs(chunks, embeddings)
        self._validate_expected_dimension(
            len(embeddings[0]), expected_dimension=expected_dimension, context="embedding"
        )
        if provenance is not None and len(provenance) != len(chunks):
            raise ValueError("provenance must contain one metadata record per chunk.")
        async with self._asset_upsert_lock(collection=collection, asset_id=asset_id):
            await self._ensure_hybrid_collection(
                collection=collection,
                dimension=len(embeddings[0]),
                dense_model=dense_model,
                language=language,
                embedding_revision=embedding_revision,
            )
            prior_ids = await self._asset_point_ids(collection=collection, asset_id=asset_id)
            bm25_options = self._bm25_options(language)
            bm25_vectors = await self._embed_bm25_documents(
                chunks,
                language=language,
                options=bm25_options,
            )
            points = []
            for index, (chunk, embedding, bm25_vector) in enumerate(
                zip(chunks, embeddings, bm25_vectors, strict=True)
            ):
                source_metadata = provenance[index] if provenance is not None else {}
                payload: dict[str, object] = {
                    "asset_id": asset_id,
                    "chunk_index": index,
                    "text": chunk,
                }
                for field in (*PROVENANCE_STRING_FIELDS, *PROVENANCE_PAGE_FIELDS):
                    value = source_metadata.get(field)
                    if isinstance(value, (str, int)) and not isinstance(value, bool):
                        payload[field] = value
                points.append(
                    models.PointStruct(
                        id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"{asset_id}:{index}")),
                        vector={
                            DENSE_VECTOR_NAME: list(embedding),
                            BM25_VECTOR_NAME: bm25_vector,
                        },
                        payload=payload,
                    )
                )
            await self._call(
                lambda: self._client.upsert(collection_name=collection, points=points, wait=True)
            )
            current_ids = {str(point.id) for point in points}
            stale_ids = sorted(prior_ids - current_ids)
            if stale_ids:
                await self._call(
                    lambda: self._client.delete(
                        collection_name=collection,
                        points_selector=models.PointIdsList(points=stale_ids),
                        wait=True,
                    )
                )
        return len(points)

    async def search(
        self,
        *,
        collection: str,
        original_embedding: Sequence[float],
        original_query: str,
        rewrite_embeddings: Sequence[Sequence[float]],
        candidate_limit: int,
        result_limit: int,
        rrf_k: int,
        original_dense_weight: float,
        original_bm25_weight: float,
        rewrite_dense_total_weight: float,
        rewrite_queries: Sequence[str],
        dense_model: str | None = None,
        embedding_revision: str | None = None,
        expected_dimension: int | None = None,
    ) -> RagSearchResult:
        # The configured query-vector contract can be checked without touching Qdrant.
        self._validate_expected_dimension(
            len(original_embedding), expected_dimension=expected_dimension, context="query"
        )
        for embedding in rewrite_embeddings:
            self._validate_expected_dimension(
                len(embedding), expected_dimension=expected_dimension, context="rewrite query"
            )
        capabilities = await self.capabilities(collection)
        if capabilities is None:
            return RagSearchResult(
                passages=[],
                retrieval={
                    "mode": "missing_collection",
                    "strategy": "none",
                    "fallback_reason": "collection_not_found",
                },
            )
        if capabilities.mode == "unsupported":
            raise RagCollectionSchemaError(
                f"Collection '{collection}' does not use the supported RAG schema."
            )
        self._validate_query_compatibility(
            collection=collection,
            capabilities=capabilities,
            original_embedding=original_embedding,
            rewrite_embeddings=rewrite_embeddings,
            dense_model=dense_model,
            embedding_revision=embedding_revision,
            expected_dimension=expected_dimension,
        )

        rankings: list[tuple[str, float, models.QueryRequest]] = [
            (
                "dense_original",
                original_dense_weight,
                models.QueryRequest(
                    query=list(original_embedding),
                    using=DENSE_VECTOR_NAME if capabilities.mode == "hybrid" else None,
                    limit=candidate_limit,
                    with_payload=True,
                ),
            )
        ]
        if capabilities.mode == "hybrid" and original_bm25_weight > 0:
            assert capabilities.language is not None
            bm25_query = await self._embed_bm25_query(
                original_query,
                language=capabilities.language,
                options=capabilities.bm25_options or {},
            )
            rankings.append(
                (
                    "bm25_original",
                    original_bm25_weight,
                    models.QueryRequest(
                        query=bm25_query,
                        using=BM25_VECTOR_NAME,
                        limit=candidate_limit,
                        with_payload=True,
                    ),
                )
            )
        if rewrite_embeddings and rewrite_dense_total_weight > 0:
            weight = rewrite_dense_total_weight / len(rewrite_embeddings)
            rankings.extend(
                (
                    f"dense_rewrite_{index}",
                    weight,
                    models.QueryRequest(
                        query=list(embedding),
                        using=DENSE_VECTOR_NAME if capabilities.mode == "hybrid" else None,
                        limit=candidate_limit,
                        with_payload=True,
                    ),
                )
                for index, embedding in enumerate(rewrite_embeddings, start=1)
            )

        responses = await self._call(
            lambda: self._client.query_batch_points(
                collection_name=collection,
                requests=[request for _, _, request in rankings],
            )
        )
        response_rankings = [
            (name, weight, response.points)
            for (name, weight, _), response in zip(rankings, responses, strict=True)
        ]
        passages, malformed_count = self._fuse_rankings(
            rankings=response_rankings,
            rrf_k=rrf_k,
            result_limit=result_limit,
        )
        hybrid = capabilities.mode == "hybrid"
        uses_rrf = len(rankings) > 1
        mode = (
            "hybrid_rrf" if hybrid else ("legacy_multi_query_rrf" if uses_rrf else "legacy_dense")
        )
        for passage in passages:
            passage["score_type"] = "rrf" if uses_rrf else capabilities.dense_distance or "unknown"
        return RagSearchResult(
            passages=passages,
            retrieval={
                "mode": mode,
                "strategy": "hybrid_rrf" if uses_rrf else "dense",
                "candidate_limit": candidate_limit,
                "result_limit": result_limit,
                "rrf_k": rrf_k if uses_rrf else None,
                "language": capabilities.language,
                "active_rankings": [name for name, _, _ in rankings],
                "rewrite_queries": list(rewrite_queries),
                "fallback_reason": None if hybrid else "legacy_dense_collection",
                "malformed_candidates": malformed_count,
            },
        )

    async def _ensure_hybrid_collection(
        self,
        *,
        collection: str,
        dimension: int,
        dense_model: str,
        language: str,
        embedding_revision: str,
    ) -> None:
        capabilities = await self.capabilities(collection)
        if capabilities is None:
            try:
                await self.create_hybrid_collection(
                    collection=collection,
                    dimension=dimension,
                    dense_model=dense_model,
                    language=language,
                    embedding_revision=embedding_revision,
                )
            except (RagCollectionConflictError, RagStoreUnavailableError):
                capabilities = await self.capabilities(collection)
                if capabilities is None:
                    raise
        if capabilities is None:
            capabilities = await self.capabilities(collection)
        assert capabilities is not None
        if capabilities.mode == "legacy_dense":
            raise RagCollectionConflictError(
                f"Collection '{collection}' is legacy dense-only. "
                "Migrate it to a new hybrid collection."
            )
        if capabilities.mode != "hybrid":
            raise RagCollectionConflictError(
                f"Collection '{collection}' does not match the required hybrid RAG schema."
            )
        if capabilities.loader_owned:
            raise RagCollectionConflictError(
                f"Collection '{collection}' is owned by RAG Dataloader and cannot receive "
                "API ingestion."
            )
        info = await self._call(lambda: self._client.get_collection(collection))
        vectors = info.config.params.vectors
        assert isinstance(vectors, dict)
        dense = vectors[DENSE_VECTOR_NAME]
        metadata = info.config.metadata or {}
        if dense.size != dimension:
            raise RagCollectionConflictError(
                f"Collection '{collection}' expects dense vectors of size {dense.size}, "
                f"not {dimension}."
            )
        if metadata.get("rag_dense_model") != dense_model:
            raise RagCollectionConflictError(
                f"Collection '{collection}' uses a different dense embedding model."
            )
        if metadata.get("rag_embedding_revision") != embedding_revision:
            raise RagCollectionConflictError(
                f"Collection '{collection}' uses a different dense embedding revision."
            )
        if capabilities.language != language:
            raise RagCollectionConflictError(
                f"Collection '{collection}' uses BM25 language "
                f"'{capabilities.language}', not '{language}'."
            )

    async def capabilities(self, collection: str) -> CollectionCapabilities | None:
        try:
            info = await self._call(lambda: self._client.get_collection(collection))
        except RagStoreUnavailableError as exc:
            cause = exc.__cause__
            if isinstance(cause, UnexpectedResponse) and cause.status_code == 404:
                return None
            raise
        except ValueError as exc:
            if str(exc) == f"Collection {collection} not found":
                return None
            raise
        params = info.config.params
        vectors = params.vectors
        if isinstance(vectors, models.VectorParams):
            return CollectionCapabilities(
                mode="legacy_dense",
                dense_distance=_distance_name(vectors.distance),
                dense_dimension=vectors.size,
            )
        sparse = params.sparse_vectors or {}
        metadata = info.config.metadata or {}
        if (
            isinstance(vectors, dict)
            and DENSE_VECTOR_NAME in vectors
            and BM25_VECTOR_NAME in sparse
            and metadata.get("rag_schema_version") == RAG_SCHEMA_VERSION
            and metadata.get("rag_bm25_model") == BM25_MODEL_NAME
        ):
            dense_model = metadata.get("rag_dense_model")
            embedding_revision = metadata.get("rag_embedding_revision")
            dense_dimension = metadata.get("rag_dense_dimension")
            if (
                not isinstance(dense_model, str)
                or not dense_model
                or not isinstance(embedding_revision, str)
                or not embedding_revision
                or not _positive_int(dense_dimension)
                or dense_dimension != vectors[DENSE_VECTOR_NAME].size
                or metadata.get("rag_dense_vector") != DENSE_VECTOR_NAME
                or metadata.get("rag_bm25_vector") != BM25_VECTOR_NAME
            ):
                return CollectionCapabilities(mode="unsupported")
            language = metadata.get("rag_bm25_language")
            options = metadata.get("rag_bm25_options")
            if isinstance(language, str) and isinstance(options, dict):
                bm25_options = dict(options)
                bm25_options["language"] = language
                return CollectionCapabilities(
                    mode="hybrid",
                    language=language,
                    bm25_options=bm25_options,
                    dense_distance=_distance_name(vectors[DENSE_VECTOR_NAME].distance),
                    dense_model=dense_model,
                    embedding_revision=embedding_revision,
                    dense_dimension=dense_dimension,
                    loader_owned=metadata.get(COLLECTION_OWNER_KEY) == LOADER_COLLECTION_OWNER,
                )
        return CollectionCapabilities(mode="unsupported")

    async def list_collections(self) -> list[dict[str, object]]:
        response = await self._call(self._client.get_collections)
        collections = []
        for item in response.collections:
            count = await self.get_collection_count(item.name)
            collections.append({"name": item.name, "document_count": count, "metadata": {}})
        return collections

    async def get_collection_count(self, collection: str) -> int:
        response = await self._call(
            lambda: self._client.count(collection_name=collection, exact=False)
        )
        return int(response.count)

    async def collection_source_chunk_payloads(
        self, collection: str
    ) -> dict[str, dict[str, object]]:
        """Return source-ID keyed citation fields for migration verification."""
        payloads: dict[str, dict[str, object]] = {}
        offset: str | int | None = None
        while True:
            records, offset = await self._call(
                lambda selected_offset=offset: self._client.scroll(
                    collection_name=collection,
                    limit=256,
                    offset=selected_offset,
                    with_payload=[
                        "source_chunk_id",
                        "filename",
                        "source",
                        "page",
                        "page_start",
                        "page_end",
                        "section",
                    ],
                    with_vectors=False,
                )
            )
            for record in records:
                payload = record.payload if isinstance(record.payload, dict) else {}
                source_id = payload.get("source_chunk_id")
                if isinstance(source_id, str):
                    payloads[source_id] = dict(payload)
            if offset is None:
                return payloads

    async def delete_collection(self, collection: str) -> bool:
        capabilities = await self.capabilities(collection)
        if capabilities is None:
            return False
        if capabilities.mode == "unsupported":
            raise RagCollectionSchemaError(
                f"Collection '{collection}' has an unsupported schema and cannot be deleted here."
            )
        if capabilities.loader_owned:
            raise RagCollectionSchemaError(
                f"Collection '{collection}' is owned by the RAG loader and cannot be deleted here."
            )
        await self._call(lambda: self._client.delete_collection(collection_name=collection))
        return True

    @asynccontextmanager
    async def _asset_upsert_lock(self, *, collection: str, asset_id: str) -> AsyncIterator[None]:
        key = (collection, asset_id)
        async with self._asset_locks_guard:
            entry = self._asset_locks.get(key)
            if entry is None:
                entry = AssetUpsertLock(lock=asyncio.Lock())
                self._asset_locks[key] = entry
            entry.users += 1
        acquired = False
        try:
            await entry.lock.acquire()
            acquired = True
            yield
        finally:
            if acquired:
                entry.lock.release()
            async with self._asset_locks_guard:
                entry.users -= 1
                if entry.users == 0 and self._asset_locks.get(key) is entry:
                    del self._asset_locks[key]

    async def _asset_point_ids(self, *, collection: str, asset_id: str) -> set[str]:
        found: set[str] = set()
        offset: str | int | uuid.UUID | None = None
        selector = models.Filter(
            must=[models.FieldCondition(key="asset_id", match=models.MatchValue(value=asset_id))]
        )
        while True:
            selected_offset = offset
            records, offset = await self._call(
                lambda selected_offset=selected_offset: self._client.scroll(
                    collection_name=collection,
                    scroll_filter=selector,
                    limit=256,
                    offset=selected_offset,
                    with_payload=False,
                    with_vectors=False,
                )
            )
            found.update(str(record.id) for record in records)
            if offset is None:
                return found

    @staticmethod
    def _validate_upsert_inputs(
        chunks: Sequence[str], embeddings: Sequence[Sequence[float]]
    ) -> None:
        if len(chunks) != len(embeddings):
            raise RagCollectionConflictError(
                "Chunks and dense embeddings must have the same length."
            )
        if not embeddings or not embeddings[0]:
            raise RagCollectionConflictError("At least one non-empty dense embedding is required.")
        dimension = len(embeddings[0])
        if any(len(embedding) != dimension for embedding in embeddings):
            raise RagCollectionConflictError("Dense embeddings must share one dimension.")
        if any(not chunk.strip() for chunk in chunks):
            raise RagCollectionConflictError("RAG chunks must contain text.")

    @staticmethod
    def _metadata(
        *, dense_model: str, embedding_revision: str, dimension: int, language: str
    ) -> dict[str, object]:
        return {
            "rag_schema_version": RAG_SCHEMA_VERSION,
            "rag_dense_model": dense_model,
            "rag_embedding_revision": embedding_revision,
            "rag_dense_dimension": dimension,
            "rag_dense_vector": DENSE_VECTOR_NAME,
            "rag_bm25_vector": BM25_VECTOR_NAME,
            "rag_bm25_model": BM25_MODEL_NAME,
            "rag_bm25_language": language,
            "rag_bm25_options": BM25_DEFAULTS,
        }

    @staticmethod
    def _validate_expected_dimension(
        dimension: int, *, expected_dimension: int | None, context: str
    ) -> None:
        if expected_dimension is not None and dimension != expected_dimension:
            raise RagCollectionConflictError(
                f"Configured dense embedding dimension is {expected_dimension}, "
                f"but the {context} vector has dimension {dimension}."
            )

    @classmethod
    def _validate_query_compatibility(
        cls,
        *,
        collection: str,
        capabilities: CollectionCapabilities,
        original_embedding: Sequence[float],
        rewrite_embeddings: Sequence[Sequence[float]],
        dense_model: str | None,
        embedding_revision: str | None,
        expected_dimension: int | None,
    ) -> None:
        collection_dimension = capabilities.dense_dimension
        assert collection_dimension is not None
        cls._validate_expected_dimension(
            len(original_embedding), expected_dimension=expected_dimension, context="query"
        )
        if len(original_embedding) != collection_dimension:
            raise RagCollectionConflictError(
                f"Collection '{collection}' expects dense vectors of size "
                f"{collection_dimension}, not {len(original_embedding)}."
            )
        for index, embedding in enumerate(rewrite_embeddings, start=1):
            cls._validate_expected_dimension(
                len(embedding), expected_dimension=expected_dimension, context="rewrite query"
            )
            if len(embedding) != collection_dimension:
                raise RagCollectionConflictError(
                    f"Collection '{collection}' expects dense rewrite vectors of size "
                    f"{collection_dimension}, not {len(embedding)} (rewrite {index})."
                )
        if capabilities.mode == "hybrid":
            if not isinstance(dense_model, str) or not dense_model.strip():
                raise RagCollectionConflictError(
                    f"Collection '{collection}' requires an explicit dense embedding model."
                )
            if not isinstance(embedding_revision, str) or not embedding_revision.strip():
                raise RagCollectionConflictError(
                    f"Collection '{collection}' requires an explicit dense embedding revision."
                )
            if capabilities.dense_model != dense_model:
                raise RagCollectionConflictError(
                    f"Collection '{collection}' uses a different dense embedding model."
                )
            if capabilities.embedding_revision != embedding_revision:
                raise RagCollectionConflictError(
                    f"Collection '{collection}' uses a different dense embedding revision."
                )

    @staticmethod
    def _bm25_options(language: str) -> dict[str, object]:
        return {**BM25_DEFAULTS, "language": language}

    async def _embed_bm25_documents(
        self,
        texts: Sequence[str],
        *,
        language: str,
        options: dict[str, object],
    ) -> list[models.SparseVector]:
        try:
            vectors = await self._bm25_encoder.embed_documents(
                texts,
                language=language,
                options=options,
            )
        except Exception as exc:
            raise RagStoreUnavailableError(
                "FastEmbed BM25 could not encode the RAG documents."
            ) from exc
        if len(vectors) != len(texts):
            raise RagStoreUnavailableError(
                "FastEmbed BM25 returned an invalid document embedding count."
            )
        return vectors

    async def _embed_bm25_query(
        self,
        text: str,
        *,
        language: str,
        options: dict[str, object],
    ) -> models.SparseVector:
        try:
            return await self._bm25_encoder.embed_query(
                text,
                language=language,
                options=options,
            )
        except Exception as exc:
            raise RagStoreUnavailableError(
                "FastEmbed BM25 could not encode the RAG query."
            ) from exc

    @staticmethod
    def _fuse_rankings(
        *,
        rankings: Sequence[tuple[str, float, Sequence[object]]],
        rrf_k: int,
        result_limit: int,
    ) -> tuple[list[dict[str, object]], int]:
        candidates: dict[str, dict[str, object]] = {}
        malformed_count = 0
        single_ranking = len(rankings) == 1
        for name, weight, points in rankings:
            seen: set[str] = set()
            for rank, point in enumerate(points, start=1):
                point_id = str(point.id)
                if point_id in seen:
                    continue
                seen.add(point_id)
                payload = point.payload if isinstance(point.payload, dict) else {}
                text = payload.get("text")
                asset_id = payload.get("asset_id")
                chunk_index = payload.get("chunk_index")
                if (
                    not isinstance(text, str)
                    or not text.strip()
                    or asset_id is None
                    or chunk_index is None
                ):
                    malformed_count += 1
                    continue
                candidate = candidates.setdefault(
                    point_id,
                    {
                        "point_id": point_id,
                        "asset_id": asset_id,
                        "chunk_index": chunk_index,
                        "text": text,
                        "score": 0.0,
                        "best_rank": rank,
                        "sources": [],
                    },
                )
                candidate["best_rank"] = min(int(candidate["best_rank"]), rank)
                provenance = _provenance(payload)
                if provenance:
                    existing_provenance = candidate.get("provenance")
                    if isinstance(existing_provenance, dict):
                        existing_provenance.update(provenance)
                    else:
                        candidate["provenance"] = provenance
                raw_score = float(point.score)
                contribution = raw_score if single_ranking else weight / (rrf_k + rank)
                candidate["score"] = float(candidate["score"]) + contribution
                sources = candidate["sources"]
                assert isinstance(sources, list)
                sources.append(
                    {
                        "ranking": name,
                        "rank": rank,
                        "weight": weight,
                        "raw_score": raw_score,
                    }
                )
        ordered = sorted(
            candidates.values(),
            key=lambda item: (-float(item["score"]), int(item["best_rank"]), str(item["point_id"])),
        )[:result_limit]
        for item in ordered:
            item.pop("best_rank")
        return ordered, malformed_count

    async def _call(self, operation: Callable[[], Awaitable[T]]) -> T:
        try:
            return await operation()
        except (ApiException, ResponseHandlingException, UnexpectedResponse) as exc:
            raise RagStoreUnavailableError(
                "Qdrant is unavailable for the requested RAG operation."
            ) from exc


def _distance_name(distance: models.Distance) -> str:
    return str(distance).split(".")[-1].lower()


def _positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _provenance(payload: dict[object, object]) -> dict[str, object]:
    provenance: dict[str, object] = {}
    for field in PROVENANCE_STRING_FIELDS:
        value = payload.get(field)
        if isinstance(value, str) and value.strip():
            provenance[field] = value
    for field in PROVENANCE_PAGE_FIELDS:
        value = payload.get(field)
        if isinstance(value, int) and not isinstance(value, bool):
            provenance[field] = value
    return provenance

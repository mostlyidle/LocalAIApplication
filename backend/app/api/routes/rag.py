"""RAG (Retrieval-Augmented Generation) endpoints.

Provides:
    POST /rag/search         — Semantic search across ingested documents.
    POST /rag/ingest         — Ingest a document into the vector store.
    GET  /rag/collections    — List all vector store collections.
    DELETE /rag/collections/{name} — Delete a collection.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: TC002 - FastAPI resolves this at runtime

from app.api.middleware.error_handler import NotFoundError
from app.api.middleware.rate_limiting import limiter
from app.config import settings
from app.dependencies import (
    DocumentParserService,
    VectorStoreService,
    get_authenticated_session,
    get_db,
    get_document_parser,
    get_vector_store,
)
from app.models.db_models import Document, RagCollection
from app.models.enums import DocumentFormat
from app.models.schemas import (
    CollectionInfo,
    RAGIngestRequest,
    RAGSearchRequest,
    RAGSearchResponse,
    RAGSearchResult,
)
from app.services.auth import AuthenticatedSession  # noqa: TC001
from app.services.rag_access import collection_access
from app.services.rag_store import (
    RagCollectionConflictError,
    RagCollectionSchemaError,
    RagStoreUnavailableError,
)

logger = structlog.get_logger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# POST /rag/search — semantic search
# ---------------------------------------------------------------------------


@router.post("/rag/search", response_model=RAGSearchResponse)
@limiter.limit(settings.rate_limit_embedding)
async def search_documents(
    request: Request,
    body: RAGSearchRequest,
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
    vector_store: VectorStoreService = Depends(get_vector_store),  # noqa: B008
) -> RAGSearchResponse:
    """Perform semantic search across ingested documents.

    Returns ranked results with relevance scores and source citations.
    """
    access = await collection_access(
        db, vector_store, name=body.collection, owner_id=authenticated.account.id
    )
    if access in {"foreign", "unassigned"}:
        raise NotFoundError("Collection", body.collection)

    retrieval: dict[str, Any] = {}
    search_with_provenance = getattr(vector_store, "search_with_provenance", None)
    try:
        if search_with_provenance is not None:
            result = await search_with_provenance(
                query=body.query,
                collection=body.collection,
                top_k=body.top_k,
                score_threshold=body.score_threshold,
                agent_name=body.agent_name,
            )
            results = result.passages
            retrieval = result.retrieval
        else:
            results = await vector_store.search(
                query=body.query,
                collection=body.collection,
                top_k=body.top_k,
                score_threshold=body.score_threshold,
            )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RagCollectionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RagCollectionSchemaError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RagStoreUnavailableError as exc:
        raise HTTPException(status_code=503, detail="RAG store is unavailable.") from exc

    search_results = [
        RAGSearchResult(
            content=r["content"],
            score=r["score"],
            score_type=r.get("score_type", "cosine"),
            source=r.get("metadata", {}).get("source", "unknown"),
            page=r.get("metadata", {}).get("page"),
            section=r.get("metadata", {}).get("section"),
            metadata=r.get("metadata", {}),
        )
        for r in results
    ]

    logger.info(
        "rag_search_completed",
        query_length=len(body.query),
        results=len(search_results),
        collection=body.collection,
    )

    return RAGSearchResponse(
        query=body.query,
        results=search_results,
        total_results=len(search_results),
        retrieval=retrieval,
    )


# ---------------------------------------------------------------------------
# POST /rag/ingest — ingest a document into the vector store
# ---------------------------------------------------------------------------


@router.post("/rag/ingest")
@limiter.limit(settings.rate_limit_embedding)
async def ingest_document(
    request: Request,
    body: RAGIngestRequest,
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
    parser: DocumentParserService = Depends(get_document_parser),  # noqa: B008
    vector_store: VectorStoreService = Depends(get_vector_store),  # noqa: B008
) -> dict[str, Any]:
    """Parse a document and ingest its chunks into the vector store.

    The document must already be uploaded (via /documents/upload). This
    endpoint parses the document, splits into chunks, generates embeddings,
    and stores them in the specified Qdrant collection.
    """
    # Fetch document record
    stmt = select(Document).where(
        Document.id == body.document_id,
        Document.owner_id == authenticated.account.id,
    )
    result = await db.execute(stmt)
    doc = result.scalar_one_or_none()

    if doc is None:
        raise NotFoundError("Document", body.document_id)

    file_path = Path(doc.storage_path)
    if not file_path.exists():
        raise NotFoundError("Document file", body.document_id)

    # Parse the document
    doc_format = DocumentFormat(doc.format)
    parsed = await parser.parse(file_path, doc_format)

    # Chunk the text
    chunks = parser.chunk_document(
        parsed,
        metadata={
            "source": doc.filename,
            "document_id": doc.id,
            "format": doc.format,
        },
    )

    if not chunks:
        return {
            "document_id": doc.id,
            "collection": body.collection,
            "chunks_ingested": 0,
            "message": "No text content found in document.",
        }

    access = await collection_access(
        db,
        vector_store,
        name=body.collection,
        owner_id=authenticated.account.id,
        reserve=True,
    )
    if access == "shared":
        raise HTTPException(status_code=403, detail="Shared RAG collections are read-only.")
    if access in {"foreign", "unassigned"}:
        raise NotFoundError("Collection", body.collection)

    # Prepare data for vector store
    texts = [c["text"] for c in chunks]
    metadatas = [c["metadata"] for c in chunks]
    ids = [f"{doc.id}-chunk-{i}" for i in range(len(chunks))]

    # Ingest into vector store
    count = await vector_store.add_documents(
        texts=texts,
        metadatas=metadatas,
        ids=ids,
        collection=body.collection,
    )

    logger.info(
        "document_ingested",
        doc_id=doc.id,
        filename=doc.filename,
        chunks=count,
        collection=body.collection,
    )

    return {
        "document_id": doc.id,
        "filename": doc.filename,
        "collection": body.collection,
        "chunks_ingested": count,
        "total_characters": sum(len(t) for t in texts),
    }


# ---------------------------------------------------------------------------
# GET /rag/collections — list all collections
# ---------------------------------------------------------------------------


@router.get("/rag/collections", response_model=list[CollectionInfo])
async def list_collections(
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
    vector_store: VectorStoreService = Depends(get_vector_store),  # noqa: B008
) -> list[CollectionInfo]:
    """List all vector store collections with document counts."""
    collections = await vector_store.list_collections()

    result = []
    for collection in collections:
        access = await collection_access(
            db,
            vector_store,
            name=collection["name"],
            owner_id=authenticated.account.id,
        )
        if access in {"owned", "shared"}:
            result.append(
                CollectionInfo(
                    name=collection["name"],
                    document_count=collection.get("document_count", 0),
                    metadata=collection.get("metadata", {}),
                )
            )
    return result


# ---------------------------------------------------------------------------
# DELETE /rag/collections/{name}
# ---------------------------------------------------------------------------


@router.delete("/rag/collections/{name}")
async def delete_collection(
    name: str,
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
    vector_store: VectorStoreService = Depends(get_vector_store),  # noqa: B008
) -> dict[str, Any]:
    """Delete a vector store collection and all its data."""
    access = await collection_access(db, vector_store, name=name, owner_id=authenticated.account.id)
    if access == "shared":
        raise HTTPException(status_code=403, detail="Shared RAG collections cannot be deleted.")
    if access != "owned":
        raise NotFoundError("Collection", name)

    deleted = await vector_store.delete_collection(name)

    if not deleted:
        raise NotFoundError("Collection", name)

    registry = await db.get(RagCollection, name)
    if registry is not None:
        await db.delete(registry)
        await db.commit()

    logger.info("collection_deleted_via_api", name=name)
    return {"status": "deleted", "collection": name}

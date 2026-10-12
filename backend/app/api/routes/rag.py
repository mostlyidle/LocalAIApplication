"""RAG (Retrieval-Augmented Generation) endpoints.

Provides:
    POST /rag/search         — Semantic search across ingested documents.
    POST /rag/ingest         — Ingest a document into the vector store.
    GET  /rag/collections    — List all vector store collections.
    DELETE /rag/collections/{name} — Delete a collection.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.middleware.error_handler import NotFoundError
from app.api.middleware.rate_limiting import limiter
from app.config import settings
from app.dependencies import (
    DocumentParserService,
    VectorStoreService,
    get_db,
    get_document_parser,
    get_vector_store,
)
from app.models.db_models import Document
from app.models.enums import DocumentFormat
from app.models.schemas import (
    CollectionInfo,
    RAGIngestRequest,
    RAGSearchRequest,
    RAGSearchResponse,
    RAGSearchResult,
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
    vector_store: VectorStoreService = Depends(get_vector_store),
) -> RAGSearchResponse:
    """Perform semantic search across ingested documents.

    Returns ranked results with relevance scores and source citations.
    """
    retrieval: dict[str, Any] = {}
    search_with_provenance = getattr(vector_store, "search_with_provenance", None)
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
    db: AsyncSession = Depends(get_db),
    parser: DocumentParserService = Depends(get_document_parser),
    vector_store: VectorStoreService = Depends(get_vector_store),
) -> dict[str, Any]:
    """Parse a document and ingest its chunks into the vector store.

    The document must already be uploaded (via /documents/upload). This
    endpoint parses the document, splits into chunks, generates embeddings,
    and stores them in the specified Qdrant collection.
    """
    # Fetch document record
    stmt = select(Document).where(Document.id == body.document_id)
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
    vector_store: VectorStoreService = Depends(get_vector_store),
) -> list[CollectionInfo]:
    """List all vector store collections with document counts."""
    collections = await vector_store.list_collections()

    return [
        CollectionInfo(
            name=c["name"],
            document_count=c.get("document_count", 0),
            metadata=c.get("metadata", {}),
        )
        for c in collections
    ]


# ---------------------------------------------------------------------------
# DELETE /rag/collections/{name}
# ---------------------------------------------------------------------------


@router.delete("/rag/collections/{name}")
async def delete_collection(
    name: str,
    vector_store: VectorStoreService = Depends(get_vector_store),
) -> dict[str, Any]:
    """Delete a vector store collection and all its data."""
    deleted = await vector_store.delete_collection(name)

    if not deleted:
        raise NotFoundError("Collection", name)

    logger.info("collection_deleted_via_api", name=name)
    return {"status": "deleted", "collection": name}

"""Qdrant dense/BM25 retrieval with Local AI document provenance."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.config import settings
from app.services.bm25 import FastEmbedBm25
from app.services.embeddings import embedding_service
from app.services.fastembed_queries import (
    LOADER_EMBEDDING_DIMENSION,
    LOADER_EMBEDDING_MODEL,
    LOADER_EMBEDDING_REVISION,
    FastEmbedQueries,
)
from app.services.rag_store import CollectionCapabilities, RagSearchResult, RagStore
from app.services.vector_store import VectorStoreService

if TYPE_CHECKING:
    from collections.abc import Mapping

    from app.agents.registry import AgentManifest, AgentRegistry
    from app.prompt_store import PromptStore
    from app.services.laya_rag import LayaRagService

class HybridVectorStoreService(VectorStoreService):
    """Drop-in vector-store API backed by Qdrant, BM25, and bounded profiles."""

    def __init__(self) -> None:
        prompt_dir = Path(__file__).parents[1] / "prompts"
        self._rag = RagStore(
            settings.qdrant_url,
            bm25_encoder=FastEmbedBm25(cache_dir=settings.fastembed_cache_path),
        )
        self._loader_queries = FastEmbedQueries(cache_dir=settings.fastembed_cache_path)
        self._prompt_dir = prompt_dir
        self._profiles: AgentRegistry | None = None
        self._prompts: PromptStore | None = None
        self._laya: LayaRagService | None = None

    async def close(self) -> None:
        await self._rag.close()

    async def collection_capabilities(self, collection: str) -> CollectionCapabilities | None:
        """Return schema and loader ownership for a named collection."""
        return await self._rag.capabilities(collection)

    async def add_documents(
        self,
        texts: list[str],
        metadatas: list[dict[str, Any]],
        ids: list[str],
        collection: str | None = None,
        language: str | None = None,
    ) -> int:
        if not texts:
            return 0
        if len(texts) != len(metadatas) or len(texts) != len(ids):
            raise ValueError("texts, metadatas, and ids must have equal lengths.")
        identity = await embedding_service.get_identity()
        embeddings = await embedding_service.embed_texts(texts)
        if await embedding_service.get_identity() != identity:
            raise ValueError(
                "Embedding weights changed during ingestion; retry with pinned weights."
            )
        if not embeddings or len(embeddings) != len(texts):
            raise ValueError("Embedding service returned incomplete vectors.")
        dimension = len(embeddings[0])
        if any(len(vector) != dimension for vector in embeddings):
            raise ValueError("Embedding service returned inconsistent vector dimensions.")
        first_metadata = metadatas[0]
        asset_id = str(first_metadata.get("document_id") or ids[0].rsplit("_", 1)[0])
        revision = self._embedding_revision(identity)
        return await self._rag.upsert(
            collection=collection or settings.chroma_collection_name,
            chunks=texts,
            embeddings=embeddings,
            asset_id=asset_id,
            dense_model=identity["embedding_model"],
            language=language or settings.rag_bm25_language,
            embedding_revision=revision,
            expected_dimension=settings.ollama_embedding_dimension,
            provenance=[self._payload_metadata(metadata) for metadata in metadatas],
        )

    async def search(
        self,
        query: str,
        collection: str | None = None,
        top_k: int | None = None,
        score_threshold: float | None = None,
        agent_name: str = "rag",
        rewrite_model: str | None = None,
        owner_id: str | None = None,
    ) -> list[dict[str, Any]]:
        selected_collection = collection or settings.chroma_collection_name
        if owner_id is not None:
            from app.api.middleware.error_handler import NotFoundError
            from app.services.database import get_app_session_factory
            from app.services.rag_access import collection_access

            async with get_app_session_factory()() as db:
                access = await collection_access(
                    db, self, name=selected_collection, owner_id=owner_id
                )
            if access in {"foreign", "unassigned", "missing"}:
                raise NotFoundError("Collection", selected_collection)

        result = await self.search_with_provenance(
            query=query,
            collection=selected_collection,
            top_k=top_k or settings.rag_top_k,
            score_threshold=score_threshold,
            agent_name=agent_name,
            rewrite_model=rewrite_model,
        )
        return result.passages

    async def search_with_provenance(
        self,
        *,
        query: str,
        collection: str,
        top_k: int,
        score_threshold: float | None = None,
        agent_name: str = "rag",
        rewrite_model: str | None = None,
        _bypass_laya_rewrite: bool = False,
    ) -> RagSearchResult:
        profile = self.profile_registry().get(agent_name)
        if profile is None or profile.target != "rag" or profile.retrieval is None:
            raise ValueError(f"'{agent_name}' is not an enabled RAG profile.")
        retrieval = profile.retrieval
        rewrites: list[str] = []
        rewrite_failure = None
        rewrite_applied = False
        initial_reason = "profile_has_no_rewrites"
        if retrieval.query_rewrite.count and score_threshold is not None:
            initial_reason = "score_threshold_compatibility"
        laya_rewrite = self._laya_gate_metadata(
            mode=settings.laya_rag_rewrite_mode, reason=initial_reason
        )
        if retrieval.query_rewrite.count and score_threshold is None:
            mode = settings.laya_rag_rewrite_mode
            laya = getattr(self, "_laya", None)
            if _bypass_laya_rewrite:
                laya_rewrite = self._laya_gate_metadata(
                    mode=mode, reason="rescue_retrieval"
                )
            elif mode == "off":
                laya_rewrite = self._laya_gate_metadata(mode=mode, reason="off")
            elif (context_reason := self._rewrite_context_reason(query)) is not None:
                laya_rewrite = self._laya_gate_metadata(mode=mode, reason=context_reason)
            elif laya is None:
                laya_rewrite = self._laya_gate_metadata(mode=mode, reason="not_ready")
            else:
                decision = await laya.check_rewrite(query)
                eligible, policy_reason = laya.can_apply(
                    "rewrite",
                    profile=profile.name,
                    prompt_digest=self._rewrite_configuration_digest(profile),
                    decision=decision,
                    input_covered=query.isascii() and len(query.encode("utf-8")) <= 512,
                )
                rewrite_applied = mode == "enforce" and eligible
                laya_rewrite = self._laya_gate_metadata(
                    mode=mode,
                    reason=policy_reason,
                    decision=decision,
                    would_apply=eligible,
                    applied=rewrite_applied,
                    model_digest=laya.model_digest,
                )

        if retrieval.query_rewrite.count and not rewrite_applied:
            rewrites, rewrite_failure = await self._rewrite_queries(
                query,
                profile.name,
                retrieval.query_rewrite.count,
                retrieval.query_rewrite.max_output_tokens,
                model=rewrite_model,
            )

        capabilities = await self._rag.capabilities(collection)
        if capabilities is None:
            return RagSearchResult(
                passages=[],
                retrieval={
                    "mode": "missing_collection",
                    "strategy": "none",
                    "laya": {"rewrite": laya_rewrite},
                },
            )
        recorded_identity_only = False
        if (
            capabilities.loader_owned
            and capabilities.dense_model == LOADER_EMBEDDING_MODEL
            and capabilities.embedding_revision == LOADER_EMBEDDING_REVISION
        ):
            dense_model = LOADER_EMBEDDING_MODEL
            embedding_revision = LOADER_EMBEDDING_REVISION
            expected_dimension = LOADER_EMBEDDING_DIMENSION
            embeddings = await self._loader_queries.embed([query, *rewrites])
        else:
            identity = await embedding_service.get_identity()
            dense_model = identity["embedding_model"]
            embedding_revision = self._embedding_revision(identity)
            expected_dimension = settings.ollama_embedding_dimension
            # Older API collections recorded model/revision, but no weight digest.
            if (
                capabilities.mode == "hybrid"
                and not capabilities.loader_owned
                and capabilities.embedding_revision == settings.ollama_embedding_revision
                and capabilities.dense_model is not None
                and (capabilities.dense_model if ":" in capabilities.dense_model else capabilities.dense_model + ":latest") == identity["embedding_model"]
                and identity["embedding_profile"] == "plain-v1"
            ):
                dense_model = capabilities.dense_model
                embedding_revision = capabilities.embedding_revision
                recorded_identity_only = True
            embeddings = [await embedding_service.embed_text(text) for text in [query, *rewrites]]
            if await embedding_service.get_identity() != identity:
                raise ValueError(
                    "Embedding weights changed during search; retry with pinned weights."
                )

        weights = retrieval.weights
        dense_weight = weights.original_dense
        bm25_weight = weights.original_bm25
        rewrite_weight = weights.rewrite_dense_total
        if rewrite_applied:
            rewrite_weight = 0
        if score_threshold is not None:
            # Compatibility for callers that still request cosine threshold semantics.
            bm25_weight = 0
            rewrite_weight = 0
            rewrites = []
            embeddings = embeddings[:1]

        result = await self._rag.search(
            collection=collection,
            original_embedding=embeddings[0],
            original_query=query,
            rewrite_embeddings=embeddings[1:],
            candidate_limit=max(retrieval.candidate_limit, top_k),
            result_limit=min(top_k, retrieval.result_limit),
            rrf_k=retrieval.rrf_k,
            original_dense_weight=dense_weight,
            original_bm25_weight=bm25_weight,
            rewrite_dense_total_weight=rewrite_weight,
            rewrite_queries=rewrites,
            dense_model=dense_model,
            embedding_revision=embedding_revision,
            expected_dimension=expected_dimension,
        )
        passages = [self._local_result(item) for item in result.passages]
        if score_threshold is not None:
            passages = [
                item
                for item in passages
                if item["score_type"] != "cosine" or item["score"] >= score_threshold
            ]
        metadata = {
            **result.retrieval,
            "agent_name": profile.name,
            "rewrite_failure": rewrite_failure,
            "skipped_by_laya": rewrite_applied,
            "recorded_identity_only": recorded_identity_only,
            "laya": {"rewrite": laya_rewrite},
        }
        return RagSearchResult(passages=passages, retrieval=metadata)

    def _rewrite_configuration_digest(self, profile: AgentManifest) -> str:
        """Fingerprint the retrieval profile and effective rewrite prompt templates."""
        from app.prompt_store import PromptStore

        prompts = getattr(self, "_prompts", None)
        if prompts is None:
            prompts = self._prompts = PromptStore(self._prompt_dir)
        rewrite = profile.retrieval.query_rewrite
        system, user = prompts.render_messages_for(
            profile.name,
            "rag",
            "rewrite",
            {"prompt": "__QUESTION__", "rewrite_count": rewrite.count},
        )
        material = {
            "profile": profile.model_dump(mode="json"),
            "rewrite_system": system,
            "rewrite_user": user,
        }
        serialized = json.dumps(material, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    @staticmethod
    def _rewrite_context_reason(query: str) -> str | None:
        if len(query.encode("utf-8")) > 512:
            return "budget_exceeded"
        if not query.isascii():
            return "unsupported_language"
        if re.search(
            r"\b(?:it|this|that|they|them|those|these|same|former|latter|the first|the second)\b",
            query.casefold(),
        ):
            return "context_dependent"
        return None

    @staticmethod
    def _laya_gate_metadata(
        *,
        mode: str,
        reason: str,
        decision: object | None = None,
        would_apply: bool = False,
        applied: bool = False,
        model_digest: str | None = None,
    ) -> dict[str, object]:
        return {
            "mode": mode,
            "outcome": getattr(decision, "choice", None) or "not_run",
            "reason": reason,
            "choice": getattr(decision, "choice", None),
            "probability": getattr(decision, "probability", None),
            "schema_version": getattr(decision, "schema_version", "rewrite-v1"),
            "model_digest": model_digest,
            "elapsed_ms": getattr(decision, "elapsed_ms", 0),
            "would_apply": would_apply,
            "applied": applied,
        }

    async def _rewrite_queries(
        self, query: str, agent_name: str, count: int, max_output_tokens: int,
        *, model: str | None = None,
    ) -> tuple[list[str], str | None]:
        from pydantic import BaseModel, Field, ValidationError

        class QueryRewriteResponse(BaseModel):
            queries: list[str] = Field(max_length=4)

        profile = self.profile_registry().get(agent_name)
        if profile is None or profile.inference is None:
            return [], "invalid_profile"
        prompt_store = getattr(self, "_prompts", None)
        if prompt_store is None:
            from app.prompt_store import PromptStore

            prompt_store = self._prompts = PromptStore(self._prompt_dir)
        system, prompt = prompt_store.render_messages_for(
            agent_name,
            "rag",
            "rewrite",
            {"prompt": query, "rewrite_count": count},
        )
        llm = self._chat_model(
            model=model or profile.inference.default_model,
            temperature=0,
            max_output_tokens=max_output_tokens,
            context_window=2048,
        )
        try:
            response = await llm.with_structured_output(QueryRewriteResponse).ainvoke(
                f"{system}\n\n{prompt}"
            )
        except Exception:
            return [], "rewrite_unavailable"
        try:
            parsed = (
                response
                if isinstance(response, QueryRewriteResponse)
                else QueryRewriteResponse.model_validate(response)
            )
        except ValidationError:
            return [], "invalid_structured_output"
        distinct: list[str] = []
        seen = {query.strip().casefold()}
        for candidate in parsed.queries:
            value = candidate.strip()
            if value and len(value) <= 1_000 and value.casefold() not in seen:
                seen.add(value.casefold())
                distinct.append(value)
        if len(distinct) != count:
            return [], "insufficient_distinct_rewrites"
        return distinct, None

    def profile_registry(self) -> AgentRegistry:
        if self._profiles is None:
            from app.agents.registry import AgentRegistry
            from app.prompt_store import PromptStore

            prompts = PromptStore(self._prompt_dir)
            self._prompts = prompts
            self._profiles = AgentRegistry(self._prompt_dir, prompts)
        return self._profiles

    def configure_profiles(self, profiles: AgentRegistry, prompts: PromptStore) -> None:
        """Use the application registry and prompt sources for profile retrieval."""
        self._profiles = profiles
        self._prompts = prompts

    @property
    def laya_service(self) -> LayaRagService | None:
        """Return the lifespan-owned local decision client when configured."""
        return self._laya

    def configure_laya_service(self, service: LayaRagService) -> None:
        """Attach the one application-owned Laya client to shared RAG retrieval."""
        self._laya = service

    @staticmethod
    def _chat_model(*, model: str, temperature: float, max_output_tokens: int, context_window: int):
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=model,
            base_url=settings.ollama_base_url,
            temperature=temperature,
            num_predict=max_output_tokens,
            num_ctx=context_window,
            timeout=settings.ollama_request_timeout,
        )

    @staticmethod
    def _embedding_revision(identity: Mapping[str, str]) -> str:
        return ":".join(
            (
                settings.ollama_embedding_revision,
                identity["embedding_digest"],
                identity["embedding_profile"],
            )
        )

    @staticmethod
    def _payload_metadata(metadata: Mapping[str, object]) -> dict[str, object]:
        result = dict(metadata)
        if "source" in result and "filename" not in result:
            result["filename"] = result["source"]
        if "page" in result:
            result["page_start"] = result["page"]
        return result

    @staticmethod
    def _local_result(item: dict[str, object]) -> dict[str, Any]:
        provenance = item.get("provenance", {})
        if not isinstance(provenance, dict):
            provenance = {}
        source = provenance.get("filename") or provenance.get("source") or item["asset_id"]
        page_start = provenance.get("page_start") or provenance.get("page")
        metadata: dict[str, object] = {
            **provenance,
            "source": source,
            "document_id": provenance.get("document_id", item["asset_id"]),
            "asset_id": item["asset_id"],
            "chunk_index": item["chunk_index"],
        }
        if page_start is not None:
            metadata["page"] = page_start
        return {
            "content": item["text"],
            "score": item["score"],
            "score_type": item.get("score_type", "unknown"),
            "metadata": metadata,
            "asset_id": item["asset_id"],
            "chunk_index": item["chunk_index"],
            "sources": item.get("sources", []),
        }

    async def list_collections(self) -> list[dict[str, Any]]:
        return await self._rag.list_collections()

    async def delete_collection(self, name: str) -> bool:
        return await self._rag.delete_collection(name)

    async def delete_asset(self, collection: str, asset_id: str) -> bool:
        return await self._rag.delete_asset(collection, asset_id)

    async def get_collection_count(self, name: str | None = None) -> int:
        return await self._rag.get_collection_count(name or settings.chroma_collection_name)


hybrid_vector_store_service = HybridVectorStoreService()

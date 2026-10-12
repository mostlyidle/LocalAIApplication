from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from qdrant_client import AsyncQdrantClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.registry import AgentExecution, AgentRegistry
from app.models.db_models import RagCollection
from app.models.profile_schemas import TaskRequest
from app.prompt_store import PromptStore
from app.services.hybrid_vector_store import HybridVectorStoreService
from app.services.rag_context import prepare_rag_context
from app.services.rag_store import RagCollectionConflictError, RagStore
from tests.test_services.test_hybrid_rag import FakeBm25Encoder


def profiles():
    directory = Path(__file__).resolve().parents[2] / "app" / "prompts"
    prompts = PromptStore(directory)
    return AgentRegistry(directory, prompts), prompts


async def test_rag_budgets_full_evidence_and_history_before_generation() -> None:
    registry, prompts = profiles()
    request = TaskRequest(prompt="When?", agent_name="rag", inference={"context_window": 1024, "max_output_tokens": 64})
    profile = registry.get("rag")
    execution = AgentExecution(profile, registry.resolve_inference(profile, request))
    search = SimpleNamespace(
        passages=[{"content": text, "metadata": {"asset_id": "guide", "chunk_index": i, "source": "guide.txt"}}
                  for i, text in enumerate(["Friday.", "oversized " * 500, "Monday."])],
        retrieval={},
    )
    with patch("app.services.hybrid_vector_store.hybrid_vector_store_service.search_with_provenance", AsyncMock(return_value=search)) as retrieve:
        context = await prepare_rag_context(request, execution, prompts, history=["old " * 1000])
    system, user = prompts.render_messages("rag", "rag", context.prompt_values)
    assert len(system.encode()) + len(user.encode()) + 64 <= int(1024 * 0.7)
    assert [citation["chunk_index"] for citation in context.citations] == [0, 2]
    assert "[guide:0]" in user and "[guide:2]" in user
    assert "[guide:1]" not in user and "old" not in user
    assert "When?" in user and context.limitations
    assert retrieve.call_args.kwargs["query"] == "When?"
    assert retrieve.call_args.kwargs["rewrite_model"] == execution.inference.model


async def test_rag_rejects_context_that_cannot_hold_one_complete_passage() -> None:
    registry, prompts = profiles()
    request = TaskRequest(prompt="When?", agent_name="rag", inference={"context_window": 512, "max_output_tokens": 64})
    profile = registry.get("rag")
    execution = AgentExecution(profile, registry.resolve_inference(profile, request))
    search = SimpleNamespace(passages=[{"content": "evidence " * 1000}], retrieval={})
    with patch("app.services.hybrid_vector_store.hybrid_vector_store_service.search_with_provenance", AsyncMock(return_value=search)):
        with pytest.raises(HTTPException) as error:
            await prepare_rag_context(request, execution, prompts)
    assert error.value.status_code == 422
    assert "Increase" in error.value.detail


async def test_rag_context_rejects_another_accounts_collection(
    db_session: AsyncSession, async_engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, prompts = profiles()
    db_session.add(RagCollection(name="private-rag", owner_id="another-account"))
    await db_session.commit()
    maker = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("app.services.database.get_app_session_factory", lambda: maker)

    request = TaskRequest(prompt="private?", agent_name="rag", collection="private-rag")
    profile = registry.get("rag")
    execution = AgentExecution(profile, registry.resolve_inference(profile, request))
    with pytest.raises(HTTPException) as error:
        await prepare_rag_context(request, execution, prompts, owner_id="current-account")
    assert error.value.status_code == 404


@pytest.mark.parametrize("model, revision, succeeds, historical", [
    ("nomic-embed-text", "nomic-embed-text-v1", True, True),
    ("nomic-embed-text:latest", "nomic-embed-text-v1:digest:plain-v1", True, False),
    ("nomic-embed-text:latest", "nomic-embed-text-v1:other:plain-v1", False, False),
    ("other-model", "nomic-embed-text-v1", False, False),
])
async def test_source_collection_queries_preserve_contract_and_write_guards(
    monkeypatch, model: str, revision: str, succeeds: bool, historical: bool
) -> None:
    registry, _ = profiles()
    store = RagStore("http://unused", client=AsyncQdrantClient(location=":memory:"), bm25_encoder=FakeBm25Encoder())
    service = HybridVectorStoreService.__new__(HybridVectorStoreService)
    service._rag = store
    service._profiles = registry
    monkeypatch.setattr("app.services.hybrid_vector_store.settings.ollama_embedding_dimension", 2)
    identity = {"embedding_model": "nomic-embed-text:latest", "embedding_digest": "digest", "embedding_profile": "plain-v1"}
    try:
        await store.upsert(collection="source", chunks=["Evidence"], embeddings=[[1.0, 0.0]], asset_id="doc", dense_model=model, embedding_revision=revision, language="english")
        with (
            patch("app.services.hybrid_vector_store.embedding_service.get_identity", AsyncMock(return_value=identity)),
            patch("app.services.hybrid_vector_store.embedding_service.embed_text", AsyncMock(return_value=[1.0, 0.0])),
            patch("app.services.hybrid_vector_store.embedding_service.embed_texts", AsyncMock(return_value=[[1.0, 0.0]])),
        ):
            if succeeds:
                result = await service.search_with_provenance(query="Evidence", collection="source", top_k=5)
                assert result.passages[0]["content"] == "Evidence"
                assert result.retrieval["recorded_identity_only"] == historical
            else:
                with pytest.raises(RagCollectionConflictError):
                    await service.search_with_provenance(query="Evidence", collection="source", top_k=5)
            if historical:
                with pytest.raises(RagCollectionConflictError):
                    await service.add_documents(["Replacement"], [{"document_id": "doc"}], ["doc_0"], collection="source")
        capabilities = await store.capabilities("source")
        assert capabilities.dense_model == model and capabilities.embedding_revision == revision
        assert await store.get_collection_count("source") == 1
    finally:
        await store.close()


async def test_rewrite_uses_selected_generation_model() -> None:
    registry, _ = profiles()
    service = HybridVectorStoreService.__new__(HybridVectorStoreService)
    service._profiles = registry
    service._prompt_dir = Path(__file__).resolve().parents[2] / "app" / "prompts"
    model = SimpleNamespace(with_structured_output=lambda schema: SimpleNamespace(ainvoke=AsyncMock(return_value={"queries": ["First query", "Second query"]})))
    with patch.object(service, "_chat_model", return_value=model) as build:
        queries, failure = await service._rewrite_queries("Original", "rag_v2", 2, 96, model="llama3.2:3b")
    assert queries == ["First query", "Second query"] and failure is None
    assert build.call_args.kwargs["model"] == "llama3.2:3b"

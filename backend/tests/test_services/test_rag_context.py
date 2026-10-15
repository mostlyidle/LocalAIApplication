from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from qdrant_client import AsyncQdrantClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.agents.registry import AgentExecution, AgentRegistry
from app.api.middleware.error_handler import NotFoundError
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


async def test_rag_omits_oversized_memory_before_document_evidence() -> None:
    registry, prompts = profiles()
    request = TaskRequest(
        prompt="When?", agent_name="rag", inference={"context_window": 1024, "max_output_tokens": 64}
    )
    profile = registry.get("rag")
    execution = AgentExecution(profile, registry.resolve_inference(profile, request))
    search = SimpleNamespace(
        passages=[
            {"content": "The deadline is Friday.", "metadata": {"asset_id": "guide", "chunk_index": 0}}
        ],
        retrieval={},
    )
    memory = '[{"type":"past_conversation","conversation_id":"old-chat","title":"Old chat","content":"' + "personal context " * 500 + '"}]'

    with patch(
        "app.services.hybrid_vector_store.hybrid_vector_store_service.search_with_provenance",
        AsyncMock(return_value=search),
    ):
        context = await prepare_rag_context(
            request, execution, prompts, memory_context=memory
        )

    assert context.memory_context == ""
    assert context.citations[0]["asset_id"] == "guide"
    assert "Friday" in context.prompt_values["passages"]
    assert any("Personal memory was omitted" in item for item in context.limitations)


async def test_rag_context_budget_includes_saved_system_prompt() -> None:
    registry, prompts = profiles()
    request = TaskRequest(
        prompt="When?", agent_name="rag", inference={"context_window": 1024, "max_output_tokens": 64}
    )
    profile = registry.get("rag")
    execution = AgentExecution(profile, registry.resolve_inference(profile, request))
    search = SimpleNamespace(passages=[{"content": "Friday."}], retrieval={})

    with (
        patch(
            "app.services.hybrid_vector_store.hybrid_vector_store_service.search_with_provenance",
            AsyncMock(return_value=search),
        ),
        pytest.raises(HTTPException, match="context budget"),
    ):
        await prepare_rag_context(
            request,
            execution,
            prompts,
            system_prompt="Saved instruction " * 200,
        )


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


async def test_hybrid_search_rejects_another_accounts_collection(
    db_session: AsyncSession,
    async_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_session.add(RagCollection(name="private-rag", owner_id="another-account"))
    await db_session.commit()
    maker = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("app.services.database.get_app_session_factory", lambda: maker)
    service = HybridVectorStoreService.__new__(HybridVectorStoreService)

    with pytest.raises(NotFoundError):
        await service.search(
            query="private?", collection="private-rag", owner_id="current-account"
        )


async def test_hybrid_search_uses_configured_custom_rag_profile() -> None:
    prompt_dir = Path(__file__).resolve().parents[2] / "app" / "prompts"
    prompts = PromptStore(prompt_dir)
    registry = AgentRegistry(prompt_dir, prompts)
    source = registry.get("rag_v2")
    assert source is not None
    custom = source.model_copy(
        update={"name": "saved_rag", "description": "Saved RAG", "default_for_target": False}
    )
    registry.apply_configurations(
        [
            SimpleNamespace(
                name="saved_rag",
                display_name="Saved RAG",
                target="rag",
                description="Saved RAG",
                system_prompt="Use the saved RAG instructions.",
                base_agent="rag_v2",
                manifest_json=custom.model_dump_json(),
                is_custom=True,
                archived=False,
            )
        ]
    )
    service = HybridVectorStoreService.__new__(HybridVectorStoreService)
    service._prompt_dir = prompt_dir
    service._profiles = None
    service._prompts = None
    service._rag = SimpleNamespace(capabilities=AsyncMock(return_value=None))
    rewrite = AsyncMock(return_value={"queries": ["First rewrite", "Second rewrite"]})
    llm = SimpleNamespace(
        with_structured_output=lambda _schema: SimpleNamespace(
            ainvoke=rewrite
        )
    )

    service.configure_profiles(registry, prompts)
    with patch.object(service, "_chat_model", return_value=llm):
        result = await service.search_with_provenance(
            query="Original question",
            collection="missing",
            top_k=3,
            agent_name="saved_rag",
        )

    rewrite_prompt = rewrite.call_args.args[0]
    assert result.retrieval["mode"] == "missing_collection"
    assert "You rewrite retrieval queries for a grounded RAG system." in rewrite_prompt
    assert "Original question" in rewrite_prompt


@pytest.mark.parametrize(
    ("mode", "expected_applied", "expected_rewrite_call"),
    [("enforce", True, False), ("observe", False, True), ("off", False, True)],
)
async def test_laya_rewrite_gate_only_skips_when_enforcement_is_approved(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    expected_applied: bool,
    expected_rewrite_call: bool,
) -> None:
    registry, prompts = profiles()
    service = HybridVectorStoreService.__new__(HybridVectorStoreService)
    service._prompt_dir = Path(__file__).resolve().parents[2] / "app" / "prompts"
    service._profiles = registry
    service._prompts = prompts
    service._rag = SimpleNamespace(capabilities=AsyncMock(return_value=None))
    decision = SimpleNamespace(
        check="rewrite",
        choice="skip",
        probability=0.96,
        probabilities={"skip": 0.96, "run": 0.02, "uncertain": 0.02},
        elapsed_ms=12.0,
        schema_version="rewrite-v1",
        reason="evaluated",
    )
    laya = SimpleNamespace(
        check_rewrite=AsyncMock(return_value=decision),
        can_apply=lambda *_args, **_kwargs: (True, "threshold_met"),
        model_digest="installed-digest",
    )
    service.configure_laya_service(laya)
    rewrite = AsyncMock(return_value=(['First rewrite', 'Second rewrite'], None))
    monkeypatch.setattr("app.services.hybrid_vector_store.settings.laya_rag_rewrite_mode", mode)
    with patch.object(service, "_rewrite_queries", rewrite):
        result = await service.search_with_provenance(
            query="A specific question",
            collection="missing",
            top_k=3,
            agent_name="rag_v2",
        )

    assert rewrite.await_count == int(expected_rewrite_call)
    assert laya.check_rewrite.await_count == int(mode != "off")
    assert result.retrieval["laya"]["rewrite"]["applied"] is expected_applied
    assert result.retrieval["laya"]["rewrite"]["mode"] == mode


async def test_laya_rewrite_skip_embeds_original_query_only_and_zeros_rewrite_weight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.fastembed_queries import (
        LOADER_EMBEDDING_MODEL,
        LOADER_EMBEDDING_REVISION,
    )

    registry, prompts = profiles()
    service = HybridVectorStoreService.__new__(HybridVectorStoreService)
    service._prompt_dir = Path(__file__).resolve().parents[2] / "app" / "prompts"
    service._profiles = registry
    service._prompts = prompts
    service._loader_queries = SimpleNamespace(embed=AsyncMock(return_value=[[0.1, 0.2]]))
    service._rag = SimpleNamespace(
        capabilities=AsyncMock(
            return_value=SimpleNamespace(
                loader_owned=True,
                dense_model=LOADER_EMBEDDING_MODEL,
                embedding_revision=LOADER_EMBEDDING_REVISION,
            )
        ),
        search=AsyncMock(return_value=SimpleNamespace(passages=[], retrieval={"mode": "hybrid_rrf"})),
    )
    decision = SimpleNamespace(
        check="rewrite", choice="skip", probability=0.96,
        probabilities={"skip": 0.96, "run": 0.02, "uncertain": 0.02},
        elapsed_ms=12.0, schema_version="rewrite-v1", reason="evaluated",
    )
    service.configure_laya_service(
        SimpleNamespace(
            check_rewrite=AsyncMock(return_value=decision),
            can_apply=lambda *_args, **_kwargs: (True, "threshold_met"),
            model_digest="installed-digest",
        )
    )
    monkeypatch.setattr("app.services.hybrid_vector_store.settings.laya_rag_rewrite_mode", "enforce")

    await service.search_with_provenance(
        query="A specific question",
        collection="available",
        top_k=3,
        agent_name="rag_v2",
    )

    service._loader_queries.embed.assert_awaited_once_with(["A specific question"])
    search_kwargs = service._rag.search.call_args.kwargs
    assert search_kwargs["rewrite_embeddings"] == []
    assert search_kwargs["rewrite_queries"] == []
    assert search_kwargs["rewrite_dense_total_weight"] == 0


async def test_laya_rewrite_gate_does_not_run_for_profiles_without_rewrites(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, prompts = profiles()
    service = HybridVectorStoreService.__new__(HybridVectorStoreService)
    service._prompt_dir = Path(__file__).resolve().parents[2] / "app" / "prompts"
    service._profiles = registry
    service._prompts = prompts
    service._rag = SimpleNamespace(capabilities=AsyncMock(return_value=None))
    laya = SimpleNamespace(check_rewrite=AsyncMock())
    service.configure_laya_service(laya)
    rewrite = AsyncMock(return_value=([], None))
    monkeypatch.setattr("app.services.hybrid_vector_store.settings.laya_rag_rewrite_mode", "enforce")

    with patch.object(service, "_rewrite_queries", rewrite):
        result = await service.search_with_provenance(
            query="A specific question",
            collection="missing",
            top_k=3,
            agent_name="rag",
        )

    laya.check_rewrite.assert_not_awaited()
    rewrite.assert_not_awaited()
    assert result.retrieval["laya"]["rewrite"]["reason"] == "profile_has_no_rewrites"


async def test_laya_evidence_override_uses_all_final_bounded_passages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, prompts = profiles()
    profile = registry.get("rag")
    request = TaskRequest(
        prompt="What is the warranty duration?",
        agent_name="rag",
        inference={"context_window": 4096, "max_output_tokens": 128},
    )
    execution = AgentExecution(profile, registry.resolve_inference(profile, request))
    passages = [
        {
            "content": "A payment methods overview.",
            "metadata": {"asset_id": "policy", "chunk_index": 0, "filename": "policy.pdf"},
        },
        {
            "content": "A later section lists unrelated service contacts.",
            "metadata": {"asset_id": "policy", "chunk_index": 1, "filename": "policy.pdf"},
        },
    ]
    search = SimpleNamespace(passages=passages, retrieval={"mode": "hybrid_rrf"})
    decision = SimpleNamespace(
        check="evidence", choice="unsupported", probability=0.97,
        probabilities={"supported": 0.01, "unsupported": 0.97, "uncertain": 0.02},
        elapsed_ms=15.0, input_bytes=600, schema_version="evidence-v1", reason="evaluated",
    )
    checked: dict[str, object] = {}

    def can_apply(_check: str, **kwargs: object) -> tuple[bool, str]:
        checked.update(kwargs)
        return True, "threshold_met"

    laya = SimpleNamespace(
        check_evidence=AsyncMock(return_value=decision),
        can_apply=can_apply,
        model_digest="installed-digest",
    )
    monkeypatch.setattr("app.services.hybrid_vector_store.settings.laya_rag_evidence_mode", "enforce")
    with (
        patch(
            "app.services.hybrid_vector_store.hybrid_vector_store_service.search_with_provenance",
            AsyncMock(return_value=search),
        ),
        patch("app.services.hybrid_vector_store.hybrid_vector_store_service._laya", laya),
    ):
        context = await prepare_rag_context(request, execution, prompts)

    laya.check_evidence.assert_awaited_once_with(
        request.prompt, [context.prompt_values["passages"]]
    )
    assert "A payment methods overview." in context.prompt_values["passages"]
    assert "A later section lists unrelated service contacts." in context.prompt_values["passages"]
    assert checked["context_independent"] is True
    assert context.answer_override == (
        "I couldn't find enough supporting evidence in the retrieved passages to answer this question."
    )
    assert context.citations == []
    evidence_meta = context.retrieval["laya"]["evidence"]
    assert evidence_meta["candidate_citations"][1]["chunk_index"] == 1
    assert evidence_meta["coverage"]["submitted_complete"] is True


async def test_laya_evidence_does_not_run_when_retrieval_has_no_passages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, prompts = profiles()
    request = TaskRequest(prompt="What is the warranty duration?", agent_name="rag")
    profile = registry.get("rag")
    execution = AgentExecution(profile, registry.resolve_inference(profile, request))
    laya = SimpleNamespace(check_evidence=AsyncMock())
    monkeypatch.setattr("app.services.hybrid_vector_store.settings.laya_rag_evidence_mode", "enforce")
    with (
        patch(
            "app.services.hybrid_vector_store.hybrid_vector_store_service.search_with_provenance",
            AsyncMock(return_value=SimpleNamespace(passages=[], retrieval={"mode": "hybrid_rrf"})),
        ),
        patch("app.services.hybrid_vector_store.hybrid_vector_store_service._laya", laya),
    ):
        context = await prepare_rag_context(request, execution, prompts)

    laya.check_evidence.assert_not_awaited()
    assert context.answer_override is None
    assert context.retrieval["laya"]["evidence"]["reason"] == "no_evidence"
    assert context.retrieval["laya"]["evidence"]["applied"] is False


async def test_laya_evidence_observes_with_the_default_explicit_system_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, prompts = profiles()
    request = TaskRequest(
        prompt="What is the warranty duration?",
        agent_name="rag",
        inference={"context_window": 4096, "max_output_tokens": 128},
    )
    profile = registry.get("rag")
    execution = AgentExecution(profile, registry.resolve_inference(profile, request))
    search = SimpleNamespace(passages=[{"content": "Payment methods."}], retrieval={})
    decision = SimpleNamespace(
        choice="unsupported",
        probability=0.97,
        elapsed_ms=15.0,
        input_bytes=300,
        schema_version="evidence-v1",
        reason="evaluated",
    )
    laya = SimpleNamespace(
        check_evidence=AsyncMock(return_value=decision),
        can_apply=lambda *_args, **_kwargs: (False, "prompt_unverified"),
        model_digest="installed-digest",
    )
    monkeypatch.setattr("app.services.hybrid_vector_store.settings.laya_rag_evidence_mode", "enforce")
    with (
        patch(
            "app.services.hybrid_vector_store.hybrid_vector_store_service.search_with_provenance",
            AsyncMock(return_value=search),
        ),
        patch("app.services.hybrid_vector_store.hybrid_vector_store_service._laya", laya),
    ):
        context = await prepare_rag_context(
            request,
            execution,
            prompts,
            system_prompt=prompts.system_prompt(profile.name, "rag"),
        )

    laya.check_evidence.assert_awaited_once()
    assert context.answer_override is None
    assert context.retrieval["laya"]["evidence"]["reason"] == "prompt_unverified"


async def test_laya_evidence_does_not_suppress_context_dependent_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, prompts = profiles()
    request = TaskRequest(
        prompt="What about the warranty?",
        agent_name="rag",
        inference={"context_window": 4096, "max_output_tokens": 128},
    )
    profile = registry.get("rag")
    execution = AgentExecution(profile, registry.resolve_inference(profile, request))
    search = SimpleNamespace(passages=[{"content": "Payment methods."}], retrieval={})
    decision = SimpleNamespace(
        check="evidence", choice="unsupported", probability=0.97,
        probabilities={"supported": 0.01, "unsupported": 0.97, "uncertain": 0.02},
        elapsed_ms=15.0, input_bytes=300, schema_version="evidence-v1", reason="evaluated",
    )
    laya = SimpleNamespace(
        check_evidence=AsyncMock(return_value=decision),
        can_apply=lambda *_args, **_kwargs: (True, "threshold_met"),
        model_digest="installed-digest",
    )
    monkeypatch.setattr("app.services.hybrid_vector_store.settings.laya_rag_evidence_mode", "enforce")
    with (
        patch(
            "app.services.hybrid_vector_store.hybrid_vector_store_service.search_with_provenance",
            AsyncMock(return_value=search),
        ),
        patch("app.services.hybrid_vector_store.hybrid_vector_store_service._laya", laya),
    ):
        context = await prepare_rag_context(
            request,
            execution,
            prompts,
            history=["Earlier turn: Tell me about this warranty."],
            memory_context="A saved preference.",
        )

    laya.check_evidence.assert_not_awaited()
    assert context.answer_override is None
    assert context.citations
    assert context.memory_context == "A saved preference."


async def test_laya_evidence_negative_triggers_one_rewrite_rescue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, prompts = profiles()
    request = TaskRequest(
        prompt="What is the warranty duration?",
        agent_name="rag_v2",
        inference={"context_window": 4096, "max_output_tokens": 128},
    )
    profile = registry.get("rag_v2")
    execution = AgentExecution(profile, registry.resolve_inference(profile, request))
    initial = SimpleNamespace(
        passages=[{"content": "Initial unrelated passage."}],
        retrieval={
            "skipped_by_laya": True,
            "laya": {"rewrite": {"applied": True}},
        },
    )
    rescued = SimpleNamespace(
        passages=[
            {
                "content": "Warranty coverage lasts 24 months.",
                "metadata": {"asset_id": "terms", "chunk_index": 4},
            }
        ],
        retrieval={"skipped_by_laya": False, "laya": {"rewrite": {"reason": "rescue_retrieval"}}},
    )
    search = AsyncMock(side_effect=[initial, rescued])
    decision = SimpleNamespace(
        check="evidence", choice="unsupported", probability=0.97,
        probabilities={"supported": 0.01, "unsupported": 0.97, "uncertain": 0.02},
        elapsed_ms=15.0, input_bytes=300, schema_version="evidence-v1", reason="evaluated",
    )
    laya = SimpleNamespace(
        check_evidence=AsyncMock(return_value=decision),
        can_apply=lambda *_args, **_kwargs: (True, "threshold_met"),
        model_digest="installed-digest",
    )
    monkeypatch.setattr("app.services.hybrid_vector_store.settings.laya_rag_evidence_mode", "enforce")
    with (
        patch(
            "app.services.hybrid_vector_store.hybrid_vector_store_service.search_with_provenance",
            search,
        ),
        patch("app.services.hybrid_vector_store.hybrid_vector_store_service._laya", laya),
    ):
        context = await prepare_rag_context(request, execution, prompts)

    assert search.await_count == 2
    assert search.await_args_list[1].kwargs["_bypass_laya_rewrite"] is True
    laya.check_evidence.assert_awaited_once()
    assert context.answer_override is None
    assert len(context.citations) == 1
    evidence_meta = context.retrieval["laya"]["evidence"]
    assert evidence_meta["rescue"]["triggered"] is True
    assert evidence_meta["rescue"]["passages"] == 1


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

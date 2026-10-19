from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.agents.registry import AgentRegistry
from app.models.profile_schemas import InferenceOptions, TaskRequest
from app.prompt_store import PromptStore


@pytest.fixture
def registry() -> AgentRegistry:
    prompt_dir = Path(__file__).resolve().parents[2] / "app" / "prompts"
    return AgentRegistry(prompt_dir, PromptStore(prompt_dir))


def test_catalog_has_a_default_for_every_agent_domain(registry: AgentRegistry) -> None:
    catalog = registry.capabilities()
    targets = {agent.target for agent in catalog.agents}

    assert targets == {
        "chat",
        "sql",
        "document",
        "rag",
        "web",
        "image_analysis",
        "image_fraud",
        "stock_research",
        "software_engineer",
        "image_generation",
        "document_redaction",
    }
    assert {agent.name for agent in catalog.agents} >= {"rag", "rag_v2"}


def test_redaction_profile_uses_its_dedicated_local_workflow(registry: AgentRegistry) -> None:
    profile = registry.default_for("document_redaction")

    assert profile.name == "document_redaction"
    assert profile.inference is None


def test_rag_v2_prompt_and_retrieval_profile_load(registry: AgentRegistry) -> None:
    profile = registry.get("rag_v2")
    assert profile is not None
    assert profile.retrieval is not None
    assert profile.retrieval.query_rewrite.count == 2

    prompt_dir = Path(__file__).resolve().parents[2] / "app" / "prompts"
    prompt_store = PromptStore(prompt_dir)
    system, prompt = prompt_store.render_messages_for(
        "rag_v2", "rag", "rewrite", {"prompt": "What risks?", "rewrite_count": 2}
    )
    assert "rewrite" in system.lower() or "query" in system.lower()
    assert "What risks?" in prompt


def test_render_messages_uses_saved_system_prompt_override() -> None:
    prompt_dir = Path(__file__).resolve().parents[2] / "app" / "prompts"
    prompt_store = PromptStore(prompt_dir)
    prompt_store.set_system_override("rag", "rag", "  Answer in one sentence.  ")

    system, user = prompt_store.render_messages(
        "rag", "rag", {"prompt": "Question?", "history": "", "passages": "Evidence."}
    )

    assert system == "Answer in one sentence."
    assert "Question: Question?" in user
    assert "Evidence." in user


def test_profile_model_and_override_limits_are_enforced(registry: AgentRegistry) -> None:
    profile = registry.get("rag")
    assert profile is not None

    with pytest.raises(ValueError, match="not approved"):
        registry.resolve_inference(
            profile,
            TaskRequest(
                prompt="Search the collection.",
                agent_name="rag",
                inference=InferenceOptions(model="unapproved-model:latest"),
            ),
        )

    with pytest.raises(ValueError, match="temperature"):
        strict_profile = registry.get("rag_v2")
        assert strict_profile is not None
        registry.resolve_inference(
            strict_profile,
            TaskRequest(
                prompt="Search the collection.",
                agent_name="rag_v2",
                inference=InferenceOptions(temperature=1.5),
            ),
        )


def test_missing_or_malformed_prompt_configuration_fails(tmp_path: Path) -> None:
    prompts = tmp_path / "chat" / "chat"
    prompts.mkdir(parents=True)
    (prompts / "agent.json").write_text(
        '{"schema_version":1,"name":"chat","target":"chat"}', encoding="utf-8"
    )

    with pytest.raises(ValueError, match="Invalid agent manifest"):
        AgentRegistry(tmp_path, PromptStore(tmp_path))


def test_custom_profile_uses_saved_prompt_and_source_user_template(registry: AgentRegistry) -> None:
    source = registry.get("chat")
    assert source is not None
    custom = source.model_copy(
        update={
            "name": "concise_helper",
            "description": "A concise assistant",
            "default_for_target": False,
        }
    )
    config = SimpleNamespace(
        name="concise_helper",
        display_name="Concise Helper",
        target="chat",
        description=custom.description,
        system_prompt="Use short sentences.",
        base_agent="chat",
        manifest_json=custom.model_dump_json(),
        is_custom=True,
        archived=False,
    )

    registry.apply_configurations([config])

    assert registry.get("concise_helper") == custom
    assert registry.system_prompt("concise_helper") == "Use short sentences."
    custom_capability = next(
        agent for agent in registry.capabilities().agents if agent.name == "concise_helper"
    )
    assert custom_capability.display_name == "Concise Helper"

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.models.profile_schemas import (
    ModelName,
    ResolvedInferenceOptions,
    RoutableTarget,
    TaskRequest,
)
from app.prompt_store import PromptStore, PromptTemplateError

if TYPE_CHECKING:
    from pathlib import Path

INFERENCE_TARGETS: set[RoutableTarget] = {
    "chat",
    "sql",
    "document",
    "spreadsheet",
    "rag",
    "web",
    "image_analysis",
    "stock_research",
    "software_engineer",
}


class AgentCatalogError(ValueError):
    """Raised when the configured agent catalog is internally inconsistent."""


class NumericLimit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    minimum: float
    maximum: float

    @model_validator(mode="after")
    def validate_order(self) -> NumericLimit:
        if self.minimum > self.maximum:
            raise ValueError("minimum must not exceed maximum")
        return self


class IntegerLimit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    minimum: int
    maximum: int

    @model_validator(mode="after")
    def validate_order(self) -> IntegerLimit:
        if self.minimum > self.maximum:
            raise ValueError("minimum must not exceed maximum")
        return self


class InferenceLimits(BaseModel):
    model_config = ConfigDict(extra="forbid")

    temperature: NumericLimit
    max_output_tokens: IntegerLimit
    context_window: IntegerLimit
    seed: IntegerLimit
    top_p: NumericLimit
    top_k: IntegerLimit
    repeat_penalty: NumericLimit
    max_stop_sequences: int = Field(ge=0, le=8)
    max_stop_length: int = Field(ge=1, le=128)


class InferenceManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_model: ModelName
    allowed_models: list[ModelName] = Field(min_length=1)
    defaults: ResolvedInferenceOptions
    limits: InferenceLimits

    @model_validator(mode="after")
    def validate_models(self) -> InferenceManifest:
        if len(self.allowed_models) != len(set(self.allowed_models)):
            raise ValueError("allowed_models must not contain duplicates")
        if self.default_model not in self.allowed_models:
            raise ValueError("default_model must be present in allowed_models")
        if self.defaults.model != self.default_model:
            raise ValueError("defaults.model must match default_model")
        return self


class RetrievalWeights(BaseModel):
    model_config = ConfigDict(extra="forbid")

    original_dense: float = Field(gt=0, le=10)
    original_bm25: float = Field(gt=0, le=10)
    rewrite_dense_total: float = Field(default=1.0, ge=0, le=10)


class QueryRewriteManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    count: int = Field(ge=0, le=4)
    max_output_tokens: int = Field(default=256, ge=32, le=512)


class RetrievalManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy: Literal["hybrid_rrf"]
    candidate_limit: int = Field(ge=1, le=200)
    result_limit: int = Field(ge=1, le=50)
    rrf_k: int = Field(ge=1, le=1_000)
    weights: RetrievalWeights
    query_rewrite: QueryRewriteManifest

    @model_validator(mode="after")
    def validate_retrieval(self) -> RetrievalManifest:
        if self.candidate_limit < self.result_limit:
            raise ValueError("candidate_limit must be at least result_limit")
        if self.query_rewrite.count == 0 and self.weights.rewrite_dense_total != 0:
            raise ValueError("rewrite_dense_total must be zero when query_rewrite.count is zero")
        if self.query_rewrite.count > 0 and self.weights.rewrite_dense_total == 0:
            raise ValueError("rewrite_dense_total must be positive when query rewrites are enabled")
        return self


class AgentManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1, 2]
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,62}$")
    target: RoutableTarget
    description: str = Field(min_length=1, max_length=500)
    enabled: bool = True
    default_for_target: bool = False
    inference: InferenceManifest | None = None
    retrieval: RetrievalManifest | None = None


class AgentCapability(BaseModel):
    name: str
    display_name: str
    target: RoutableTarget
    description: str
    default_for_target: bool
    system_prompt: str
    is_custom: bool = False
    archived: bool = False
    inference: InferenceManifest | None
    retrieval: RetrievalManifest | None
    model_availability: dict[str, bool | None] = Field(default_factory=dict)


class AgentCatalogResponse(BaseModel):
    agents: list[AgentCapability]


@dataclass(frozen=True)
class AgentExecution:
    profile: AgentManifest
    inference: ResolvedInferenceOptions | None


class AgentRegistry:
    """Validated catalog of configured prompt-backed agent profiles."""

    def __init__(self, prompt_dir: Path, prompts: PromptStore) -> None:
        self._prompt_dir = prompt_dir
        self._prompts = prompts
        self._base_agents = self._load()
        self._agents = dict(self._base_agents)
        self._display_names = {name: name.replace("_", " ").title() for name in self._agents}
        self._custom_names: set[str] = set()
        self._archived_names: set[str] = set()
        self._base_profiles: dict[str, str] = {}
        self._apply_defaults()

    def _apply_defaults(self) -> None:
        self._defaults = {
            agent.target: agent
            for agent in self._agents.values()
            if agent.enabled and agent.default_for_target
        }

    def get(self, agent_name: str, *, include_archived: bool = False) -> AgentManifest | None:
        agent = self._agents.get(agent_name)
        return (
            agent
            if agent
            and agent.enabled
            and (include_archived or agent_name not in self._archived_names)
            else None
        )

    def default_for(self, target: RoutableTarget) -> AgentManifest:
        return self._defaults[target]

    def capabilities(self, *, include_archived: bool = False) -> AgentCatalogResponse:
        agents = [
            AgentCapability(
                name=agent.name,
                display_name=self._display_names.get(agent.name, agent.name),
                target=agent.target,
                description=agent.description,
                default_for_target=agent.default_for_target,
                system_prompt=self.system_prompt(agent.name),
                is_custom=agent.name in self._custom_names,
                archived=agent.name in self._archived_names,
                inference=agent.inference,
                retrieval=agent.retrieval,
            )
            for agent in self._agents.values()
            if include_archived or (agent.enabled and agent.name not in self._archived_names)
        ]
        agents.sort(key=lambda agent: (agent.target, agent.name))
        return AgentCatalogResponse(agents=agents)

    def system_prompt(self, agent_name: str) -> str:
        """Return the resolved system prompt for an agent profile."""
        agent = self._agents[agent_name]
        return self._prompts.system_prompt(agent.name, agent.target)

    def default_system_prompts(self) -> dict[str, str]:
        """Return system prompts for the default profile in each agent domain."""
        return {
            target: self.system_prompt(profile.name)
            for target, profile in self._defaults.items()
        }

    def prompt_source(self, agent_name: str) -> str:
        """Return the built-in profile from which an agent was derived."""
        return self._base_profiles.get(agent_name, agent_name)

    def apply_configurations(self, configurations: list[object]) -> None:
        """Apply persisted installation-wide prompt edits and custom profiles."""
        self._agents = dict(self._base_agents)
        self._display_names = {
            name: name.replace("_", " ").title() for name in self._agents
        }
        self._custom_names = set()
        self._archived_names = set()
        self._base_profiles = {}
        self._prompts.clear_overrides()

        for config in configurations:
            name = config.name
            if not config.is_custom:
                if name not in self._agents:
                    continue
                if config.target != self._agents[name].target:
                    raise AgentCatalogError(f"Saved configuration for '{name}' has the wrong target.")
                self._display_names[name] = config.display_name
                self._prompts.set_system_override(name, config.target, config.system_prompt)
                continue

            try:
                profile = AgentManifest.model_validate_json(config.manifest_json)
            except (ValidationError, TypeError) as exc:
                raise AgentCatalogError(f"Invalid saved custom profile '{name}'.") from exc
            if profile.name != name or profile.target != config.target or profile.default_for_target:
                raise AgentCatalogError(f"Invalid saved custom profile '{name}'.")
            base_agent = config.base_agent
            if (
                base_agent not in self._base_agents
                or self._base_agents[base_agent].target != profile.target
                or profile.target not in INFERENCE_TARGETS
            ):
                raise AgentCatalogError(f"Custom profile '{name}' has an invalid source agent.")
            if name in self._agents:
                raise AgentCatalogError(f"Custom profile '{name}' conflicts with a built-in agent.")
            self._agents[name] = profile.model_copy(
                update={"description": config.description, "enabled": True}
            )
            self._display_names[name] = config.display_name
            self._custom_names.add(name)
            self._base_profiles[name] = base_agent
            self._prompts.set_system_override(name, config.target, config.system_prompt)
            if config.archived:
                self._archived_names.add(name)

        for config in configurations:
            if config.is_custom:
                self._prompts.set_source(config.name, config.target, self._base_profiles[config.name])

        self._apply_defaults()

    def resolve_inference(
        self, agent: AgentManifest, request: TaskRequest
    ) -> ResolvedInferenceOptions | None:
        overrides = request.inference_overrides()
        if agent.inference is None:
            if request.inference is not None or request.model is not None:
                raise ValueError(f"agent_name '{agent.name}' does not support inference settings")
            return None

        values = agent.inference.defaults.model_dump()
        if overrides:
            values.update(overrides)
        resolved = ResolvedInferenceOptions.model_validate(values)
        self._validate_inference(agent, resolved)
        return resolved

    def _load(self) -> dict[str, AgentManifest]:
        manifests: list[AgentManifest] = []
        manifest_paths = sorted(self._prompt_dir.glob("*/*/agent.json"))
        if not manifest_paths:
            raise AgentCatalogError(f"No agent manifests were found in {self._prompt_dir}.")
        for path in manifest_paths:
            try:
                manifest = AgentManifest.model_validate_json(path.read_text(encoding="utf-8"))
            except (OSError, ValidationError) as exc:
                raise AgentCatalogError(f"Invalid agent manifest '{path}': {exc}") from exc
            target_dir, agent_dir = path.parent.parent.name, path.parent.name
            if manifest.target != target_dir or manifest.name != agent_dir:
                raise AgentCatalogError(
                    f"Agent manifest '{path}' must match its target and profile directory names."
                )
            if (manifest.inference is not None) != (manifest.target in INFERENCE_TARGETS):
                raise AgentCatalogError(
                    f"Agent manifest '{path}' has an incompatible inference configuration."
                )
            if manifest.target == "rag":
                if manifest.schema_version != 2 or manifest.retrieval is None:
                    raise AgentCatalogError(
                        f"RAG agent manifest '{path}' must use schema_version 2 "
                        "with retrieval settings."
                    )
                if manifest.retrieval.query_rewrite.count:
                    try:
                        self._prompts.validate_messages(manifest.name, manifest.target, "rewrite")
                    except PromptTemplateError as exc:
                        raise AgentCatalogError(str(exc)) from exc
            elif manifest.retrieval is not None:
                raise AgentCatalogError(
                    f"Non-RAG agent manifest '{path}' must not declare retrieval settings."
                )
            try:
                self._prompts.validate(manifest.name, manifest.target)
                if manifest.name == "medical_lab_explainer":
                    self._prompts.validate_messages(
                        manifest.name, manifest.target, "interpretation"
                    )
            except PromptTemplateError as exc:
                raise AgentCatalogError(str(exc)) from exc
            if manifest.inference:
                try:
                    self._validate_inference(manifest, manifest.inference.defaults)
                except ValueError as exc:
                    raise AgentCatalogError(f"Invalid agent manifest '{path}': {exc}") from exc
            manifests.append(manifest)

        names = Counter(agent.name for agent in manifests)
        duplicates = sorted(name for name, count in names.items() if count > 1)
        if duplicates:
            raise AgentCatalogError(f"Duplicate agent names: {', '.join(duplicates)}.")

        for target in get_args(RoutableTarget):
            defaults = [
                agent
                for agent in manifests
                if agent.enabled and agent.target == target and agent.default_for_target
            ]
            if len(defaults) != 1:
                raise AgentCatalogError(
                    f"Target '{target}' must have exactly one enabled default agent profile."
                )
        return {agent.name: agent for agent in manifests}

    @staticmethod
    def _validate_inference(agent: AgentManifest, values: ResolvedInferenceOptions) -> None:
        inference = agent.inference
        assert inference is not None
        limits = inference.limits
        if values.model not in inference.allowed_models:
            raise ValueError(
                f"Model '{values.model}' is not approved for agent_name '{agent.name}'. "
                f"Allowed models: {', '.join(inference.allowed_models)}."
            )
        checks = (
            ("temperature", values.temperature, limits.temperature),
            ("max_output_tokens", values.max_output_tokens, limits.max_output_tokens),
            ("context_window", values.context_window, limits.context_window),
            ("seed", values.seed, limits.seed),
            ("top_p", values.top_p, limits.top_p),
            ("top_k", values.top_k, limits.top_k),
            ("repeat_penalty", values.repeat_penalty, limits.repeat_penalty),
        )
        for name, value, limit in checks:
            if not limit.minimum <= value <= limit.maximum:
                raise ValueError(
                    f"{name} must be between {limit.minimum} and {limit.maximum} "
                    f"for agent_name '{agent.name}'."
                )
        if len(values.stop) > limits.max_stop_sequences:
            raise ValueError(
                f"stop accepts at most {limits.max_stop_sequences} values for "
                f"agent_name '{agent.name}'."
            )
        if any(len(value) > limits.max_stop_length for value in values.stop):
            raise ValueError(
                f"Each stop value must contain at most {limits.max_stop_length} characters "
                f"for agent_name '{agent.name}'."
            )

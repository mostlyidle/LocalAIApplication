"""Validated request and inference settings for prompt-backed agent profiles."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, model_validator

RoutableTarget = Literal[
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
]
AgentTarget = Literal["auto"] | RoutableTarget
ModelName = Annotated[
    str,
    Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,99}$"),
]
StopSequence = Annotated[str, Field(min_length=1, max_length=128)]


class InferenceOptions(BaseModel):
    """Optional, validated generation overrides from one chat or task request."""

    model: ModelName | None = None
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_output_tokens: int | None = Field(default=None, ge=1, le=32_768)
    context_window: int | None = Field(default=None, ge=512, le=131_072)
    seed: int | None = Field(default=None, ge=0, le=2_147_483_647)
    top_p: float | None = Field(default=None, ge=0, le=1)
    top_k: int | None = Field(default=None, ge=1, le=1_000)
    repeat_penalty: float | None = Field(default=None, ge=0, le=4)
    stop: list[StopSequence] | None = Field(default=None, max_length=8)


class ResolvedInferenceOptions(BaseModel):
    """Complete provider-neutral settings, converted for Ollama at call time."""

    model: ModelName
    temperature: float
    max_output_tokens: int
    context_window: int
    seed: int
    top_p: float
    top_k: int
    repeat_penalty: float
    stop: list[StopSequence] = Field(default_factory=list, max_length=8)

    def ollama_options(self) -> dict[str, object]:
        return {
            "temperature": self.temperature,
            "num_predict": self.max_output_tokens,
            "num_ctx": self.context_window,
            "seed": self.seed,
            "top_p": self.top_p,
            "top_k": self.top_k,
            "repeat_penalty": self.repeat_penalty,
            "stop": self.stop,
        }


class ExecutionMetadata(BaseModel):
    request_id: str
    target: RoutableTarget
    agent_name: str
    model: str | None = None
    inference: ResolvedInferenceOptions | None = None


class TaskRequest(BaseModel):
    """Bounded agent-task input; optional fields are interpreted by each target."""

    prompt: str = Field(min_length=1, max_length=32_000)
    agent_name: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{0,62}$")
    target: AgentTarget = "auto"
    asset_id: str | None = Field(default=None, max_length=255)
    collection: str = Field(default="documents", pattern=r"^[A-Za-z0-9_-]{1,63}$")
    context: str | None = Field(default=None, max_length=100_000)
    symbol: str | None = Field(default=None, pattern=r"^[A-Za-z0-9.^=-]{1,20}$")
    inference: InferenceOptions | None = None
    model: ModelName | None = Field(default=None, deprecated=True)
    workflow: dict[str, Any] | None = None
    workspace_path: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_target_fields(self) -> TaskRequest:
        if (
            self.model
            and self.inference
            and self.inference.model
            and self.model != self.inference.model
        ):
            raise ValueError("model and inference.model must match when both are supplied")
        if self.target == "stock_research" and not self.symbol:
            raise ValueError("stock_research requires a ticker symbol.")
        if self.target == "software_engineer" and self.asset_id:
            raise ValueError("software_engineer reads a mounted workspace, not an upload.")
        return self

    def inference_overrides(self) -> dict[str, object] | None:
        values = self.inference.model_dump(exclude_none=True) if self.inference else {}
        if self.model and "model" not in values:
            values["model"] = self.model
        return values or None


class AgentResult(BaseModel):
    agent: str
    answer: str
    artifacts: dict[str, Any] = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)
    metadata: ExecutionMetadata | None = None

"""Deterministic question detection and private local answer suggestions."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Any, Protocol

import structlog

from app.config import settings
from app.models.enums import AudioSource

logger = structlog.get_logger(__name__)

ANSWER_PROVIDER_TIMEOUT_SECONDS = 5.0


class AnswerGenerator(Protocol):
    """Provider boundary for a local answer suggestion model."""

    async def generate(self, question: str, context: str) -> str:
        """Generate one private answer suggestion."""
        ...


class Retriever(Protocol):
    """Minimal optional retrieval boundary."""

    async def search(
        self,
        query: str,
        collection: str | None = None,
        top_k: int | None = None,
        score_threshold: float | None = None,
    ) -> list[dict[str, Any]]:
        """Retrieve local context."""
        ...


@dataclass(frozen=True)
class AnswerSuggestion:
    """Answer text and local citations returned to the session."""

    answer: str
    citations: list[str]
    degraded_components: list[str]


class DeterministicQuestionDetector:
    """Detect questions without an LLM and only for system audio."""

    _QUESTION_PREFIX = re.compile(
        r"^(?:who|what|when|where|why|how|can|could|would|will|is|are|do|does|did|should)\b",
        re.IGNORECASE,
    )

    def detect(self, text: str, source: AudioSource) -> str | None:
        """Return the first system-source question sentence, if any."""
        if source != AudioSource.SYSTEM:
            return None
        for sentence in re.split(r"(?<=[.!?])\s+", text.strip()):
            candidate = sentence.strip()
            if candidate.endswith("?") or self._QUESTION_PREFIX.match(candidate):
                return candidate
        return None


class OllamaAnswerGenerator:
    """Generate suggestions directly through the existing local Ollama client."""

    def __init__(self, llm: object | None = None) -> None:
        if llm is None:
            from app.services.llm import llm_service

            llm = llm_service
        self._llm: Any = llm

    async def generate(self, question: str, context: str) -> str:
        """Ask Ollama for a concise private suggestion."""
        model = self._llm.get_chat_model(temperature=0.1, max_tokens=512)
        response = await model.ainvoke(
            [
                {
                    "role": "system",
                    "content": (
                        "You provide a concise private meeting answer suggestion. "
                        "Use only the supplied local context and say when it is insufficient."
                    ),
                },
                {"role": "user", "content": f"Question: {question}\nContext:\n{context}"},
            ]
        )
        return str(response.content).strip()


class FakeAnswerGenerator:
    """Deterministic answer provider for tests."""

    def __init__(self, answer: str = "Local answer") -> None:
        self.answer = answer
        self.calls: list[tuple[str, str]] = []

    async def generate(self, question: str, context: str) -> str:
        """Record the request and return the configured answer."""
        self.calls.append((question, context))
        return self.answer


class MeetingAnswerService:
    """Combine optional Chroma retrieval with local Ollama generation."""

    def __init__(
        self,
        generator: AnswerGenerator | None = None,
        retriever: Retriever | None = None,
        provider_timeout_seconds: float = ANSWER_PROVIDER_TIMEOUT_SECONDS,
    ) -> None:
        if provider_timeout_seconds <= 0:
            raise ValueError("provider_timeout_seconds must be positive")
        self.generator = generator or OllamaAnswerGenerator()
        self.retriever = retriever
        self.provider_timeout_seconds = provider_timeout_seconds

    async def suggest(self, question: str) -> AnswerSuggestion:
        """Retrieve optional context and generate a private answer."""
        context_parts: list[str] = []
        citations: list[str] = []
        degraded_components: list[str] = []
        if settings.meeting_enable_rag and self.retriever is not None:
            try:
                results = await asyncio.wait_for(
                    self.retriever.search(question), timeout=self.provider_timeout_seconds
                )
            except asyncio.TimeoutError:
                logger.warning("meeting_rag_timeout")
                degraded_components.append("rag")
                results = []
            except Exception as exc:
                logger.warning("meeting_rag_degraded", error=str(exc))
                degraded_components.append("rag")
                results = []
            for result in results:
                content = str(result.get("content", "")).strip()
                if content:
                    context_parts.append(content)
                metadata = result.get("metadata") or {}
                if isinstance(metadata, dict) and metadata.get("source"):
                    citations.append(str(metadata["source"]))
        try:
            answer = await asyncio.wait_for(
                self.generator.generate(question, "\n\n".join(context_parts)),
                timeout=self.provider_timeout_seconds,
            )
        except asyncio.TimeoutError:
            logger.warning("meeting_ollama_timeout")
            degraded_components.append("ollama")
            answer = "No local answer is available."
        except Exception as exc:
            logger.warning("meeting_ollama_degraded", error=str(exc))
            degraded_components.append("ollama")
            answer = "No local answer is available."
        return AnswerSuggestion(
            answer=answer,
            citations=list(dict.fromkeys(citations)),
            degraded_components=degraded_components,
        )


__all__ = [
    "ANSWER_PROVIDER_TIMEOUT_SECONDS",
    "AnswerGenerator",
    "AnswerSuggestion",
    "DeterministicQuestionDetector",
    "FakeAnswerGenerator",
    "MeetingAnswerService",
    "OllamaAnswerGenerator",
]

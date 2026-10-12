"""Ollama LLM client wrapper with streaming support."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Any, AsyncIterator

import httpx
import structlog
from langchain_ollama import ChatOllama

from app.api.middleware.error_handler import LLMConnectionError, LLMTimeoutError
from app.config import settings
from app.models.profile_schemas import ResolvedInferenceOptions

logger = structlog.get_logger(__name__)


class LLMService:
    """Wrapper around Ollama providing chat, vision, and streaming capabilities.

    Design decisions:
        - Uses langchain-ollama's ChatOllama for LangChain/LangGraph compatibility.
        - Supports model switching at runtime (chat vs vision).
        - Health check method for the /health endpoint.
        - All methods are async to avoid blocking the event loop.
    """

    def __init__(self) -> None:
        self._base_url = settings.ollama_base_url
        self._timeout = settings.ollama_request_timeout
        self._profile_inference: ContextVar[ResolvedInferenceOptions | None] = ContextVar(
            "llm_profile_inference", default=None
        )

    @contextmanager
    def inference_context(self, inference: ResolvedInferenceOptions):
        """Apply one validated profile's options to all model calls in this task."""
        token: Token[ResolvedInferenceOptions | None] = self._profile_inference.set(inference)
        try:
            yield
        finally:
            self._profile_inference.reset(token)

    def get_chat_model(
        self,
        model: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> ChatOllama:
        """Get a ChatOllama instance for the specified model.

        Args:
            model: Ollama model name. Defaults to the configured chat model.
            temperature: Sampling temperature (lower = more deterministic).
            max_tokens: Maximum tokens in the response.
            **kwargs: Additional kwargs passed to ChatOllama.

        Returns:
            A configured ChatOllama instance.
        """
        inference = self._profile_inference.get()
        if inference is not None:
            options = inference.ollama_options()
            model = inference.model
            temperature = inference.temperature
            max_tokens = inference.max_output_tokens
            kwargs.update({key: value for key, value in options.items() if key not in {"temperature", "num_predict"}})
        return ChatOllama(
            model=model or settings.ollama_chat_model,
            base_url=self._base_url,
            temperature=temperature,
            num_predict=max_tokens,
            timeout=self._timeout,
            **kwargs,
        )

    def get_vision_model(
        self,
        temperature: float = 0.1,
        max_tokens: int = 4096,
    ) -> ChatOllama:
        """Get a ChatOllama instance configured for vision tasks."""
        return self.get_chat_model(
            model=settings.ollama_vision_model,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    async def astream_chat(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Stream chat completion tokens from Ollama.

        Args:
            messages: List of message dicts with 'role' and 'content'.
            model: Optional model override.
            **kwargs: Additional ChatOllama kwargs.

        Yields:
            Individual content tokens as strings.

        Raises:
            LLMConnectionError: If Ollama is unreachable.
            LLMTimeoutError: If the request times out.
        """
        llm = self.get_chat_model(model=model, **kwargs)
        try:
            async for chunk in llm.astream(messages):
                if chunk.content:
                    yield str(chunk.content)
        except httpx.ConnectError as exc:
            logger.error("ollama_connection_failed", error=str(exc))
            raise LLMConnectionError() from exc
        except httpx.TimeoutException as exc:
            logger.error("ollama_timeout", error=str(exc))
            raise LLMTimeoutError() from exc

    async def check_health(self) -> tuple[bool, str]:
        """Check if Ollama is reachable and responsive.

        Returns:
            Tuple of (is_healthy, status_message).
        """
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self._base_url}/api/tags")
                if resp.status_code == 200:
                    data = resp.json()
                    model_count = len(data.get("models", []))
                    return True, f"OK — {model_count} models available"
                return False, f"Unexpected status: {resp.status_code}"
        except httpx.ConnectError:
            return False, "Ollama is not running"
        except httpx.TimeoutException:
            return False, "Ollama health check timed out"

    async def list_models(self) -> list[dict[str, Any]]:
        """List all locally available Ollama models."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self._base_url}/api/tags")
                resp.raise_for_status()
                return resp.json().get("models", [])
        except (httpx.HTTPError, KeyError) as exc:
            logger.error("list_models_failed", error=str(exc))
            return []


# Module-level singleton
llm_service = LLMService()

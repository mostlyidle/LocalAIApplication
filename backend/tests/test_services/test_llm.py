"""Tests for app.services.llm — Ollama LLM client wrapper."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.api.middleware.error_handler import LLMConnectionError, LLMTimeoutError
from app.services.llm import LLMService


# =============================================================================
# Helpers
# =============================================================================


async def _async_iter(items):
    """Convert a list into an async iterator."""
    for item in items:
        yield item


# =============================================================================
# LLMService.__init__ / config
# =============================================================================


class TestLLMServiceInit:
    """Verify service picks up config values."""

    def test_defaults_from_settings(self):
        svc = LLMService()
        assert "localhost" in svc._base_url or "11434" in svc._base_url
        assert isinstance(svc._timeout, int)


# =============================================================================
# get_chat_model
# =============================================================================


class TestGetChatModel:
    """Test ChatOllama factory method."""

    @patch("app.services.llm.ChatOllama")
    def test_returns_chat_ollama_with_defaults(self, mock_cls):
        svc = LLMService()
        svc.get_chat_model()
        mock_cls.assert_called_once()
        kwargs = mock_cls.call_args.kwargs
        assert kwargs["temperature"] == 0.1
        assert kwargs["num_predict"] == 4096

    @patch("app.services.llm.ChatOllama")
    def test_custom_model_and_temperature(self, mock_cls):
        svc = LLMService()
        svc.get_chat_model(model="phi3:3.8b", temperature=0.7, max_tokens=2048)
        kwargs = mock_cls.call_args.kwargs
        assert kwargs["model"] == "phi3:3.8b"
        assert kwargs["temperature"] == 0.7
        assert kwargs["num_predict"] == 2048

    @patch("app.services.llm.ChatOllama")
    def test_extra_kwargs_forwarded(self, mock_cls):
        svc = LLMService()
        svc.get_chat_model(top_k=40)
        assert mock_cls.call_args.kwargs["top_k"] == 40

    @patch("app.services.llm.ChatOllama")
    def test_default_model_uses_settings(self, mock_cls):
        """When no model is given, uses settings.ollama_chat_model."""
        from app.config import settings

        svc = LLMService()
        svc.get_chat_model()
        assert mock_cls.call_args.kwargs["model"] == settings.ollama_chat_model


# =============================================================================
# get_vision_model
# =============================================================================


class TestGetVisionModel:
    """Verify get_vision_model delegates to get_chat_model with vision model."""

    @patch("app.services.llm.ChatOllama")
    def test_uses_vision_model_from_settings(self, mock_cls):
        from app.config import settings

        svc = LLMService()
        svc.get_vision_model()
        assert mock_cls.call_args.kwargs["model"] == settings.ollama_vision_model

    @patch("app.services.llm.ChatOllama")
    def test_passes_temperature_and_max_tokens(self, mock_cls):
        svc = LLMService()
        svc.get_vision_model(temperature=0.5, max_tokens=2048)
        kwargs = mock_cls.call_args.kwargs
        assert kwargs["temperature"] == 0.5
        assert kwargs["num_predict"] == 2048


# =============================================================================
# astream_chat
# =============================================================================


class TestAstreamChat:
    """Test streaming chat completions."""

    async def test_yields_content_tokens(self):
        svc = LLMService()
        chunk1 = MagicMock(content="Hello")
        chunk2 = MagicMock(content=" world")
        chunk3 = MagicMock(content="")  # empty chunk, should be skipped

        mock_llm = MagicMock()
        # astream must return an async generator, not a coroutine
        mock_llm.astream = lambda *a, **kw: _async_iter([chunk1, chunk2, chunk3])

        with patch.object(svc, "get_chat_model", return_value=mock_llm):
            tokens = []
            async for token in svc.astream_chat([{"role": "user", "content": "Hi"}]):
                tokens.append(token)

        assert tokens == ["Hello", " world"]

    async def test_connect_error_raises_llm_connection_error(self):
        svc = LLMService()

        async def _raise_connect(*_a, **_kw):
            raise httpx.ConnectError("refused")
            yield  # noqa: unreachable — makes this an async generator

        mock_llm = MagicMock()
        mock_llm.astream = _raise_connect

        with patch.object(svc, "get_chat_model", return_value=mock_llm):
            with pytest.raises(LLMConnectionError):
                async for _ in svc.astream_chat([]):
                    pass

    async def test_timeout_raises_llm_timeout_error(self):
        svc = LLMService()

        async def _raise_timeout(*_a, **_kw):
            raise httpx.TimeoutException("timed out")
            yield  # noqa

        mock_llm = MagicMock()
        mock_llm.astream = _raise_timeout

        with patch.object(svc, "get_chat_model", return_value=mock_llm):
            with pytest.raises(LLMTimeoutError):
                async for _ in svc.astream_chat([]):
                    pass


# =============================================================================
# check_health
# =============================================================================


class TestCheckHealth:
    """Test Ollama health-check logic."""

    async def test_healthy_response(self):
        svc = LLMService()
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"models": [{"name": "a"}, {"name": "b"}]}

        with patch("app.services.llm.httpx.AsyncClient") as mock_client_cls:
            mock_client_cls.return_value.__aenter__ = AsyncMock(
                return_value=MagicMock(get=AsyncMock(return_value=resp))
            )
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            healthy, msg = await svc.check_health()

        assert healthy is True
        assert "2 models" in msg

    async def test_unhealthy_status_code(self):
        svc = LLMService()
        resp = MagicMock()
        resp.status_code = 500

        with patch("app.services.llm.httpx.AsyncClient") as mock_client_cls:
            mock_client_cls.return_value.__aenter__ = AsyncMock(
                return_value=MagicMock(get=AsyncMock(return_value=resp))
            )
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            healthy, msg = await svc.check_health()

        assert healthy is False
        assert "500" in msg

    async def test_connect_error(self):
        svc = LLMService()
        with patch("app.services.llm.httpx.AsyncClient") as mock_client_cls:
            mock_client_cls.return_value.__aenter__ = AsyncMock(
                return_value=MagicMock(get=AsyncMock(side_effect=httpx.ConnectError("no")))
            )
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            healthy, msg = await svc.check_health()

        assert healthy is False
        assert "not running" in msg

    async def test_timeout_error(self):
        svc = LLMService()
        with patch("app.services.llm.httpx.AsyncClient") as mock_client_cls:
            mock_client_cls.return_value.__aenter__ = AsyncMock(
                return_value=MagicMock(get=AsyncMock(side_effect=httpx.TimeoutException("timeout")))
            )
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            healthy, msg = await svc.check_health()

        assert healthy is False
        assert "timed out" in msg


# =============================================================================
# list_models
# =============================================================================


class TestListModels:
    """Test Ollama model listing."""

    async def test_returns_model_list(self):
        svc = LLMService()
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"models": [{"name": "llama3.1:8b"}]}

        with patch("app.services.llm.httpx.AsyncClient") as mock_client_cls:
            mock_client_cls.return_value.__aenter__ = AsyncMock(
                return_value=MagicMock(get=AsyncMock(return_value=resp))
            )
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            models = await svc.list_models()

        assert len(models) == 1
        assert models[0]["name"] == "llama3.1:8b"

    async def test_returns_empty_on_error(self):
        svc = LLMService()
        with patch("app.services.llm.httpx.AsyncClient") as mock_client_cls:
            mock_client_cls.return_value.__aenter__ = AsyncMock(
                return_value=MagicMock(get=AsyncMock(side_effect=httpx.ConnectError("fail")))
            )
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            models = await svc.list_models()

        assert models == []

    @pytest.mark.parametrize("payload", [{}, {"models": [{"name": 42}]}, {"models": "invalid"}])
    async def test_strict_inventory_distinguishes_invalid_responses_from_empty_models(self, payload):
        from app.api.middleware.error_handler import LLMConnectionError
        response = MagicMock()
        response.json.return_value = payload
        with patch("app.services.llm.httpx.AsyncClient") as cls:
            cls.return_value.__aenter__ = AsyncMock(return_value=MagicMock(get=AsyncMock(return_value=response)))
            cls.return_value.__aexit__ = AsyncMock(return_value=False)
            with pytest.raises(LLMConnectionError):
                await LLMService().list_models(raise_on_error=True)


# =============================================================================
# Module-level singleton
# =============================================================================


class TestSingleton:
    def test_module_level_instance(self):
        from app.services.llm import llm_service

        assert isinstance(llm_service, LLMService)

"""Tests for the GET /health endpoint."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient


class TestHealthEndpoint:
    """Tests for GET /api/v1/health."""

    async def test_required_readiness_ignores_unresponsive_optional_providers(
        self, client: AsyncClient
    ):
        """Required readiness succeeds without probing optional services."""

        class FakeConnection:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc_value, traceback):
                return None

            async def execute(self, statement):
                return None

        class FakeEngine:
            def connect(self):
                return FakeConnection()

        mock_optional_http = MagicMock(side_effect=AssertionError("optional HTTP probe called"))
        mock_optional_rag = AsyncMock(side_effect=AssertionError("optional RAG probe called"))
        with (
            patch(
                "app.services.transcription.check_local_asr_readiness",
                new=AsyncMock(return_value=(True, "OK — local ASR model is ready")),
            ),
            patch("app.services.database.get_app_engine", return_value=FakeEngine()),
            patch("app.api.routes.tools.httpx.AsyncClient", mock_optional_http),
            patch("app.services.hybrid_vector_store.hybrid_vector_store_service.list_collections", mock_optional_rag),
        ):
            response = await client.get("/api/v1/health/ready")

        assert response.status_code == 200
        data = response.json()
        assert data["meeting_ready"] is True
        assert data["status"] == "healthy"
        assert {service["name"] for service in data["services"]} == {
            "local_asr",
            "app_database",
        }
        mock_optional_http.assert_not_called()
        mock_optional_rag.assert_not_awaited()

    async def test_health_returns_200(self, client: AsyncClient):
        """Health endpoint should always return 200 even when services are down."""
        # hybrid_vector_store_service is lazily imported inside health_check,
        # so we patch it in its home module.
        mock_vs = AsyncMock()
        mock_vs.list_collections = AsyncMock(return_value=["documents"])

        with (
            patch("app.api.routes.tools.httpx.AsyncClient") as mock_httpx_class,
            patch("app.services.hybrid_vector_store.hybrid_vector_store_service", mock_vs),
        ):
            # Mock Ollama check — simulate Ollama being healthy
            # Use MagicMock (not AsyncMock) because httpx Response.json() is synchronous.
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"models": [{"name": "llama3.1:8b"}]}

            mock_client_instance = AsyncMock()
            mock_client_instance.get = AsyncMock(return_value=mock_response)
            mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
            mock_client_instance.__aexit__ = AsyncMock(return_value=None)
            mock_httpx_class.return_value = mock_client_instance

            resp = await client.get("/api/v1/health")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in {"healthy", "degraded", "unhealthy"}
        assert "services" in data
        assert "version" in data
        assert data["meeting_ready"] is False
        services = {service["name"]: service for service in data["services"]}
        assert services["local_asr"]["required_for_meeting"] is True
        assert services["ollama"]["optional_for_answers"] is True
        assert services["qdrant"]["optional_for_answers"] is True
        assert services["finnhub_market_data"]["optional_for_answers"] is True
        assert services["comfyui"]["optional_for_answers"] is True

    async def test_metrics_endpoint_is_exposed(self, client: AsyncClient):
        response = await client.get("/metrics")
        assert response.status_code == 200
        assert "http_requests_total" in response.text

    async def test_health_unhealthy_when_all_down(self, client: AsyncClient):
        """When all services fail, status should be 'unhealthy'."""
        mock_vs = AsyncMock()
        mock_vs.list_collections = AsyncMock(side_effect=RuntimeError("Qdrant offline"))

        with (
            patch("app.api.routes.tools.httpx.AsyncClient") as mock_httpx_class,
            patch("app.services.hybrid_vector_store.hybrid_vector_store_service", mock_vs),
            patch(
                "app.services.database.get_app_engine",
                side_effect=RuntimeError("DB offline"),
            ),
        ):
            # Ollama connect error
            import httpx as real_httpx

            mock_client_instance = AsyncMock()
            mock_client_instance.get = AsyncMock(
                side_effect=real_httpx.ConnectError("Connection refused")
            )
            mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
            mock_client_instance.__aexit__ = AsyncMock(return_value=None)
            mock_httpx_class.return_value = mock_client_instance

            resp = await client.get("/api/v1/health")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "unhealthy"

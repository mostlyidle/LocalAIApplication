from __future__ import annotations

import httpx
import pytest

from app.services.comfyui import ComfyUIClient
from app.services.market_data import (
    FinnhubMarketDataClient,
    MarketDataError,
    MarketDataRateLimitError,
)


async def test_finnhub_snapshot_authenticates_and_caches() -> None:
    requests: list[httpx.Request] = []

    async def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/quote"):
            return httpx.Response(200, json={"c": 125.0, "t": 1_780_000_000})
        if request.url.path.endswith("/profile2"):
            return httpx.Response(200, json={"name": "Example Inc"})
        return httpx.Response(200, json=[{"headline": "Example news", "url": "https://example.test"}])

    client = FinnhubMarketDataClient(
        api_key="test-key",
        cache_seconds=60,
        transport=httpx.MockTransport(respond),
    )
    try:
        first = await client.snapshot("aapl")
        second = await client.snapshot("AAPL")
    finally:
        await client.close()

    assert first["symbol"] == "AAPL"
    assert first["quote"]["current"] == 125.0
    assert first["recent_news"][0]["headline"] == "Example news"
    assert second["cache_hit"] is True
    assert len(requests) == 3
    assert all(request.headers["X-Finnhub-Token"] == "test-key" for request in requests)


async def test_finnhub_requires_a_key_and_surfaces_provider_rate_limits() -> None:
    unconfigured = FinnhubMarketDataClient(api_key=None, cache_seconds=0)
    with pytest.raises(MarketDataError, match="FINNHUB_API_KEY"):
        await unconfigured.snapshot("AAPL")
    await unconfigured.close()

    limited = FinnhubMarketDataClient(
        api_key="test-key",
        cache_seconds=0,
        transport=httpx.MockTransport(lambda _: httpx.Response(429)),
    )
    with pytest.raises(MarketDataRateLimitError, match="rate limit"):
        await limited.snapshot("AAPL")
    await limited.close()


async def test_comfyui_submits_workflow_once_and_returns_queue_id() -> None:
    requests: list[httpx.Request] = []

    async def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"prompt_id": "job-42"})

    client = ComfyUIClient("http://comfyui.test", transport=httpx.MockTransport(respond))
    workflow = {"1": {"class_type": "SaveImage", "inputs": {}}}
    try:
        result = await client.submit(workflow)
    finally:
        await client.close()

    assert result["prompt_id"] == "job-42"
    assert len(requests) == 1
    assert requests[0].url.path == "/prompt"
    assert requests[0].read() == b'{"prompt":{"1":{"class_type":"SaveImage","inputs":{}}}}'


async def test_comfyui_reports_unavailable_server() -> None:
    client = ComfyUIClient(
        "http://comfyui.test",
        transport=httpx.MockTransport(lambda _: httpx.Response(503)),
    )
    try:
        with pytest.raises(RuntimeError, match="ComfyUI is unavailable"):
            await client.submit({"1": {"class_type": "SaveImage", "inputs": {}}})
    finally:
        await client.close()


async def test_finnhub_preserves_partial_provider_failure_warnings() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/quote"):
            return httpx.Response(200, json={"c": 125.0})
        return httpx.Response(429)

    client = FinnhubMarketDataClient(
        api_key="test", cache_seconds=60, transport=httpx.MockTransport(respond)
    )
    try:
        snapshot = await client.snapshot("AAPL")
        cached = await client.snapshot("AAPL")
    finally:
        await client.close()
    assert snapshot["quote"]["current"] == 125.0
    assert len(snapshot["warnings"]) == 2
    assert all("rate limit" in warning for warning in snapshot["warnings"])
    assert cached["warnings"] == snapshot["warnings"]

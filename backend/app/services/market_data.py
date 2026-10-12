"""Rate-conscious Finnhub adapter for bounded stock-research tasks."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx


class MarketDataError(RuntimeError):
    """The configured market-data provider could not fulfill a live request."""


class MarketDataRateLimitError(MarketDataError):
    """The provider declined a request due to rate limiting."""


class FinnhubMarketDataClient:
    """Small adapter for Finnhub's documented REST endpoints."""

    def __init__(
        self,
        *,
        api_key: str | None,
        cache_seconds: int,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._cache_seconds = max(cache_seconds, 0)
        self._cache: dict[str, tuple[datetime, dict[str, Any]]] = {}
        self._lock = asyncio.Lock()
        self._client = httpx.AsyncClient(
            base_url="https://finnhub.io/api/v1",
            timeout=15.0,
            transport=transport,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def snapshot(self, symbol: str) -> dict[str, Any]:
        if not self._api_key:
            raise MarketDataError(
                "Live market data is not configured. Set FINNHUB_API_KEY in your local .env file."
            )
        normalized = symbol.upper()
        now = datetime.now(UTC)
        async with self._lock:
            cached = self._cache.get(normalized)
            if cached and now - cached[0] < timedelta(seconds=self._cache_seconds):
                return {**cached[1], "cache_hit": True}

        quote, company_result, news_result = await asyncio.gather(
            self._get("quote", {"symbol": normalized}),
            self._get_optional("stock/profile2", {"symbol": normalized}),
            self._get_optional(
                "company-news",
                {
                    "symbol": normalized,
                    "from": (date.today() - timedelta(days=7)).isoformat(),
                    "to": date.today().isoformat(),
                },
            ),
        )
        company, company_warning = company_result
        news, news_warning = news_result
        if not isinstance(quote, dict) or not isinstance(quote.get("c"), int | float) or quote["c"] <= 0:
            raise MarketDataError(f"The provider returned no current quote for {normalized}.")
        quote_time = quote.get("t")
        timestamp = (
            datetime.fromtimestamp(quote_time, UTC).isoformat()
            if isinstance(quote_time, int | float) and quote_time > 0
            else None
        )
        articles = news if isinstance(news, list) else []
        snapshot = {
            "provider": "Finnhub",
            "symbol": normalized,
            "fetched_at": now.isoformat(),
            "quote_timestamp": timestamp,
            "quote": {
                "current": quote.get("c"),
                "change": quote.get("d"),
                "change_percent": quote.get("dp"),
                "open": quote.get("o"),
                "high": quote.get("h"),
                "low": quote.get("l"),
                "previous_close": quote.get("pc"),
            },
            "company": company if isinstance(company, dict) else {},
            "recent_news": [
                {
                    "headline": item.get("headline"),
                    "source": item.get("source"),
                    "published_at": item.get("datetime"),
                    "url": item.get("url"),
                }
                for item in articles[:8]
                if isinstance(item, dict)
            ],
            "cache_hit": False,
            "warnings": [warning for warning in (company_warning, news_warning) if warning],
        }
        async with self._lock:
            self._cache[normalized] = (now, snapshot)
        return snapshot

    async def _get_optional(self, endpoint: str, params: dict[str, str]) -> tuple[Any, str | None]:
        try:
            return await self._get(endpoint, params), None
        except MarketDataError as exc:
            return None, f"{endpoint} is unavailable: {exc}"

    async def _get(self, endpoint: str, params: dict[str, str]) -> Any:
        try:
            response = await self._client.get(
                f"/{endpoint}",
                params=params,
                headers={"X-Finnhub-Token": self._api_key or ""},
            )
        except httpx.HTTPError as exc:
            raise MarketDataError("The live market-data provider is unavailable.") from exc
        if response.status_code == 429:
            raise MarketDataRateLimitError("The live market-data provider rate limit was reached.")
        if response.is_error:
            raise MarketDataError("The live market-data provider rejected the request.")
        try:
            return response.json()
        except ValueError as exc:
            raise MarketDataError("The live market-data provider returned an invalid response.") from exc

"""DataOrchestrator — fallback routing + SQLite caching across providers."""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from src.storage.cache import Cache

logger = logging.getLogger(__name__)


class DataOrchestrator:
    """
    Routes data requests to providers with:
    - Fallback: if primary provider fails, try secondary
    - SQLite caching with per-data-type TTLs
    - Logging of which provider served each request

    TTLs:
        quotes:         5 min
        news:           15 min
        options:        30 min
        fundamentals:   24 hours
        macro:          60 min
    """

    TTLS = {
        "quote": 300,
        "top_movers": 300,
        "news": 900,
        "market_news": 900,
        "options": 1800,
        "expirations": 1800,
        "fundamentals": 86400,
        "earnings": 3600,
        "recommendations": 3600,
        "macro": 3600,
        "yield_curve": 3600,
    }

    def __init__(self, cache: Optional[Cache] = None):
        self.cache = cache or Cache()
        # Provider registrations
        self._market_providers: list[Any] = []
        self._news_providers: list[Any] = []
        self._options_providers: list[Any] = []
        self._macro_providers: list[Any] = []
        self._fundamentals_providers: list[Any] = []

    def register_market(self, provider: Any) -> "DataOrchestrator":
        self._market_providers.append(provider)
        return self

    def register_news(self, provider: Any) -> "DataOrchestrator":
        self._news_providers.append(provider)
        return self

    def register_options(self, provider: Any) -> "DataOrchestrator":
        self._options_providers.append(provider)
        return self

    def register_macro(self, provider: Any) -> "DataOrchestrator":
        self._macro_providers.append(provider)
        return self

    def register_fundamentals(self, provider: Any) -> "DataOrchestrator":
        self._fundamentals_providers.append(provider)
        return self

    async def _with_fallback(
        self,
        cache_key: str,
        ttl_key: str,
        providers: list[Any],
        method: str,
        *args,
        **kwargs,
    ) -> Optional[Any]:
        """
        Try providers in order, return first successful result.
        Uses cache to avoid redundant calls within TTL window.
        """
        # Check cache first
        cached = await self.cache.get(cache_key)
        if cached is not None:
            logger.debug("Cache hit: %s", cache_key)
            return cached

        ttl = self.TTLS.get(ttl_key, 300)
        result = None

        for provider in providers:
            provider_name = type(provider).__name__
            fn: Optional[Callable] = getattr(provider, method, None)
            if fn is None:
                continue
            try:
                result = await fn(*args, **kwargs)
                if result is not None and result != [] and result != {}:
                    logger.info("[%s] served %s%s", provider_name, method, f"({args[0]})" if args else "")
                    await self.cache.set(cache_key, result, ttl)
                    return result
            except Exception as e:
                logger.warning("[%s] %s failed: %s — trying next provider", provider_name, method, e)
                continue

        logger.warning("All providers failed for %s", cache_key)
        return result  # may be None or empty

    async def get_quote(self, ticker: str):
        return await self._with_fallback(
            f"quote:{ticker}", "quote",
            self._market_providers, "get_quote", ticker,
        )

    async def get_top_movers(self, limit: int = 10):
        return await self._with_fallback(
            f"top_movers:{limit}", "top_movers",
            self._market_providers, "get_top_movers", limit,
        )

    async def get_news(self, ticker: str, limit: int = 10):
        return await self._with_fallback(
            f"news:{ticker}:{limit}", "news",
            self._news_providers, "get_news", ticker, limit,
        )

    async def get_market_news(self, limit: int = 20):
        return await self._with_fallback(
            f"market_news:{limit}", "market_news",
            self._news_providers, "get_market_news", limit,
        )

    async def get_option_chain(self, ticker: str, expiry: Optional[str] = None):
        expiry_key = expiry or "nearest"
        return await self._with_fallback(
            f"options:{ticker}:{expiry_key}", "options",
            self._options_providers, "get_option_chain", ticker, expiry,
        )

    async def get_expirations(self, ticker: str):
        return await self._with_fallback(
            f"expirations:{ticker}", "expirations",
            self._options_providers, "get_expirations", ticker,
        )

    async def get_fundamentals(self, ticker: str):
        return await self._with_fallback(
            f"fundamentals:{ticker}", "fundamentals",
            self._fundamentals_providers, "get_fundamentals", ticker,
        )

    async def get_earnings_calendar(self, from_date: str, to_date: str):
        return await self._with_fallback(
            f"earnings:{from_date}:{to_date}", "earnings",
            self._fundamentals_providers, "get_earnings_calendar", from_date, to_date,
        )

    async def get_recommendations(self, ticker: str):
        return await self._with_fallback(
            f"recommendations:{ticker}", "recommendations",
            self._fundamentals_providers, "get_recommendations", ticker,
        )

    async def get_indicator(self, series_id: str):
        return await self._with_fallback(
            f"macro:{series_id}", "macro",
            self._macro_providers, "get_indicator", series_id,
        )

    async def get_yield_curve(self):
        return await self._with_fallback(
            "yield_curve", "yield_curve",
            self._macro_providers, "get_yield_curve",
        )

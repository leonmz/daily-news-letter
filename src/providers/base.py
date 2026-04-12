"""Protocol definitions for all data providers."""

from datetime import datetime
from typing import Optional, Protocol, runtime_checkable

import pandas as pd

from src.models.market import StockQuote, OptionsSnapshot
from src.models.news import NewsArticle
from src.models.macro import MacroIndicator, YieldCurve


class ProviderError(Exception):
    """Raised when a provider encounters an unrecoverable error."""


class RateLimitError(ProviderError):
    """Raised when a provider rate limit is hit."""


class AuthError(ProviderError):
    """Raised when API credentials are invalid or missing."""


@runtime_checkable
class MarketDataProvider(Protocol):
    """Provider for real-time and historical market data."""

    async def get_quote(self, ticker: str) -> Optional[StockQuote]:
        """Return current quote for a ticker. Returns None on failure."""
        ...

    async def get_top_movers(self, limit: int = 10) -> dict[str, list[StockQuote]]:
        """Return top gainers/losers. Dict with keys 'gainers' and 'losers'."""
        ...


@runtime_checkable
class NewsProvider(Protocol):
    """Provider for news articles."""

    async def get_news(self, ticker: str, limit: int = 10) -> list[NewsArticle]:
        """Return recent news articles for a ticker."""
        ...

    async def get_market_news(self, limit: int = 20) -> list[NewsArticle]:
        """Return broad market news, not ticker-specific."""
        ...


@runtime_checkable
class OptionsProvider(Protocol):
    """Provider for options chain data."""

    async def get_option_chain(
        self, ticker: str, expiry: Optional[str] = None
    ) -> Optional[OptionsSnapshot]:
        """Return options chain. If expiry is None, use nearest expiry."""
        ...

    async def get_expirations(self, ticker: str) -> list[str]:
        """Return available expiration dates as YYYY-MM-DD strings."""
        ...


@runtime_checkable
class MacroProvider(Protocol):
    """Provider for macroeconomic indicators."""

    async def get_indicator(self, series_id: str) -> Optional[MacroIndicator]:
        """Return the latest value for a FRED-style series ID."""
        ...

    async def get_yield_curve(self) -> Optional[YieldCurve]:
        """Return current yield curve data."""
        ...


@runtime_checkable
class FundamentalsProvider(Protocol):
    """Provider for company fundamentals."""

    async def get_fundamentals(self, ticker: str) -> Optional[dict]:
        """Return company profile: market_cap, sector, peers, etc."""
        ...

    async def get_earnings_calendar(
        self, from_date: str, to_date: str
    ) -> list[dict]:
        """Return upcoming earnings. Dates as YYYY-MM-DD strings."""
        ...

    async def get_recommendations(self, ticker: str) -> Optional[dict]:
        """Return analyst ratings and price targets."""
        ...


@runtime_checkable
class HistoricalProvider(Protocol):
    """Provider for historical OHLCV data."""

    async def get_historical(
        self, ticker: str, start: str, end: str
    ) -> Optional[pd.DataFrame]:
        """Return OHLCV DataFrame with DatetimeIndex. Dates as YYYY-MM-DD."""
        ...

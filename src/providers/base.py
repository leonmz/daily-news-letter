"""Protocol definitions for all data providers."""

from typing import Optional, Protocol, runtime_checkable

import pandas as pd

from src.models.market import StockQuote, OptionsSnapshot
from src.models.news import NewsArticle
from src.models.macro import MacroIndicator, YieldCurve


class ProviderError(Exception):
    """Raised when a provider encounters an unrecoverable error."""

class RateLimitError(ProviderError):
    pass

class AuthError(ProviderError):
    pass


@runtime_checkable
class MarketDataProvider(Protocol):
    async def get_quote(self, ticker: str) -> Optional[StockQuote]: ...
    async def get_top_movers(self, limit: int = 10) -> dict[str, list[StockQuote]]: ...


@runtime_checkable
class NewsProvider(Protocol):
    async def get_news(self, ticker: str, limit: int = 10) -> list[NewsArticle]: ...
    async def get_market_news(self, limit: int = 20) -> list[NewsArticle]: ...


@runtime_checkable
class OptionsProvider(Protocol):
    async def get_option_chain(self, ticker: str, expiry: Optional[str] = None) -> Optional[OptionsSnapshot]: ...
    async def get_expirations(self, ticker: str) -> list[str]: ...


@runtime_checkable
class MacroProvider(Protocol):
    async def get_indicator(self, series_id: str) -> Optional[MacroIndicator]: ...
    async def get_yield_curve(self) -> Optional[YieldCurve]: ...


@runtime_checkable
class FundamentalsProvider(Protocol):
    async def get_fundamentals(self, ticker: str) -> Optional[dict]: ...
    async def get_earnings_calendar(self, from_date: str, to_date: str) -> list[dict]: ...
    async def get_recommendations(self, ticker: str) -> Optional[dict]: ...


@runtime_checkable
class HistoricalProvider(Protocol):
    async def get_historical(self, ticker: str, start: str, end: str) -> Optional[pd.DataFrame]: ...

"""Alpaca Markets provider — free tier (IEX real-time quotes + Benzinga news)."""

import logging
from datetime import datetime, timezone
from typing import Optional

from src.models.market import StockQuote
from src.models.news import NewsArticle
from src.providers.base import AuthError, ProviderError

logger = logging.getLogger(__name__)

_SOURCE = "alpaca"


class AlpacaProvider:
    """
    Wraps the alpaca-py SDK for market data and news.

    Free tier capabilities:
    - Real-time quotes via IEX feed (~200 calls/min)
    - Top movers via most-active screener
    - Benzinga news via Alpaca News API
    """

    def __init__(self, api_key: str, secret_key: str):
        if not api_key or not secret_key:
            raise AuthError("ALPACA_API_KEY and ALPACA_SECRET_KEY are required")
        self._api_key = api_key
        self._secret_key = secret_key
        self._stock_client = None
        self._news_client = None

    def _get_stock_client(self):
        if self._stock_client is None:
            from alpaca.data.historical import StockHistoricalDataClient
            self._stock_client = StockHistoricalDataClient(
                api_key=self._api_key, secret_key=self._secret_key
            )
        return self._stock_client

    def _get_news_client(self):
        """News client — separate from stock data client."""
        if self._news_client is None:
            from alpaca.data.historical import NewsClient
            self._news_client = NewsClient(
                api_key=self._api_key, secret_key=self._secret_key
            )
        return self._news_client

    async def get_quote(self, ticker: str) -> Optional[StockQuote]:
        """Real-time quote via IEX feed."""
        try:
            from alpaca.data.historical import StockHistoricalDataClient
            from alpaca.data.requests import StockLatestQuoteRequest, StockSnapshotRequest

            client = self._get_stock_client()
            req = StockSnapshotRequest(symbol_or_symbols=ticker, feed="iex")
            snapshots = client.get_stock_snapshot(req)
            snap = snapshots.get(ticker)
            if snap is None:
                logger.warning("Alpaca: no snapshot for %s", ticker)
                return None

            # Snapshot has latest_trade, latest_quote, daily_bar
            trade = snap.latest_trade
            daily = snap.daily_bar
            prev_close = snap.previous_daily_bar.close if snap.previous_daily_bar else None

            price = float(trade.price) if trade else None
            if price is None and daily:
                price = float(daily.close)
            if price is None:
                return None

            change = 0.0
            change_pct = 0.0
            if prev_close and prev_close != 0:
                change = price - float(prev_close)
                change_pct = (change / float(prev_close)) * 100

            volume = int(daily.volume) if daily and daily.volume else 0

            return StockQuote(
                ticker=ticker.upper(),
                price=price,
                change=change,
                change_pct=change_pct,
                volume=volume,
                market_cap=None,  # not available from snapshot
                timestamp=trade.timestamp if trade else datetime.now(timezone.utc),
                source=_SOURCE,
                delayed=False,
            )
        except AuthError:
            raise
        except Exception as e:
            logger.error("Alpaca get_quote(%s) failed: %s", ticker, e)
            return None

    async def get_top_movers(self, limit: int = 10) -> dict[str, list[StockQuote]]:
        """
        Return top gainers and losers using Alpaca's screener endpoint.
        Falls back to most-active snapshot approach if screener is unavailable.
        """
        try:
            from alpaca.data.historical import StockHistoricalDataClient
            from alpaca.data.requests import StockSnapshotRequest

            # Use screener API if available (requires broker key)
            try:
                return await self._get_movers_via_screener(limit)
            except Exception:
                pass

            # Fallback: snapshot a list of liquid large-caps and sort
            return await self._get_movers_via_snapshot(limit)

        except Exception as e:
            logger.error("Alpaca get_top_movers failed: %s", e)
            return {"gainers": [], "losers": []}

    async def _get_movers_via_screener(self, limit: int) -> dict[str, list[StockQuote]]:
        """Use Alpaca's screener endpoint (requires data subscription)."""
        import httpx

        url = "https://data.alpaca.markets/v1beta1/screener/stocks/movers"
        headers = {
            "APCA-API-KEY-ID": self._api_key,
            "APCA-API-SECRET-KEY": self._secret_key,
        }
        params = {"top": limit}

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, headers=headers, params=params)
            resp.raise_for_status()
            data = resp.json()

        gainers = []
        losers = []

        for item in data.get("gainers", []):
            q = self._screener_item_to_quote(item)
            if q:
                gainers.append(q)

        for item in data.get("losers", []):
            q = self._screener_item_to_quote(item)
            if q:
                losers.append(q)

        return {"gainers": gainers[:limit], "losers": losers[:limit]}

    def _screener_item_to_quote(self, item: dict) -> Optional[StockQuote]:
        try:
            ticker = item.get("symbol", "")
            price = float(item.get("price", 0))
            change = float(item.get("change", 0))
            change_pct = float(item.get("change_percent", 0))
            volume = int(item.get("volume", 0))
            return StockQuote(
                ticker=ticker,
                price=price,
                change=change,
                change_pct=change_pct,
                volume=volume,
                market_cap=None,
                timestamp=datetime.now(timezone.utc),
                source=_SOURCE,
                delayed=False,
            )
        except Exception:
            return None

    async def _get_movers_via_snapshot(self, limit: int) -> dict[str, list[StockQuote]]:
        """Snapshot a predefined liquid universe and sort by change_pct."""
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests import StockSnapshotRequest

        universe = [
            "AAPL", "MSFT", "NVDA", "AMZN", "GOOG", "META", "TSLA", "BRK-B",
            "JPM", "V", "JNJ", "UNH", "XOM", "PG", "MA", "HD", "CVX", "ABBV",
            "MRK", "PEP", "KO", "AVGO", "COST", "WMT", "BAC", "DIS", "NFLX",
            "AMD", "INTC", "QCOM", "ORCL", "CRM", "ADBE", "PYPL", "SQ",
        ]

        client = self._get_stock_client()
        req = StockSnapshotRequest(symbol_or_symbols=universe, feed="iex")
        snapshots = client.get_stock_snapshot(req)

        quotes = []
        for ticker, snap in snapshots.items():
            try:
                trade = snap.latest_trade
                daily = snap.daily_bar
                prev = snap.previous_daily_bar

                price = float(trade.price) if trade else (float(daily.close) if daily else None)
                if price is None:
                    continue

                prev_close = float(prev.close) if prev else None
                change = price - prev_close if prev_close else 0.0
                change_pct = (change / prev_close * 100) if prev_close else 0.0
                volume = int(daily.volume) if daily and daily.volume else 0

                quotes.append(StockQuote(
                    ticker=ticker,
                    price=price,
                    change=change,
                    change_pct=change_pct,
                    volume=volume,
                    market_cap=None,
                    timestamp=trade.timestamp if trade else datetime.now(timezone.utc),
                    source=_SOURCE,
                    delayed=False,
                ))
            except Exception:
                continue

        quotes.sort(key=lambda q: q.change_pct, reverse=True)
        gainers = [q for q in quotes if q.change_pct > 0][:limit]
        losers = sorted([q for q in quotes if q.change_pct < 0], key=lambda q: q.change_pct)[:limit]
        return {"gainers": gainers, "losers": losers}

    async def get_news(self, ticker: str, limit: int = 10) -> list[NewsArticle]:
        """Fetch Benzinga news articles for a specific ticker via Alpaca."""
        try:
            from alpaca.data.requests import NewsRequest

            client = self._get_news_client()
            req = NewsRequest(symbols=ticker, limit=limit, sort="desc")
            news_set = client.get_news(req)
            # NewsSet wraps results in .data['news']
            news = news_set.data.get("news", []) if hasattr(news_set, "data") else list(news_set)

            articles = []
            for item in (news or []):
                try:
                    articles.append(NewsArticle(
                        title=item.headline or "",
                        summary=item.summary or "",
                        url=item.url or "",
                        published_at=item.created_at if item.created_at else datetime.now(timezone.utc),
                        source=_SOURCE,
                        ticker=ticker.upper(),
                        author=item.author or None,
                        image_url=item.images[0].url if item.images else None,
                    ))
                except Exception:
                    continue

            return articles[:limit]

        except Exception as e:
            logger.error("Alpaca get_news(%s) failed: %s", ticker, e)
            return []

    async def get_market_news(self, limit: int = 20) -> list[NewsArticle]:
        """Fetch broad market news (no specific ticker)."""
        try:
            from alpaca.data.requests import NewsRequest

            client = self._get_news_client()
            req = NewsRequest(limit=limit, sort="desc")
            news_set = client.get_news(req)
            news = news_set.data.get("news", []) if hasattr(news_set, "data") else list(news_set)

            articles = []
            for item in (news or []):
                try:
                    articles.append(NewsArticle(
                        title=item.headline or "",
                        summary=item.summary or "",
                        url=item.url or "",
                        published_at=item.created_at if item.created_at else datetime.now(timezone.utc),
                        source=_SOURCE,
                        ticker=None,
                        author=item.author or None,
                        image_url=item.images[0].url if item.images else None,
                    ))
                except Exception:
                    continue

            return articles[:limit]

        except Exception as e:
            logger.error("Alpaca get_market_news failed: %s", e)
            return []

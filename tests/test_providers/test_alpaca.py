"""Unit tests for AlpacaProvider — all API calls mocked."""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.providers.alpaca import AlpacaProvider
from src.providers.base import AuthError


# ─── Construction ─────────────────────────────────────────────────────────────

def test_requires_api_key():
    with pytest.raises(AuthError):
        AlpacaProvider("", "secret")


def test_requires_secret_key():
    with pytest.raises(AuthError):
        AlpacaProvider("key", "")


# ─── get_quote ────────────────────────────────────────────────────────────────

def _mock_snapshot(price: float, prev_close: float, volume: int):
    trade = MagicMock()
    trade.price = price
    trade.timestamp = datetime.now(timezone.utc)

    daily = MagicMock()
    daily.close = price
    daily.volume = volume

    prev_bar = MagicMock()
    prev_bar.close = prev_close

    snap = MagicMock()
    snap.latest_trade = trade
    snap.daily_bar = daily
    snap.previous_daily_bar = prev_bar
    return snap


@pytest.mark.asyncio
async def test_get_quote_success():
    provider = AlpacaProvider("key", "secret")

    with patch.object(provider, "_get_stock_client") as mock_client_fn:
        mock_client = MagicMock()
        mock_client_fn.return_value = mock_client

        snap = _mock_snapshot(135.20, 130.00, 50_000_000)
        mock_client.get_stock_snapshot.return_value = {"NVDA": snap}

        result = await provider.get_quote("NVDA")

    assert result is not None
    assert result.ticker == "NVDA"
    assert result.price == pytest.approx(135.20)
    assert result.source == "alpaca"
    assert result.delayed is False
    assert result.change_pct == pytest.approx((135.20 - 130.00) / 130.00 * 100)


@pytest.mark.asyncio
async def test_get_quote_missing_ticker_returns_none():
    provider = AlpacaProvider("key", "secret")

    with patch.object(provider, "_get_stock_client") as mock_client_fn:
        mock_client = MagicMock()
        mock_client_fn.return_value = mock_client
        mock_client.get_stock_snapshot.return_value = {}  # ticker not in response

        result = await provider.get_quote("FAKE")

    assert result is None


@pytest.mark.asyncio
async def test_get_quote_exception_returns_none():
    provider = AlpacaProvider("key", "secret")

    with patch.object(provider, "_get_stock_client") as mock_client_fn:
        mock_client = MagicMock()
        mock_client_fn.return_value = mock_client
        mock_client.get_stock_snapshot.side_effect = RuntimeError("network error")

        result = await provider.get_quote("NVDA")

    assert result is None


# ─── get_news ─────────────────────────────────────────────────────────────────

def _mock_news_item(headline: str, summary: str, url: str):
    item = MagicMock()
    item.headline = headline
    item.summary = summary
    item.url = url
    item.author = "Reuters"
    item.created_at = datetime.now(timezone.utc)
    item.images = []
    return item


def _wrap_news(items):
    """Wrap a list of news items into a mock NewsSet (data={'news': [...]})."""
    news_set = MagicMock()
    news_set.data = {"news": items}
    return news_set


@pytest.mark.asyncio
async def test_get_news_returns_articles():
    provider = AlpacaProvider("key", "secret")

    mock_items = [
        _mock_news_item("NVDA beats earnings", "Nvidia beat EPS estimates by 20%.", "https://example.com/1"),
        _mock_news_item("NVDA new GPU announced", "Next gen GPU announced at GTC.", "https://example.com/2"),
    ]

    with patch.object(provider, "_get_news_client") as mock_client_fn:
        mock_client = MagicMock()
        mock_client_fn.return_value = mock_client
        mock_client.get_news.return_value = _wrap_news(mock_items)

        articles = await provider.get_news("NVDA", limit=5)

    assert len(articles) == 2
    assert articles[0].title == "NVDA beats earnings"
    assert articles[0].ticker == "NVDA"
    assert articles[0].source == "alpaca"
    assert articles[0].author == "Reuters"


@pytest.mark.asyncio
async def test_get_news_respects_limit():
    provider = AlpacaProvider("key", "secret")

    mock_items = [
        _mock_news_item(f"Headline {i}", f"Summary {i}", f"https://example.com/{i}")
        for i in range(20)
    ]

    with patch.object(provider, "_get_news_client") as mock_client_fn:
        mock_client = MagicMock()
        mock_client_fn.return_value = mock_client
        mock_client.get_news.return_value = _wrap_news(mock_items)

        articles = await provider.get_news("NVDA", limit=3)

    assert len(articles) == 3


@pytest.mark.asyncio
async def test_get_news_exception_returns_empty():
    provider = AlpacaProvider("key", "secret")

    with patch.object(provider, "_get_news_client") as mock_client_fn:
        mock_client = MagicMock()
        mock_client_fn.return_value = mock_client
        mock_client.get_news.side_effect = RuntimeError("API down")

        articles = await provider.get_news("NVDA")

    assert articles == []


# ─── get_market_news ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_market_news_ticker_is_none():
    provider = AlpacaProvider("key", "secret")

    mock_items = [_mock_news_item("Market rally", "S&P 500 up 2%.", "https://example.com/m1")]

    with patch.object(provider, "_get_news_client") as mock_client_fn:
        mock_client = MagicMock()
        mock_client_fn.return_value = mock_client
        mock_client.get_news.return_value = _wrap_news(mock_items)

        articles = await provider.get_market_news(5)

    assert len(articles) == 1
    assert articles[0].ticker is None  # broad market, no specific ticker


# ─── get_top_movers ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_top_movers_screener_success():
    provider = AlpacaProvider("key", "secret")

    mock_response = {
        "gainers": [
            {"symbol": "NVDA", "price": 135.0, "change": 5.0, "change_percent": 3.8, "volume": 50_000_000},
            {"symbol": "AMD",  "price":  90.0, "change": 3.0, "change_percent": 3.4, "volume": 30_000_000},
        ],
        "losers": [
            {"symbol": "INTC", "price": 20.0, "change": -2.0, "change_percent": -9.1, "volume": 40_000_000},
        ],
    }

    with patch("httpx.AsyncClient") as mock_http:
        mock_resp = MagicMock()
        mock_resp.json.return_value = mock_response
        mock_resp.raise_for_status = MagicMock()
        mock_inner = MagicMock()
        mock_inner.get = AsyncMock(return_value=mock_resp)
        mock_http.return_value.__aenter__ = AsyncMock(return_value=mock_inner)
        mock_http.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await provider._get_movers_via_screener(10)

    assert len(result["gainers"]) == 2
    assert result["gainers"][0].ticker == "NVDA"
    assert result["gainers"][0].change_pct == pytest.approx(3.8)
    assert len(result["losers"]) == 1
    assert result["losers"][0].ticker == "INTC"

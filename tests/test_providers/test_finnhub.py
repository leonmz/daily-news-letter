"""Unit tests for FinnhubProvider — all API calls mocked."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.providers.finnhub import FinnhubProvider
from src.providers.base import AuthError


# ─── Construction ─────────────────────────────────────────────────────────────

def test_requires_api_key():
    with pytest.raises(AuthError):
        FinnhubProvider("")


# ─── get_fundamentals ─────────────────────────────────────────────────────────

def _mock_profile():
    return {
        "name": "NVIDIA Corporation",
        "finnhubIndustry": "Technology",
        "marketCapitalization": 3_200_000,  # millions → $3.2T
        "country": "US",
        "currency": "USD",
        "exchange": "NASDAQ",
        "ipo": "1999-01-22",
        "logo": "https://example.com/nvda.png",
        "weburl": "https://www.nvidia.com",
    }


@pytest.mark.asyncio
async def test_get_fundamentals_success():
    provider = FinnhubProvider("testkey")

    with patch.object(provider, "_get_client") as mock_fn:
        client = MagicMock()
        mock_fn.return_value = client
        client.company_profile2.return_value = _mock_profile()
        client.company_peers.return_value = ["AMD", "INTC"]

        result = await provider.get_fundamentals("NVDA")

    assert result is not None
    assert result["ticker"] == "NVDA"
    assert result["name"] == "NVIDIA Corporation"
    assert result["sector"] == "Technology"
    assert result["market_cap_b"] == pytest.approx(3200.0)
    assert result["peers"] == ["AMD", "INTC"]
    assert result["source"] == "finnhub"


@pytest.mark.asyncio
async def test_get_fundamentals_empty_profile_returns_none():
    provider = FinnhubProvider("testkey")

    with patch.object(provider, "_get_client") as mock_fn:
        client = MagicMock()
        mock_fn.return_value = client
        client.company_profile2.return_value = {}

        result = await provider.get_fundamentals("FAKE")

    assert result is None


@pytest.mark.asyncio
async def test_get_fundamentals_exception_returns_none():
    provider = FinnhubProvider("testkey")

    with patch.object(provider, "_get_client") as mock_fn:
        client = MagicMock()
        mock_fn.return_value = client
        client.company_profile2.side_effect = RuntimeError("rate limit")

        result = await provider.get_fundamentals("NVDA")

    assert result is None


# ─── get_earnings_calendar ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_earnings_calendar_returns_events():
    provider = FinnhubProvider("testkey")

    mock_data = {
        "earningsCalendar": [
            {
                "symbol": "AAPL", "name": "Apple Inc.", "date": "2026-04-30",
                "hour": "amc", "epsEstimate": 1.52, "revenueEstimate": 95_000_000_000,
            },
            {
                "symbol": "MSFT", "name": "Microsoft", "date": "2026-04-29",
                "hour": "amc", "epsEstimate": 3.20, "revenueEstimate": 65_000_000_000,
            },
        ]
    }

    with patch.object(provider, "_get_client") as mock_fn:
        client = MagicMock()
        mock_fn.return_value = client
        client.earnings_calendar.return_value = mock_data

        events = await provider.get_earnings_calendar("2026-04-12", "2026-04-26")

    assert len(events) == 2
    assert events[0]["ticker"] == "AAPL"
    assert events[0]["eps_estimate"] == pytest.approx(1.52)
    assert events[0]["source"] == "finnhub"


@pytest.mark.asyncio
async def test_get_earnings_calendar_exception_returns_empty():
    provider = FinnhubProvider("testkey")

    with patch.object(provider, "_get_client") as mock_fn:
        client = MagicMock()
        mock_fn.return_value = client
        client.earnings_calendar.side_effect = RuntimeError("api error")

        events = await provider.get_earnings_calendar("2026-04-12", "2026-04-26")

    assert events == []


# ─── get_recommendations ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_recommendations_success():
    provider = FinnhubProvider("testkey")

    mock_trend = [
        {
            "strongBuy": 20, "buy": 15, "hold": 5, "sell": 1, "strongSell": 0,
            "period": "2026-04-01",
        }
    ]
    mock_target = {
        "targetHigh": 200.0,
        "targetLow": 120.0,
        "targetMean": 165.0,
        "targetMedian": 162.0,
    }

    with patch.object(provider, "_get_client") as mock_fn:
        client = MagicMock()
        mock_fn.return_value = client
        client.recommendation_trends.return_value = mock_trend
        client.price_target.return_value = mock_target

        rec = await provider.get_recommendations("NVDA")

    assert rec is not None
    assert rec["total_analysts"] == 41
    assert rec["strong_buy"] == 20
    assert rec["target_mean"] == pytest.approx(165.0)
    assert rec["source"] == "finnhub"


@pytest.mark.asyncio
async def test_get_recommendations_no_data_returns_none():
    provider = FinnhubProvider("testkey")

    with patch.object(provider, "_get_client") as mock_fn:
        client = MagicMock()
        mock_fn.return_value = client
        client.recommendation_trends.return_value = []
        client.price_target.return_value = {}

        rec = await provider.get_recommendations("FAKE")

    assert rec is None


# ─── get_news ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_news_returns_articles_with_sentiment():
    provider = FinnhubProvider("testkey")

    mock_news = [
        {
            "headline": "NVDA revenue beats",
            "summary": "Nvidia reported record revenue.",
            "url": "https://example.com/1",
            "datetime": int(datetime(2026, 4, 10, tzinfo=timezone.utc).timestamp()),
            "image": "",
        }
    ]
    mock_sentiment = {
        "buzz": {"articlesInLastWeek": 5},
        "sentiment": {"bullishPercent": 0.75},
    }

    with patch.object(provider, "_get_client") as mock_fn:
        client = MagicMock()
        mock_fn.return_value = client
        client.company_news.return_value = mock_news
        client.news_sentiment.return_value = mock_sentiment

        articles = await provider.get_news("NVDA", limit=5)

    assert len(articles) == 1
    assert articles[0].title == "NVDA revenue beats"
    assert articles[0].sentiment == "positive"
    assert articles[0].source == "finnhub"
    assert articles[0].ticker == "NVDA"


@pytest.mark.asyncio
async def test_get_news_exception_returns_empty():
    provider = FinnhubProvider("testkey")

    with patch.object(provider, "_get_client") as mock_fn:
        client = MagicMock()
        mock_fn.return_value = client
        client.company_news.side_effect = RuntimeError("network error")

        articles = await provider.get_news("NVDA")

    assert articles == []

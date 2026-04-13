"""Tests that cache correctly round-trips typed dataclasses (not plain dicts)."""

import os
import tempfile
from datetime import datetime, timezone

import pytest

from src.models.market import StockQuote
from src.models.news import NewsArticle
from src.storage.cache import Cache


@pytest.fixture
def tmp_cache():
    with tempfile.TemporaryDirectory() as d:
        yield Cache(db_path=os.path.join(d, "test.db"))


@pytest.mark.asyncio
async def test_stockquote_roundtrip(tmp_cache):
    """StockQuote stored and retrieved from cache must be a StockQuote, not a dict."""
    original = StockQuote(
        ticker="NVDA",
        price=135.20,
        change=5.20,
        change_pct=4.01,
        volume=50_000_000,
        market_cap=3300.0,
        timestamp=datetime(2026, 4, 12, 15, 30, tzinfo=timezone.utc),
        source="alpaca",
        delayed=False,
        currency="USD",
        company_name="NVIDIA Corporation",
        sector="Technology",
    )

    await tmp_cache.set("quote:NVDA", original, ttl_seconds=300)
    result = await tmp_cache.get("quote:NVDA")

    assert isinstance(result, StockQuote), f"Expected StockQuote, got {type(result)}"
    assert result.ticker == "NVDA"
    assert result.price == pytest.approx(135.20)
    assert result.source == "alpaca"
    assert result.delayed is False
    assert result.timestamp == original.timestamp


@pytest.mark.asyncio
async def test_news_article_list_roundtrip(tmp_cache):
    """List[NewsArticle] must be reconstructed as a list of NewsArticle objects."""
    articles = [
        NewsArticle(
            title=f"Title {i}",
            summary=f"Summary {i}",
            url=f"https://example.com/{i}",
            published_at=datetime(2026, 4, 12, tzinfo=timezone.utc),
            source="alpaca",
            ticker="NVDA",
        )
        for i in range(3)
    ]

    await tmp_cache.set("news:NVDA:3", articles, ttl_seconds=900)
    result = await tmp_cache.get("news:NVDA:3")

    assert isinstance(result, list)
    assert len(result) == 3
    for item in result:
        assert isinstance(item, NewsArticle), f"Expected NewsArticle, got {type(item)}"
        assert item.source == "alpaca"
        assert item.ticker == "NVDA"


@pytest.mark.asyncio
async def test_cache_miss_returns_none(tmp_cache):
    result = await tmp_cache.get("nonexistent:key")
    assert result is None


@pytest.mark.asyncio
async def test_expired_entry_returns_none(tmp_cache):
    quote = StockQuote(
        ticker="AAPL", price=198.0, change=1.0, change_pct=0.5,
        volume=10_000_000, market_cap=3000.0,
        timestamp=datetime.now(timezone.utc), source="test",
    )
    await tmp_cache.set("quote:AAPL", quote, ttl_seconds=-1)  # already expired
    result = await tmp_cache.get("quote:AAPL")
    assert result is None


@pytest.mark.asyncio
async def test_plain_dict_roundtrip(tmp_cache):
    """Plain dicts (e.g. from finnhub fundamentals) should come back as dicts."""
    data = {"ticker": "NVDA", "market_cap_b": 3300.0, "sector": "Technology"}
    await tmp_cache.set("fundamentals:NVDA", data, ttl_seconds=300)
    result = await tmp_cache.get("fundamentals:NVDA")
    assert isinstance(result, dict)
    assert result["ticker"] == "NVDA"
    assert result["market_cap_b"] == pytest.approx(3300.0)

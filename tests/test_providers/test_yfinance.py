"""Unit tests for YFinanceProvider — all yfinance calls mocked."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, PropertyMock

import pandas as pd
import pytest

from src.providers.yfinance_provider import YFinanceProvider


# ─── get_quote ────────────────────────────────────────────────────────────────

def _mock_ticker(price: float, prev_close: float, volume: int, market_cap: float):
    ticker = MagicMock()

    # fast_info
    fast_info = MagicMock()
    fast_info.last_price = price
    fast_info.previous_close = prev_close
    fast_info.three_month_average_volume = volume
    fast_info.market_cap = market_cap
    fast_info.currency = "USD"
    ticker.fast_info = fast_info

    # info
    ticker.info = {
        "longName": "NVIDIA Corporation",
        "sector": "Technology",
        "currentPrice": price,
        "previousClose": prev_close,
    }

    # history (for volume)
    hist = pd.DataFrame({"Volume": [volume]}, index=[datetime.now(timezone.utc)])
    ticker.history.return_value = hist

    return ticker


@pytest.mark.asyncio
async def test_get_quote_success():
    provider = YFinanceProvider()

    mock_ticker = _mock_ticker(
        price=135.18, prev_close=130.00, volume=45_000_000, market_cap=3_300_000_000_000
    )

    with patch("yfinance.Ticker", return_value=mock_ticker):
        result = await provider.get_quote("NVDA")

    assert result is not None
    assert result.ticker == "NVDA"
    assert result.price == pytest.approx(135.18)
    assert result.delayed is True
    assert result.source == "yfinance"
    assert result.market_cap == pytest.approx(3300.0, rel=0.01)  # in billions
    assert result.company_name == "NVIDIA Corporation"
    assert result.sector == "Technology"


@pytest.mark.asyncio
async def test_get_quote_no_price_returns_none():
    provider = YFinanceProvider()

    mock_ticker = MagicMock()
    fast_info = MagicMock()
    fast_info.last_price = None
    mock_ticker.fast_info = fast_info
    mock_ticker.info = {"currentPrice": None, "regularMarketPrice": None}

    with patch("yfinance.Ticker", return_value=mock_ticker):
        result = await provider.get_quote("FAKE")

    assert result is None


@pytest.mark.asyncio
async def test_get_quote_exception_returns_none():
    provider = YFinanceProvider()

    with patch("yfinance.Ticker", side_effect=RuntimeError("yfinance down")):
        result = await provider.get_quote("NVDA")

    assert result is None


# ─── get_historical ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_historical_returns_dataframe():
    provider = YFinanceProvider()

    mock_df = pd.DataFrame(
        {"Open": [100, 101], "High": [102, 103], "Low": [99, 100], "Close": [101, 102], "Volume": [1_000_000, 1_100_000]},
        index=pd.date_range("2016-01-01", periods=2, freq="D"),
    )

    mock_ticker = MagicMock()
    mock_ticker.history.return_value = mock_df

    with patch("yfinance.Ticker", return_value=mock_ticker):
        df = await provider.get_historical("SPY", "2016-01-01", "2016-01-03")

    assert df is not None
    assert len(df) == 2
    assert "Close" in df.columns


@pytest.mark.asyncio
async def test_get_historical_empty_returns_none():
    provider = YFinanceProvider()

    mock_ticker = MagicMock()
    mock_ticker.history.return_value = pd.DataFrame()

    with patch("yfinance.Ticker", return_value=mock_ticker):
        result = await provider.get_historical("FAKE", "2020-01-01", "2020-01-02")

    assert result is None


# ─── get_expirations ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_expirations_returns_dates():
    provider = YFinanceProvider()

    mock_ticker = MagicMock()
    mock_ticker.options = ("2026-04-18", "2026-04-25", "2026-05-02")

    with patch("yfinance.Ticker", return_value=mock_ticker):
        expirations = await provider.get_expirations("SPY")

    assert len(expirations) == 3
    assert "2026-04-18" in expirations


# ─── get_option_chain ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_option_chain_success():
    provider = YFinanceProvider()

    calls_df = pd.DataFrame({
        "strike": [500.0, 510.0],
        "lastPrice": [5.0, 3.0],
        "bid": [4.9, 2.9],
        "ask": [5.1, 3.1],
        "volume": [1000, 500],
        "openInterest": [5000, 3000],
        "impliedVolatility": [0.20, 0.22],
    })
    puts_df = pd.DataFrame({
        "strike": [490.0],
        "lastPrice": [4.0],
        "bid": [3.9],
        "ask": [4.1],
        "volume": [800],
        "openInterest": [4000],
        "impliedVolatility": [0.21],
    })

    chain = MagicMock()
    chain.calls = calls_df
    chain.puts = puts_df

    mock_ticker = MagicMock()
    mock_ticker.options = ("2026-04-18", "2026-04-25")
    mock_ticker.option_chain.return_value = chain

    with patch("yfinance.Ticker", return_value=mock_ticker):
        snapshot = await provider.get_option_chain("SPY", "2026-04-18")

    assert snapshot is not None
    assert snapshot.ticker == "SPY"
    assert len(snapshot.calls) == 2
    assert len(snapshot.puts) == 1
    assert snapshot.total_contracts == 3
    assert snapshot.calls[0].strike == 500.0
    assert snapshot.calls[0].implied_volatility == pytest.approx(0.20)
    assert snapshot.source == "yfinance"


@pytest.mark.asyncio
async def test_get_option_chain_no_options_returns_none():
    provider = YFinanceProvider()

    mock_ticker = MagicMock()
    mock_ticker.options = ()  # no options

    with patch("yfinance.Ticker", return_value=mock_ticker):
        result = await provider.get_option_chain("FAKE")

    assert result is None


# ─── get_top_movers ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_top_movers_filters_small_caps():
    """Stocks below min_market_cap_b should be excluded."""
    provider = YFinanceProvider(min_market_cap_b=10.0, min_volume=1_000_000)

    mock_gainers = {
        "quotes": [
            # Big cap — should pass
            {
                "symbol": "NVDA",
                "marketCap": 3_300_000_000_000,
                "regularMarketPrice": 135.0,
                "regularMarketChange": 5.0,
                "regularMarketChangePercent": 3.8,
                "regularMarketVolume": 50_000_000,
            },
            # Small cap — should be filtered out
            {
                "symbol": "TINY",
                "marketCap": 500_000_000,  # $500M < $10B
                "regularMarketPrice": 5.0,
                "regularMarketChange": 2.0,
                "regularMarketChangePercent": 66.0,
                "regularMarketVolume": 5_000_000,
            },
        ]
    }
    mock_losers = {"quotes": []}

    def mock_screen(screen_name, **kwargs):
        if screen_name == "day_gainers":
            return mock_gainers
        return mock_losers

    with patch("yfinance.screen", side_effect=mock_screen):
        result = await provider.get_top_movers(10)

    gainers = result["gainers"]
    assert len(gainers) == 1
    assert gainers[0].ticker == "NVDA"
    # TINY must not appear
    assert all(g.ticker != "TINY" for g in gainers)


@pytest.mark.asyncio
async def test_get_top_movers_exception_returns_empty():
    provider = YFinanceProvider()

    with patch("yfinance.screen", side_effect=RuntimeError("screener down")):
        result = await provider.get_top_movers()

    assert result["gainers"] == []
    assert result["losers"] == []

"""Data loaders for backtesting — fetch historical OHLCV via yfinance."""

from __future__ import annotations

import pandas as pd
import yfinance as yf


def load_ticker_data(
    ticker: str,
    start: str = "2002-01-01",
    end: str = "2025-12-31",
) -> pd.DataFrame:
    """Load daily OHLCV for any ticker from yfinance.

    Args:
        ticker: Any valid yfinance symbol (e.g. "SPY", "QQQ", "NVDA", "AAPL").
        start: Start date string, inclusive.
        end: End date string, inclusive.

    Returns:
        DataFrame with columns [open, close, high, low, volume], DatetimeIndex.

    Raises:
        ValueError: If no data is returned for the ticker/date range.
    """
    df = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False)
    if df.empty:
        raise ValueError(f"No data returned for {ticker} ({start} – {end})")
    # yfinance may return MultiIndex columns; flatten to lowercase strings
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0].lower() for c in df.columns]
    else:
        df.columns = [c.lower() for c in df.columns]
    df.index = pd.to_datetime(df.index)
    available = [c for c in ["open", "close", "high", "low", "volume"] if c in df.columns]
    return df[available]


def load_spy_data(start: str = "2002-01-01", end: str = "2025-12-31") -> pd.DataFrame:
    """Load SPY daily OHLCV from yfinance."""
    return load_ticker_data("SPY", start, end)


def load_qqq_data(start: str = "2002-01-01", end: str = "2025-12-31") -> pd.DataFrame:
    """Load QQQ daily OHLCV from yfinance."""
    return load_ticker_data("QQQ", start, end)


def load_vix_data(start: str = "2002-01-01", end: str = "2025-12-31") -> pd.DataFrame:
    """Load VIX daily close from yfinance (^VIX).

    Returns:
        DataFrame with a 'close' column, DatetimeIndex.
    """
    return load_ticker_data("^VIX", start, end)[["close"]]

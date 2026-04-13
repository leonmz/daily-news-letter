"""Data loaders for backtesting — fetch historical OHLCV via yfinance."""

from __future__ import annotations

import pandas as pd
import yfinance as yf


def _download(ticker: str, start: str, end: str) -> pd.DataFrame:
    """Download daily OHLCV and normalise column names to lowercase."""
    df = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False)
    if df.empty:
        raise ValueError(f"No data returned for {ticker} ({start} – {end})")
    df.columns = [c.lower() if isinstance(c, str) else c[0].lower() for c in df.columns]
    df.index = pd.to_datetime(df.index)
    return df[["open", "close", "high", "low", "volume"]]


def load_spy_data(start: str = "2002-01-01", end: str = "2025-12-31") -> pd.DataFrame:
    """Load SPY daily OHLCV from yfinance.

    Returns:
        DataFrame with columns [open, close, high, low, volume], DatetimeIndex.
    """
    return _download("SPY", start, end)


def load_qqq_data(start: str = "2002-01-01", end: str = "2025-12-31") -> pd.DataFrame:
    """Load QQQ daily OHLCV from yfinance."""
    return _download("QQQ", start, end)


def load_vix_data(start: str = "2002-01-01", end: str = "2025-12-31") -> pd.DataFrame:
    """Load VIX daily data from yfinance (^VIX).

    Returns:
        DataFrame with a 'close' column, DatetimeIndex.
    """
    df = yf.download("^VIX", start=start, end=end, auto_adjust=True, progress=False)
    if df.empty:
        raise ValueError(f"No VIX data returned ({start} – {end})")
    df.columns = [c.lower() if isinstance(c, str) else c[0].lower() for c in df.columns]
    df.index = pd.to_datetime(df.index)
    return df[["close"]]

"""Data loaders for backtesting — fetch historical OHLCV via yfinance."""

from __future__ import annotations

import warnings

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


# ---------------------------------------------------------------------------
# VIX6M: CBOE 6-month implied volatility index
# ---------------------------------------------------------------------------

# Regression coefficients fitted on 2008-2025 overlap of VIX and VIX6M.
# VIX6M = _VIX6M_SLOPE * VIX + _VIX6M_INTERCEPT  (R²=0.88)
_VIX6M_SLOPE = 0.7161
_VIX6M_INTERCEPT = 8.6406


def load_vix6m_data(start: str = "2002-01-01", end: str = "2025-12-31") -> pd.DataFrame:
    """Load CBOE 6-month VIX (^VIX6M) with regression fallback for pre-2008.

    ^VIX6M is available from 2008-01-02.  For dates before that, we synthesize
    VIX6M from ^VIX using a linear regression fitted on the 2008-2025 overlap:
        VIX6M ≈ 0.716 × VIX + 8.64

    Returns:
        DataFrame with a 'close' column (VIX6M in percentage points, e.g. 22.5),
        DatetimeIndex covering the full requested range.
    """
    vix = load_vix_data(start=start, end=end)  # always available from 2002

    try:
        vix6m_raw = load_ticker_data("^VIX6M", start=start, end=end)[["close"]]
    except ValueError:
        # ^VIX6M genuinely has no data for this range
        vix6m_raw = pd.DataFrame(columns=["close"])
    except Exception as exc:
        warnings.warn(f"VIX6M fetch failed ({exc}); falling back to VIX regression")
        vix6m_raw = pd.DataFrame(columns=["close"])

    if vix6m_raw.empty:
        # Full regression fallback
        synth = vix.copy()
        synth["close"] = _VIX6M_SLOPE * vix["close"] + _VIX6M_INTERCEPT
        return synth

    # Merge: use real VIX6M where available, regression-synthesized elsewhere
    vix6m_aligned = vix6m_raw["close"].reindex(vix.index)
    vix_vals = vix["close"]

    # Fill gaps (pre-2008 + any missing dates) with regression
    synth_vals = _VIX6M_SLOPE * vix_vals + _VIX6M_INTERCEPT
    filled = vix6m_aligned.fillna(synth_vals)

    return pd.DataFrame({"close": filled}, index=vix.index)

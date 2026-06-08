"""SPY/QQQ moving-average comparison (price vs N SMAs).

Pure compute. Adapted from the daily-news-letter newsletter module, generalised
so the SMA periods are caller-supplied (this project tracks the short/mid/long
set 5/10/50/200 rather than the digest's 50/100/200/250).

The SMA200 cross is the only line with a backtested timing edge; the others are
shown for trend-structure context. This module does no timing on top of them.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

DEFAULT_SMA_PERIODS = [5, 10, 50, 200]


@dataclass
class MALevel:
    period: int
    value: float
    deviation_pct: float
    above: bool


@dataclass
class MAComparison:
    ticker: str
    price: float
    levels: list[MALevel]


def compute_ma_comparison(
    ticker: str,
    df: pd.DataFrame,
    periods: list[int] | None = None,
) -> MAComparison | None:
    """Compute price vs each SMA from an OHLCV DataFrame.

    Returns None if there isn't enough history for the longest SMA, or the
    frame has no usable Close column. Pure function — no I/O, fully testable
    with synthetic data.
    """
    if periods is None:
        periods = DEFAULT_SMA_PERIODS
    if df is None or df.empty or "Close" not in df.columns:
        return None

    close = df["Close"].dropna()
    if len(close) < max(periods) + 1:
        return None

    price = float(close.iloc[-1])
    levels: list[MALevel] = []
    for period in periods:
        sma_v = float(close.rolling(period).mean().iloc[-1])
        if sma_v == 0:
            continue
        deviation = (price - sma_v) / sma_v * 100
        levels.append(
            MALevel(
                period=period,
                value=sma_v,
                deviation_pct=deviation,
                above=price >= sma_v,
            )
        )

    if not levels:
        return None

    return MAComparison(ticker=ticker.upper(), price=price, levels=levels)

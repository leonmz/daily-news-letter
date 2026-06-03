"""QQQ/SPY moving-average comparison snapshot for the daily digest.

Shows SPY and QQQ each against four SMAs (50/100/200/250) with the
percentage deviation and above/below state.

The SMA200 cross is the only line with a backtested timing edge (see
backtest/ + scripts/ — 19-year QLD study + 60/180/360-day stretch-overlay
diagnostics, which confirmed momentum dominates and no mean-reversion
overlay helps). The other three SMAs are shown purely to give a full
short/mid/long-term trend-structure view; this module does not attempt
any timing on top of them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd


SMA_PERIODS = [50, 100, 200, 250]
DEFAULT_TICKERS = ["SPY", "QQQ"]
HISTORY_DAYS = 500  # ~350 trading days, leaves ~100d headroom over SMA250


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


def compute_ma_comparison(ticker: str, df: pd.DataFrame) -> Optional[MAComparison]:
    """Compute price vs each SMA in SMA_PERIODS from an OHLCV DataFrame.

    Returns None if there isn't enough history for the longest SMA.
    Pure function — no I/O, fully testable with synthetic data.
    """
    if df is None or df.empty or "Close" not in df.columns:
        return None
    close = df["Close"].dropna()
    if len(close) < max(SMA_PERIODS) + 1:
        return None

    price = float(close.iloc[-1])
    levels: list[MALevel] = []
    for period in SMA_PERIODS:
        sma_v = float(close.rolling(period).mean().iloc[-1])
        if sma_v == 0:
            continue
        deviation = (price - sma_v) / sma_v * 100
        levels.append(
            MALevel(
                period=period,
                value=sma_v,
                deviation_pct=deviation,
                above=price > sma_v,
            )
        )

    if not levels:
        return None

    return MAComparison(ticker=ticker.upper(), price=price, levels=levels)


def _fmt_dev(pct: float) -> str:
    return f"+{pct:.1f}%" if pct >= 0 else f"{pct:.1f}%"


def format_ma_section(comparisons: list[MAComparison]) -> str:
    """Render MA comparisons as a Markdown section. Empty list → empty string."""
    if not comparisons:
        return ""
    lines = ["## 📈 SMA Comparison"]
    for c in comparisons:
        lines.append(f"**{c.ticker}** ${c.price:.2f}")
        for lv in c.levels:
            emoji = "🟢" if lv.above else "🔴"
            label = f"SMA{lv.period}".ljust(6)
            lines.append(f"  {emoji} {label} ${lv.value:.2f}  {_fmt_dev(lv.deviation_pct)}")
    return "\n".join(lines)


def fetch_ma_comparisons(tickers: Optional[list[str]] = None) -> list[MAComparison]:
    """Pull ~500 days of OHLCV via yfinance, compute MA comparison per ticker.

    Per-ticker errors are swallowed (returns partial list); a global failure
    returns []. Network I/O — do not call in unit tests.
    """
    if tickers is None:
        tickers = DEFAULT_TICKERS

    try:
        import yfinance as yf
    except ImportError:
        return []

    end = datetime.now().date()
    start = end - timedelta(days=HISTORY_DAYS)
    results: list[MAComparison] = []
    for ticker in tickers:
        try:
            df = yf.Ticker(ticker).history(
                start=start.isoformat(),
                end=end.isoformat(),
                auto_adjust=True,
            )
            comparison = compute_ma_comparison(ticker, df)
            if comparison is not None:
                results.append(comparison)
        except Exception:
            continue
    return results

"""QQQ/SPY 200-day SMA trend snapshot for the daily digest.

Strategy validated via 19-year QLD backtest (see backtest/ + scripts/):
  above SMA200 → hold leveraged ETF (QLD for QQQ, SSO for SPY)
  below SMA200 → hold defensive (SHY 1-3yr Treasuries)

Stretch-overlay tests at 60/180/360-day horizons confirmed no usable
mean-reversion signal — momentum dominates. So this module only reports
the current state; it does NOT attempt any fancy timing on top.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

import pandas as pd


SMA_PERIOD = 200
LEVERAGED_ETF = {"QQQ": "QLD", "SPY": "SSO"}
DEFENSIVE_ETF = "SHY"
DEFAULT_TICKERS = ["QQQ", "SPY"]
HISTORY_DAYS = 400  # ~280 trading days, enough for SMA200 + cross detection


@dataclass
class TrendState:
    ticker: str
    price: float
    sma200: float
    deviation_pct: float
    state: str  # "BULL" or "BEAR"
    last_cross_date: Optional[date]
    days_in_state: Optional[int]


def compute_trend_state(ticker: str, df: pd.DataFrame) -> Optional[TrendState]:
    """Compute current SMA200 regime from an OHLCV DataFrame.

    Returns None when there isn't enough history to form an SMA200 value.
    Pure function — no I/O, fully testable with synthetic data.
    """
    if df is None or df.empty or "Close" not in df.columns:
        return None
    close = df["Close"].dropna()
    if len(close) < SMA_PERIOD + 1:
        return None

    sma = close.rolling(SMA_PERIOD).mean()
    above = (close > sma).astype("Int64")
    valid = above.dropna()
    if valid.empty:
        return None

    last_cross_date: Optional[date] = None
    days_in_state: Optional[int] = None
    for i in range(len(valid) - 1, 0, -1):
        if valid.iloc[i] != valid.iloc[i - 1]:
            cross_idx = valid.index[i]
            last_cross_date = cross_idx.date() if hasattr(cross_idx, "date") else cross_idx
            days_in_state = (valid.index[-1] - cross_idx).days
            break

    price = float(close.iloc[-1])
    sma_v = float(sma.iloc[-1])
    deviation = (price - sma_v) / sma_v * 100

    return TrendState(
        ticker=ticker.upper(),
        price=price,
        sma200=sma_v,
        deviation_pct=deviation,
        state="BULL" if price > sma_v else "BEAR",
        last_cross_date=last_cross_date,
        days_in_state=days_in_state,
    )


def _recommendation(s: TrendState) -> str:
    if s.state == "BULL":
        leveraged = LEVERAGED_ETF.get(s.ticker)
        return f"hold {leveraged}" if leveraged else "bullish trend"
    return f"hold {DEFENSIVE_ETF}"


def format_trend_section(states: list[TrendState]) -> str:
    """Render trend states as a Markdown section. Empty list → empty string."""
    if not states:
        return ""
    lines = ["## 📈 Trend Snapshot (200-day SMA)"]
    for s in states:
        emoji = "🟢" if s.state == "BULL" else "🔴"
        dev = f"+{s.deviation_pct:.1f}%" if s.deviation_pct >= 0 else f"{s.deviation_pct:.1f}%"
        lines.append(
            f"{emoji} **{s.ticker}** ${s.price:.2f} | SMA200 ${s.sma200:.2f} "
            f"({dev}) — {_recommendation(s)}"
        )
        if s.last_cross_date is not None and s.days_in_state is not None:
            lines.append(f"   ↳ State held since {s.last_cross_date} ({s.days_in_state} days)")
    return "\n".join(lines)


def fetch_trend_states(tickers: Optional[list[str]] = None) -> list[TrendState]:
    """Pull last ~400 days of OHLCV via yfinance, compute trend state per ticker.

    Errors per ticker are swallowed (returns partial list); a global failure
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
    results: list[TrendState] = []
    for ticker in tickers:
        try:
            df = yf.Ticker(ticker).history(
                start=start.isoformat(),
                end=end.isoformat(),
                auto_adjust=True,
            )
            state = compute_trend_state(ticker, df)
            if state is not None:
                results.append(state)
        except Exception:
            continue
    return results

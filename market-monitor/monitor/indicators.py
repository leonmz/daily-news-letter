"""Fetch a live Snapshot from yfinance (network I/O — not unit-tested).

``yfinance`` is imported lazily inside the fetch function so the pure modules and
unit tests never need the network dependency installed.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from monitor import config
from monitor.moving_averages import compute_ma_comparison
from monitor.snapshot import Reading, Snapshot


def _last_close(df) -> float | None:
    if df is None or df.empty or "Close" not in df.columns:
        return None
    s = df["Close"].dropna()
    return float(s.iloc[-1]) if len(s) else None


def fetch_snapshot(
    equity_tickers: list[str] | None = None,
    vol_tickers: list[str] | None = None,
    sma_periods: list[int] | None = None,
    history_period: str | None = None,
    tz: str | None = None,
) -> Snapshot:
    """Pull SPY/QQQ (with SMAs) + VIX/VXN levels into a Snapshot.

    Per-ticker failures are swallowed so a transient error on one symbol still
    yields a partial snapshot for the rest.
    """
    import yfinance as yf

    equity_tickers = equity_tickers or config.EQUITY_TICKERS
    vol_tickers = vol_tickers or config.VOL_TICKERS
    sma_periods = sma_periods or config.SMA_PERIODS
    history_period = history_period or config.HISTORY_PERIOD
    tz = tz or config.TIMEZONE

    now = datetime.now(ZoneInfo(tz))
    readings: list[Reading] = []

    for ticker in equity_tickers:
        try:
            df = yf.Ticker(ticker).history(period=history_period, auto_adjust=True)
            ma = compute_ma_comparison(ticker, df, sma_periods)
            price = ma.price if ma is not None else _last_close(df)
            if price is not None:
                readings.append(Reading(symbol=ticker.upper(), price=price, ma=ma))
        except Exception as e:  # noqa: BLE001 - one bad ticker shouldn't sink the run
            print(f"[indicators] {ticker} failed: {e}")

    for ticker in vol_tickers:
        try:
            df = yf.Ticker(ticker).history(period="1mo", auto_adjust=False)
            price = _last_close(df)
            if price is not None:
                readings.append(Reading(symbol=ticker, price=price, ma=None))
        except Exception as e:  # noqa: BLE001
            print(f"[indicators] {ticker} failed: {e}")

    return Snapshot(
        timestamp=now.isoformat(timespec="minutes"),
        date=now.strftime("%Y-%m-%d"),
        readings=readings,
    )

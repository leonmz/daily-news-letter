"""Generate comparison reports matching the Google Sheet format.

Google Sheet tabs reproduced:
- SMA周期: run Basic_MA with multiple SMA periods, compare metrics.
- 信号对比: compare Basic_MA, VIX_Optimized, Dual_MA signals.
"""

from __future__ import annotations

import pandas as pd

from .data import load_ticker_data, load_vix_data
from .engine import BacktestEngine
from .signals import basic_ma_signal, vix_optimized_signal, dual_ma_signal

SMA_PERIODS = [150, 180, 200, 230, 250, 300]


def _run_basic_ma(prices: pd.DataFrame, period: int) -> dict:
    """Run Basic_MA for a single SMA period and return a metrics row."""
    sig = basic_ma_signal(prices["close"], period=period)
    engine = BacktestEngine()
    result = engine.run(prices, sig)
    m = result.metrics

    whipsaw = sum(1 for t in result.trades if t.duration_days < 5)

    return {
        "SMA周期": period,
        "CAGR": f"{m.cagr:.1%}",
        "Sharpe": f"{m.sharpe:.2f}",
        "MaxDD": f"{m.max_drawdown:.1%}",
        "Final($M)": f"{m.final_value / 1e6:.2f}",
        "时间在市场": f"{m.time_in_market:.1%}",
        "交易次数": m.num_trades,
        "Whipsaw次数": whipsaw,
    }


def generate_sma_comparison(underlying: str = "SPY") -> pd.DataFrame:
    """Run Basic_MA signal with multiple SMA periods.

    Reproduces the Google Sheet "SMA周期" tab.

    Args:
        underlying: Any ticker symbol (e.g. "SPY", "QQQ", "NVDA").

    Returns:
        DataFrame with metrics for each SMA period.
    """
    prices = load_ticker_data(underlying.upper())
    rows = [_run_basic_ma(prices, period) for period in SMA_PERIODS]
    return pd.DataFrame(rows)


def generate_signal_comparison(underlying: str = "SPY") -> pd.DataFrame:
    """Compare Basic_MA, VIX_Optimized, and Dual_MA signals.

    Reproduces the Google Sheet "信号对比" tab.

    Args:
        underlying: Any ticker symbol.

    Returns:
        DataFrame with one row per signal variant.
    """
    prices = load_ticker_data(underlying.upper())
    vix_close = load_vix_data()["close"]
    engine = BacktestEngine()
    rows = []

    for name, sig in [
        ("Basic_MA (SMA250)", basic_ma_signal(prices["close"])),
        ("VIX_Optimized", vix_optimized_signal(prices["close"], vix_close)),
        ("Dual_MA (50/200)", dual_ma_signal(prices["close"])),
    ]:
        result = engine.run(prices, sig)
        m = result.metrics
        rows.append({
            "信号": name,
            "CAGR": f"{m.cagr:.1%}",
            "Sharpe": f"{m.sharpe:.2f}",
            "MaxDD": f"{m.max_drawdown:.1%}",
            "Final($M)": f"{m.final_value / 1e6:.2f}",
            "时间在市场": f"{m.time_in_market:.1%}",
            "交易次数": m.num_trades,
        })

    return pd.DataFrame(rows)

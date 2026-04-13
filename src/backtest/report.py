"""Generate comparison reports matching the Google Sheet format.

Google Sheet tabs reproduced:
- SMA周期: run Basic_MA with multiple SMA periods, compare metrics.
- 信号对比: compare Basic_MA, VIX_Optimized, Dual_MA signals.
"""

from __future__ import annotations

import pandas as pd

from .data import load_spy_data, load_qqq_data, load_vix_data
from .engine import BacktestEngine
from .signals import basic_ma_signal, vix_optimized_signal, dual_ma_signal

SMA_PERIODS = [150, 180, 200, 230, 250, 300]


def _run_basic_ma(prices: pd.DataFrame, period: int) -> dict:
    """Run Basic_MA for a single SMA period and return a metrics dict."""
    sig = basic_ma_signal(prices["close"], period=period)
    engine = BacktestEngine()
    result = engine.run(prices, sig)
    m = result.metrics

    # Count whipsaw: trades that lasted fewer than 5 days
    whipsaw = sum(
        1 for t in result.trades
        if (pd.Timestamp(t.exit_date) - pd.Timestamp(t.entry_date)).days < 5
    )

    return {
        "SMA周期": period,
        "AfterTax CAGR": f"{m.cagr_aftertax:.1%}",
        "PreTax CAGR": f"{m.cagr_pretax:.1%}",
        "Sharpe": f"{m.sharpe:.2f}",
        "MaxDD": f"{m.max_drawdown:.1%}",
        "Final($M)": f"{m.final_value_aftertax / 1e6:.2f}",
        "时间在市场": f"{m.time_in_market:.1%}",
        "交易次数": m.num_trades,
        "Whipsaw次数": whipsaw,
    }


def generate_sma_comparison(underlying: str = "SPY") -> pd.DataFrame:
    """Run Basic_MA signal with multiple SMA periods.

    Reproduces the Google Sheet "SMA周期" tab.

    Args:
        underlying: "SPY" or "QQQ".

    Returns:
        DataFrame with columns: SMA周期, AfterTax CAGR, Sharpe, MaxDD,
        Final($M), Whipsaw次数, plus extras.
    """
    loader = load_spy_data if underlying.upper() == "SPY" else load_qqq_data
    prices = loader()

    rows = [_run_basic_ma(prices, period) for period in SMA_PERIODS]
    return pd.DataFrame(rows)


def generate_signal_comparison(underlying: str = "SPY") -> pd.DataFrame:
    """Compare Basic_MA, VIX_Optimized, and Dual_MA signals.

    Reproduces the Google Sheet "信号对比" tab.

    Args:
        underlying: "SPY" or "QQQ".

    Returns:
        DataFrame with one row per signal variant.
    """
    loader = load_spy_data if underlying.upper() == "SPY" else load_qqq_data
    prices = loader()
    vix_df = load_vix_data()
    vix_close = vix_df["close"]

    engine = BacktestEngine()
    rows = []

    # Basic_MA (SMA250 default)
    sig_basic = basic_ma_signal(prices["close"])
    r = engine.run(prices, sig_basic)
    m = r.metrics
    rows.append({
        "信号": "Basic_MA (SMA250)",
        "AfterTax CAGR": f"{m.cagr_aftertax:.1%}",
        "PreTax CAGR": f"{m.cagr_pretax:.1%}",
        "Sharpe": f"{m.sharpe:.2f}",
        "MaxDD": f"{m.max_drawdown:.1%}",
        "Final($M)": f"{m.final_value_aftertax / 1e6:.2f}",
        "时间在市场": f"{m.time_in_market:.1%}",
        "交易次数": m.num_trades,
    })

    # VIX_Optimized
    sig_vix = vix_optimized_signal(prices["close"], vix_close)
    r = engine.run(prices, sig_vix)
    m = r.metrics
    rows.append({
        "信号": "VIX_Optimized",
        "AfterTax CAGR": f"{m.cagr_aftertax:.1%}",
        "PreTax CAGR": f"{m.cagr_pretax:.1%}",
        "Sharpe": f"{m.sharpe:.2f}",
        "MaxDD": f"{m.max_drawdown:.1%}",
        "Final($M)": f"{m.final_value_aftertax / 1e6:.2f}",
        "时间在市场": f"{m.time_in_market:.1%}",
        "交易次数": m.num_trades,
    })

    # Dual_MA (50/200)
    sig_dual = dual_ma_signal(prices["close"])
    r = engine.run(prices, sig_dual)
    m = r.metrics
    rows.append({
        "信号": "Dual_MA (50/200)",
        "AfterTax CAGR": f"{m.cagr_aftertax:.1%}",
        "PreTax CAGR": f"{m.cagr_pretax:.1%}",
        "Sharpe": f"{m.sharpe:.2f}",
        "MaxDD": f"{m.max_drawdown:.1%}",
        "Final($M)": f"{m.final_value_aftertax / 1e6:.2f}",
        "时间在市场": f"{m.time_in_market:.1%}",
        "交易次数": m.num_trades,
    })

    return pd.DataFrame(rows)

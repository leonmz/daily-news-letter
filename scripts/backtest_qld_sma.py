#!/usr/bin/env python3
"""QLD + N-day SMA timing backtest.

Compares SMA(50/100/200) timing on QLD (2x QQQ daily-reset ETF) vs Buy & Hold.
Real OHLCV via yfinance. QLD inception: 2006-06-21.

Usage:
    python scripts/backtest_qld_sma.py
    python scripts/backtest_qld_sma.py --no-hysteresis           # pure cross, no entry/exit band
    python scripts/backtest_qld_sma.py --start 2010-01-01        # custom window
    python scripts/backtest_qld_sma.py --periods 20 50 100 200   # custom SMA list
    python scripts/backtest_qld_sma.py --plot                    # equity curves PNG

Whipsaw definitions reported:
  - "Short trades"   : trades held < 10 trading days (any P&L)
  - "Whipsaw losses" : trades held < 10 days AND with negative return  (the painful kind)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd

from backtest.data import load_ticker_data
from backtest.engine import BacktestEngine, BacktestResult
from backtest.signals import basic_ma_signal


def _count_whipsaws(trades, max_days: int = 10) -> tuple[int, int]:
    short = sum(1 for t in trades if t.duration_days < max_days)
    short_losses = sum(1 for t in trades if t.duration_days < max_days and t.pct_return < 0)
    return short, short_losses


def _buy_and_hold(prices: pd.DataFrame, initial_capital: float = 1_000_000) -> BacktestResult:
    sig = pd.Series(1, index=prices.index, dtype=int)
    return BacktestEngine().run(prices, sig, initial_capital=initial_capital, annual_fee=0.0095)


def _run_sma(
    prices: pd.DataFrame,
    period: int,
    entry_mult: float,
    exit_mult: float,
    initial_capital: float = 1_000_000,
) -> BacktestResult:
    sig = basic_ma_signal(prices["close"], period=period, entry_mult=entry_mult, exit_mult=exit_mult)
    return BacktestEngine().run(prices, sig, initial_capital=initial_capital, annual_fee=0.0095)


def _row(label: str, result: BacktestResult) -> dict:
    m = result.metrics
    short, whip_loss = _count_whipsaws(result.trades, max_days=10)
    return {
        "Strategy": label,
        "CAGR": f"{m.cagr:.1%}",
        "Sharpe": f"{m.sharpe:.2f}",
        "MaxDD": f"{m.max_drawdown:.1%}",
        "DD Window": f"{m.max_dd_start} → {m.max_dd_end}",
        "Final($M)": f"{m.final_value / 1e6:.2f}",
        "TimeInMkt": f"{m.time_in_market:.0%}",
        "Trades": m.num_trades,
        "Short(<10d)": short,
        "WhipLosses": whip_loss,
    }


def _plot(results: dict[str, BacktestResult], output: str) -> None:
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib not installed — skipping plot. pip install matplotlib")
        return
    fig, ax = plt.subplots(figsize=(14, 7))
    for label, result in results.items():
        result.equity_curve.plot(ax=ax, label=label, linewidth=1.1)
    ax.set_title("QLD: SMA Timing Strategies vs Buy & Hold")
    ax.set_ylabel("Portfolio Value ($)")
    ax.set_yscale("log")
    ax.legend(loc="upper left")
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(output, dpi=150)
    print(f"\nPlot saved → {output}")


def main() -> None:
    p = argparse.ArgumentParser(description="QLD + N-day SMA timing backtest")
    p.add_argument("--start", default="2006-06-21", help="Start date (QLD inception 2006-06-21)")
    p.add_argument("--end", default="2025-12-31", help="End date")
    p.add_argument("--periods", type=int, nargs="+", default=[50, 100, 200], help="SMA periods to compare")
    p.add_argument("--no-hysteresis", action="store_true",
                   help="Disable entry/exit band (pure SMA cross)")
    p.add_argument("--entry-mult", type=float, default=1.04)
    p.add_argument("--exit-mult", type=float, default=0.95)
    p.add_argument("--capital", type=float, default=1_000_000, help="Initial capital")
    p.add_argument("--plot", action="store_true", help="Save equity curves PNG")
    p.add_argument("--output", default="qld_sma_backtest.png")
    args = p.parse_args()

    entry_mult = 1.0 if args.no_hysteresis else args.entry_mult
    exit_mult = 1.0 if args.no_hysteresis else args.exit_mult

    print(f"\nLoading QLD {args.start} → {args.end}...")
    prices = load_ticker_data("QLD", start=args.start, end=args.end)
    print(f"  Loaded {len(prices)} trading days ({prices.index[0].date()} → {prices.index[-1].date()})")
    if args.no_hysteresis:
        print("  Mode: PURE CROSS (no hysteresis band)")
    else:
        print(f"  Mode: hysteresis (entry > SMA×{entry_mult}, exit < SMA×{exit_mult})")

    results: dict[str, BacktestResult] = {}
    rows = []

    bh = _buy_and_hold(prices, initial_capital=args.capital)
    results["Buy & Hold"] = bh
    rows.append(_row("Buy & Hold", bh))

    for period in args.periods:
        result = _run_sma(prices, period, entry_mult, exit_mult, initial_capital=args.capital)
        label = f"SMA{period}"
        results[label] = result
        rows.append(_row(label, result))

    df = pd.DataFrame(rows)
    print(f"\n{'=' * 100}")
    print("  QLD — SMA Timing Comparison")
    print(f"{'=' * 100}")
    print(df.to_string(index=False))

    print(f"\n{'=' * 60}")
    print("  Sample trades (most recent 3 per strategy)")
    print(f"{'=' * 60}")
    for label, result in results.items():
        if not result.trades or label == "Buy & Hold":
            continue
        print(f"\n  {label}:")
        print(f"    {'Entry':<12} {'Exit':<12} {'Return':>8} {'Days':>6}")
        for t in result.trades[-3:]:
            print(f"    {str(t.entry_date):<12} {str(t.exit_date):<12} "
                  f"{t.pct_return:>8.2%} {t.duration_days:>6}")

    if args.plot:
        _plot(results, args.output)


if __name__ == "__main__":
    main()

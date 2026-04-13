#!/usr/bin/env python3
"""CLI entry point for the backtesting engine.

Usage:
    python scripts/run_backtest.py --underlying SPY --signal basic_ma --sma 250
    python scripts/run_backtest.py --compare-sma SPY
    python scripts/run_backtest.py --compare-signals SPY

Output: prints metrics table; optionally saves equity curve plot with --plot.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running from repo root without installing the package
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd

from src.backtest.data import load_spy_data, load_qqq_data, load_vix_data
from src.backtest.engine import BacktestEngine
from src.backtest.report import generate_sma_comparison, generate_signal_comparison
from src.backtest.signals import basic_ma_signal, vix_optimized_signal, dual_ma_signal


def _print_metrics(result, label: str) -> None:
    m = result.metrics
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    print(f"  PreTax  CAGR : {m.cagr_pretax:.2%}")
    print(f"  AfterTax CAGR: {m.cagr_aftertax:.2%}")
    print(f"  Sharpe       : {m.sharpe:.3f}")
    print(f"  Max Drawdown : {m.max_drawdown:.2%}  ({m.max_dd_start} → {m.max_dd_end})")
    print(f"  Time in Mkt  : {m.time_in_market:.1%}")
    print(f"  Trades       : {m.num_trades}")
    print(f"  Final (Pre)  : ${m.final_value_pretax:,.0f}")
    print(f"  Final (After): ${m.final_value_aftertax:,.0f}")
    print()

    if result.trades:
        print("  Last 5 trades:")
        print(f"  {'Entry':<12} {'Exit':<12} {'Return':>8} {'Tax Paid':>12}")
        print(f"  {'-'*48}")
        for t in result.trades[-5:]:
            print(
                f"  {str(t.entry_date):<12} {str(t.exit_date):<12} "
                f"{t.pct_return:>8.2%} {t.tax_paid:>12,.0f}"
            )


def run_single(args: argparse.Namespace) -> None:
    underlying = args.underlying.upper()
    loader = load_spy_data if underlying == "SPY" else load_qqq_data
    prices = loader()

    signal_name = args.signal.lower()
    sma = args.sma

    if signal_name == "basic_ma":
        sig = basic_ma_signal(prices["close"], period=sma)
        label = f"{underlying} Basic_MA (SMA{sma})"
    elif signal_name == "vix_optimized":
        vix = load_vix_data()["close"]
        sig = vix_optimized_signal(prices["close"], vix, period=sma)
        label = f"{underlying} VIX_Optimized (SMA{sma})"
    elif signal_name == "dual_ma":
        sig = dual_ma_signal(prices["close"])
        label = f"{underlying} Dual_MA (50/200)"
    else:
        print(f"Unknown signal: {signal_name}. Choose from: basic_ma, vix_optimized, dual_ma")
        sys.exit(1)

    engine = BacktestEngine()
    result = engine.run(prices, sig)
    _print_metrics(result, label)

    if args.plot:
        _save_plot(result, label, args.output)


def run_compare_sma(args: argparse.Namespace) -> None:
    underlying = args.underlying.upper()
    print(f"\nSMA Period Comparison — {underlying}\n")
    df = generate_sma_comparison(underlying)
    print(df.to_string(index=False))


def run_compare_signals(args: argparse.Namespace) -> None:
    underlying = args.underlying.upper()
    print(f"\nSignal Comparison — {underlying}\n")
    df = generate_signal_comparison(underlying)
    print(df.to_string(index=False))


def _save_plot(result, label: str, output: str | None) -> None:
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib not installed — skipping plot. pip install matplotlib")
        return

    fig, ax = plt.subplots(figsize=(14, 6))
    result.equity_curve_pretax.plot(ax=ax, label="Pre-Tax", linewidth=1.2, color="steelblue")
    result.equity_curve_aftertax.plot(ax=ax, label="After-Tax", linewidth=1.2, color="darkorange")
    ax.set_title(label)
    ax.set_ylabel("Portfolio Value ($)")
    ax.legend()
    ax.grid(True, alpha=0.3)

    out_path = output or f"backtest_{label.replace(' ', '_')}.png"
    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    print(f"Plot saved to {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest SMA timing strategies")
    parser.add_argument(
        "--underlying", default="SPY", help="SPY or QQQ (default: SPY)"
    )
    parser.add_argument(
        "--signal",
        default="basic_ma",
        choices=["basic_ma", "vix_optimized", "dual_ma"],
        help="Signal to use (default: basic_ma)",
    )
    parser.add_argument(
        "--sma", type=int, default=250, help="SMA period (default: 250)"
    )
    parser.add_argument(
        "--compare-sma",
        metavar="UNDERLYING",
        help="Run all SMA periods for the given underlying (SPY or QQQ)",
    )
    parser.add_argument(
        "--compare-signals",
        metavar="UNDERLYING",
        help="Compare all signals for the given underlying",
    )
    parser.add_argument("--plot", action="store_true", help="Save equity curve plot")
    parser.add_argument("--output", help="Output path for plot (default: auto)")

    args = parser.parse_args()

    if args.compare_sma:
        args.underlying = args.compare_sma
        run_compare_sma(args)
    elif args.compare_signals:
        args.underlying = args.compare_signals
        run_compare_signals(args)
    else:
        run_single(args)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Three-tier SMA regime backtest: QLD / QQQ / SHY.

Regime logic (decided by QQQ close vs its own SMA50 and SMA200):
  QQQ > SMA50            → hold QLD  (2x leveraged QQQ, bullish)
  SMA200 < QQQ ≤ SMA50   → hold QQQ  (1x, de-levered, transitional)
  QQQ ≤ SMA200           → hold SHY  (1-3yr Treasuries, defensive cash)

SHY chosen over BIL because SHY (inception 2002-07) covers the full QLD
history (QLD inception 2006-06). Signal computed on QQQ; holdings are
the actual ETFs.

Usage:
    python scripts/backtest_qld_qqq_shy_sma.py
    python scripts/backtest_qld_qqq_shy_sma.py --no-hysteresis
    python scripts/backtest_qld_qqq_shy_sma.py --fast 50 --slow 200
    python scripts/backtest_qld_qqq_shy_sma.py --plot
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd

from backtest.data import load_ticker_data
from backtest.metrics import calculate_cagr, calculate_max_drawdown, calculate_sharpe


FEES = {"QLD": 0.0095, "QQQ": 0.0020, "SHY": 0.0015}


def three_tier_signal(
    price: pd.Series,
    sma_fast: pd.Series,
    sma_slow: pd.Series,
    entry_mult: float = 1.04,
    exit_mult: float = 0.95,
) -> pd.Series:
    """State machine: SHY ↔ QQQ ↔ QLD with hysteresis bands."""
    n = len(price)
    states = ["SHY"] * n
    state = "SHY"

    for i in range(n):
        if pd.isna(sma_slow.iloc[i]):
            states[i] = state
            continue
        p = price.iloc[i]
        s_slow = sma_slow.iloc[i]
        s_fast = sma_fast.iloc[i]
        f_ok = not pd.isna(s_fast)

        for _ in range(4):  # cap chained transitions per day
            if state == "SHY" and p > s_slow * entry_mult:
                state = "QQQ"
                continue
            if state == "QQQ":
                if f_ok and p > s_fast * entry_mult:
                    state = "QLD"
                    continue
                if p < s_slow * exit_mult:
                    state = "SHY"
                    continue
            if state == "QLD" and f_ok and p < s_fast * exit_mult:
                state = "QQQ"
                continue
            break

        states[i] = state

    return pd.Series(states, index=price.index)


def run_three_tier(
    signal: pd.Series,
    qld: pd.DataFrame,
    qqq: pd.DataFrame,
    shy: pd.DataFrame,
    initial_capital: float,
):
    qld_close = qld["close"].reindex(signal.index).ffill()
    qqq_close = qqq["close"].reindex(signal.index).ffill()
    shy_close = shy["close"].reindex(signal.index).ffill()

    qld_ret = qld_close.pct_change().fillna(0).values
    qqq_ret = qqq_close.pct_change().fillna(0).values
    shy_ret = shy_close.pct_change().fillna(0).values

    pos = signal.shift(1).fillna("SHY").values

    qld_fee = (1 - FEES["QLD"]) ** (1 / 252)
    qqq_fee = (1 - FEES["QQQ"]) ** (1 / 252)
    shy_fee = (1 - FEES["SHY"]) ** (1 / 252)

    factor = np.where(
        pos == "QLD", (1 + qld_ret) * qld_fee,
        np.where(pos == "QQQ", (1 + qqq_ret) * qqq_fee,
                 (1 + shy_ret) * shy_fee),
    )
    equity = initial_capital * np.cumprod(factor)
    equity_curve = pd.Series(equity, index=signal.index)

    strategy_ret = pd.Series(
        np.where(pos == "QLD", qld_ret,
                 np.where(pos == "QQQ", qqq_ret, shy_ret)),
        index=signal.index,
    )
    return equity_curve, strategy_ret, pd.Series(pos, index=signal.index)


def regime_stats(positions: pd.Series, max_short: int = 10) -> dict:
    n = len(positions)
    counts = positions.value_counts()
    pct = {r: counts.get(r, 0) / n for r in ["QLD", "QQQ", "SHY"]}

    changes = (positions != positions.shift(1)).fillna(False)
    n_changes = max(0, int(changes.sum()) - 1)

    qld_episodes = []
    enter = None
    for i in range(1, n):
        prev, curr = positions.iloc[i - 1], positions.iloc[i]
        if prev != "QLD" and curr == "QLD":
            enter = i
        elif prev == "QLD" and curr != "QLD" and enter is not None:
            qld_episodes.append(i - enter)
            enter = None
    if enter is not None:
        qld_episodes.append(n - enter)

    short_qld = sum(1 for d in qld_episodes if d < max_short)

    return {
        "QLD_pct": pct["QLD"],
        "QQQ_pct": pct["QQQ"],
        "SHY_pct": pct["SHY"],
        "changes": n_changes,
        "qld_episodes": len(qld_episodes),
        "short_qld": short_qld,
    }


def _baseline(prices: pd.DataFrame, capital: float, fee: float):
    daily_fee = (1 - fee) ** (1 / 252)
    rets = prices["close"].pct_change().fillna(0)
    factor = (1 + rets) * daily_fee
    ec = capital * factor.cumprod()
    return ec, calculate_cagr(ec), calculate_sharpe(rets), *calculate_max_drawdown(ec)


def main():
    p = argparse.ArgumentParser(description="QLD/QQQ/SHY three-tier SMA regime backtest")
    p.add_argument("--start", default="2006-06-21", help="Backtest start (QLD inception)")
    p.add_argument("--end", default="2025-12-31")
    p.add_argument("--fast", type=int, default=50, help="Fast SMA (QLD↔QQQ switch)")
    p.add_argument("--slow", type=int, default=200, help="Slow SMA (QQQ↔SHY switch)")
    p.add_argument("--no-hysteresis", action="store_true")
    p.add_argument("--entry-mult", type=float, default=1.04)
    p.add_argument("--exit-mult", type=float, default=0.95)
    p.add_argument("--capital", type=float, default=1_000_000)
    p.add_argument("--plot", action="store_true")
    p.add_argument("--output", default="qld_qqq_shy_backtest.png")
    args = p.parse_args()

    entry_mult = 1.0 if args.no_hysteresis else args.entry_mult
    exit_mult = 1.0 if args.no_hysteresis else args.exit_mult

    # Warmup window so SMA is populated by args.start
    warmup_days = int(args.slow * 1.6) + 50
    load_start = (pd.Timestamp(args.start) - pd.Timedelta(days=warmup_days)).strftime("%Y-%m-%d")

    print(f"\nLoading QQQ/QLD/SHY {load_start} → {args.end}...")
    qqq_full = load_ticker_data("QQQ", start=load_start, end=args.end)
    qld_full = load_ticker_data("QLD", start=args.start, end=args.end)
    shy_full = load_ticker_data("SHY", start=load_start, end=args.end)
    print(f"  QQQ: {len(qqq_full)}  QLD: {len(qld_full)}  SHY: {len(shy_full)} trading days loaded")

    sma_fast = qqq_full["close"].rolling(args.fast).mean()
    sma_slow = qqq_full["close"].rolling(args.slow).mean()
    full_signal = three_tier_signal(
        qqq_full["close"], sma_fast, sma_slow,
        entry_mult=entry_mult, exit_mult=exit_mult,
    )

    # Trim everything to actual backtest window (signal carries state across boundary)
    qld_start = qld_full.index[0]
    actual_start = max(pd.Timestamp(args.start), qld_start)
    mask = full_signal.index >= actual_start
    signal = full_signal[mask]
    qqq = qqq_full[qqq_full.index >= actual_start]

    print(f"  Backtest window: {signal.index[0].date()} → {signal.index[-1].date()} "
          f"({len(signal)} days)")
    if args.no_hysteresis:
        print("  Mode: PURE CROSS")
    else:
        print(f"  Mode: hysteresis (entry × {entry_mult}, exit × {exit_mult})")
    print(f"  Signal: SMA{args.fast} (QLD↔QQQ) | SMA{args.slow} (QQQ↔SHY)")

    equity_curve, strategy_ret, positions = run_three_tier(
        signal, qld_full, qqq, shy_full, initial_capital=args.capital,
    )

    cagr = calculate_cagr(equity_curve)
    sharpe = calculate_sharpe(strategy_ret)
    max_dd, dd_start, dd_end = calculate_max_drawdown(equity_curve)
    stats = regime_stats(positions)

    qld_bh = _baseline(qld_full.loc[actual_start:], args.capital, FEES["QLD"])
    qqq_bh = _baseline(qqq, args.capital, FEES["QQQ"])

    rows = [
        {"Strategy": f"3-Tier (SMA{args.fast}/{args.slow})",
         "CAGR": f"{cagr:.1%}", "Sharpe": f"{sharpe:.2f}",
         "MaxDD": f"{max_dd:.1%}", "DD Window": f"{dd_start} → {dd_end}",
         "Final($M)": f"{equity_curve.iloc[-1] / 1e6:.2f}"},
        {"Strategy": "QLD B&H",
         "CAGR": f"{qld_bh[1]:.1%}", "Sharpe": f"{qld_bh[2]:.2f}",
         "MaxDD": f"{qld_bh[3]:.1%}", "DD Window": f"{qld_bh[4]} → {qld_bh[5]}",
         "Final($M)": f"{qld_bh[0].iloc[-1] / 1e6:.2f}"},
        {"Strategy": "QQQ B&H",
         "CAGR": f"{qqq_bh[1]:.1%}", "Sharpe": f"{qqq_bh[2]:.2f}",
         "MaxDD": f"{qqq_bh[3]:.1%}", "DD Window": f"{qqq_bh[4]} → {qqq_bh[5]}",
         "Final($M)": f"{qqq_bh[0].iloc[-1] / 1e6:.2f}"},
    ]

    print(f"\n{'=' * 100}")
    print("  Three-Tier Regime Backtest")
    print(f"{'=' * 100}")
    print(pd.DataFrame(rows).to_string(index=False))

    print("\n  Regime time breakdown:")
    print(f"    QLD : {stats['QLD_pct']:.1%}   QQQ : {stats['QQQ_pct']:.1%}   "
          f"SHY : {stats['SHY_pct']:.1%}")
    print(f"  Regime changes total       : {stats['changes']}")
    print(f"  QLD episodes               : {stats['qld_episodes']}")
    print(f"  QLD episodes lasting <10d  : {stats['short_qld']}")

    changes_idx = positions[positions != positions.shift(1)].iloc[1:].index
    if len(changes_idx) > 0:
        print("\n  Last 8 regime changes:")
        for dt in changes_idx[-8:]:
            prev_ = positions.shift(1).loc[dt]
            curr_ = positions.loc[dt]
            print(f"    {dt.date()}  {prev_:>3} → {curr_}")

    if args.plot:
        try:
            import matplotlib.pyplot as plt
            fig, ax = plt.subplots(figsize=(14, 7))
            equity_curve.plot(ax=ax, label=f"3-Tier (SMA{args.fast}/{args.slow})",
                              linewidth=1.4, color="darkgreen")
            qld_bh[0].plot(ax=ax, label="QLD B&H", linewidth=1.0, alpha=0.55, color="red")
            qqq_bh[0].plot(ax=ax, label="QQQ B&H", linewidth=1.0, alpha=0.55, color="steelblue")
            ax.set_title("QLD/QQQ/SHY Three-Tier Regime vs Buy & Hold")
            ax.set_ylabel("Portfolio Value ($)")
            ax.set_yscale("log")
            ax.legend(loc="upper left")
            ax.grid(True, alpha=0.3)
            plt.tight_layout()
            plt.savefig(args.output, dpi=150)
            print(f"\nPlot saved → {args.output}")
        except ImportError:
            print("matplotlib not installed — skipping plot")


if __name__ == "__main__":
    main()

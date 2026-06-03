#!/usr/bin/env python3
"""Stretch-overlay strategy on QLD/QQQ/SHY.

Hypothesis: when QQQ trades far above its SMA200 (e.g., >18%), mean-reversion
risk is elevated; de-lever QLD → QQQ to protect against the impending pullback.
Once stretch normalizes (e.g., ≤10%), re-lever back to QLD.

This script runs three phases:
  Phase 1 — Diagnostic: distribution of QQQ stretch vs SMA200
  Phase 2 — Validation: forward 60d returns after each stretch-threshold crossing
                        (tests whether high stretch actually predicts lower forward returns)
  Phase 3 — Strategy backtest: state machine with 4 (enter, exit) threshold pairs

State machine:
  Price < SMA200                              → SHY (defensive)
  Price > SMA200 AND stretch ≥ enter (e.g. 18%) → QQQ (overheated, de-lever)
  Price > SMA200 AND stretch ≤ exit  (e.g. 10%) → QLD (cool, leverage up)
  In between                                  → stay in current state (hysteresis hold)
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


def stretch_distribution(qqq_close: pd.Series, sma200: pd.Series) -> None:
    stretch = (qqq_close - sma200) / sma200
    valid = stretch.dropna()
    pos = valid[valid > 0]

    print("\n--- Phase 1: QQQ stretch (% above SMA200) distribution ---")
    print(f"  Total days with valid SMA200 : {len(valid)}")
    print(f"  Days price > SMA200          : {len(pos)} ({len(pos) / len(valid) * 100:.1f}%)")
    print(f"  Days price ≤ SMA200          : {len(valid) - len(pos)}")
    print("\n  Percentiles of stretch when price > SMA200:")
    for p in [50, 70, 80, 90, 95, 97, 99]:
        v = np.percentile(pos, p) * 100
        print(f"    P{p:>2}: {v:>5.1f}%")

    print("\n  Days at/above each threshold:")
    for t in [0.05, 0.10, 0.12, 0.15, 0.18, 0.20, 0.25, 0.30]:
        days = int((stretch >= t).sum())
        pct = days / len(valid) * 100
        print(f"    ≥ {t * 100:>4.0f}%: {days:>5} days ({pct:>4.1f}% of total)")


def forward_returns_by_threshold(qqq_close: pd.Series, sma200: pd.Series, days: int = 60) -> None:
    stretch = (qqq_close - sma200) / sma200
    print(f"\n--- Phase 2: Forward {days}d QQQ return after first crossing into each threshold ---")
    print(f"  (Crossing = stretch < t yesterday AND stretch ≥ t today)")

    print(f"\n  {'Threshold':>10} {'N':>4} {'AvgFwd':>9} {'Median':>9} {'Worst':>9} {'%>0':>6} {'<-10%':>7}")
    for t in [0.10, 0.12, 0.15, 0.18, 0.20, 0.25]:
        crossings = (stretch >= t) & (stretch.shift(1) < t)
        crossing_dates = stretch[crossings].index
        returns = []
        for dt in crossing_dates:
            idx = qqq_close.index.get_loc(dt)
            if idx + days < len(qqq_close):
                fwd = qqq_close.iloc[idx + days] / qqq_close.iloc[idx] - 1
                returns.append(fwd)
        if returns:
            arr = np.array(returns)
            print(f"  ≥{t * 100:>4.0f}%      "
                  f"{len(arr):>4} "
                  f"{np.mean(arr) * 100:>+7.1f}% "
                  f"{np.median(arr) * 100:>+7.1f}% "
                  f"{np.min(arr) * 100:>+7.1f}% "
                  f"{(arr > 0).mean() * 100:>5.0f}% "
                  f"{(arr < -0.10).mean() * 100:>6.0f}%")


def stretch_signal(qqq_close: pd.Series, sma200: pd.Series, enter: float, exit_: float) -> pd.Series:
    n = len(qqq_close)
    states = ["SHY"] * n
    state = "SHY"

    for i in range(n):
        p = qqq_close.iloc[i]
        s = sma200.iloc[i]
        if pd.isna(s):
            states[i] = state
            continue
        stretch = (p - s) / s

        for _ in range(4):
            if state != "SHY" and p < s:
                state = "SHY"
                continue
            if state == "SHY" and p > s:
                state = "QQQ" if stretch >= enter else "QLD"
                continue
            if state == "QLD" and stretch >= enter:
                state = "QQQ"
                continue
            if state == "QQQ" and p > s and stretch <= exit_:
                state = "QLD"
                continue
            break

        states[i] = state

    return pd.Series(states, index=qqq_close.index)


def run_three_asset(signal: pd.Series, qld: pd.DataFrame, qqq: pd.DataFrame, shy: pd.DataFrame,
                    capital: float) -> tuple[pd.Series, pd.Series, pd.Series]:
    qld_c = qld["close"].reindex(signal.index).ffill()
    qqq_c = qqq["close"].reindex(signal.index).ffill()
    shy_c = shy["close"].reindex(signal.index).ffill()

    qld_r = qld_c.pct_change().fillna(0).values
    qqq_r = qqq_c.pct_change().fillna(0).values
    shy_r = shy_c.pct_change().fillna(0).values

    pos = signal.shift(1).fillna("SHY").values
    f_qld = (1 - FEES["QLD"]) ** (1 / 252)
    f_qqq = (1 - FEES["QQQ"]) ** (1 / 252)
    f_shy = (1 - FEES["SHY"]) ** (1 / 252)

    factor = np.where(pos == "QLD", (1 + qld_r) * f_qld,
              np.where(pos == "QQQ", (1 + qqq_r) * f_qqq, (1 + shy_r) * f_shy))
    equity = capital * np.cumprod(factor)
    equity_curve = pd.Series(equity, index=signal.index)
    strat_ret = pd.Series(np.where(pos == "QLD", qld_r,
                          np.where(pos == "QQQ", qqq_r, shy_r)), index=signal.index)
    return equity_curve, strat_ret, pd.Series(pos, index=signal.index)


def regime_stats(positions: pd.Series) -> tuple[dict, int]:
    n = len(positions)
    counts = positions.value_counts()
    pct = {r: counts.get(r, 0) / n for r in ["QLD", "QQQ", "SHY"]}
    changes = (positions != positions.shift(1)).fillna(False)
    return pct, max(0, int(changes.sum()) - 1)


def summarize(label: str, equity: pd.Series, strat_ret: pd.Series, positions: pd.Series) -> dict:
    cagr = calculate_cagr(equity)
    sharpe = calculate_sharpe(strat_ret)
    max_dd, dd_s, dd_e = calculate_max_drawdown(equity)
    pct, changes = regime_stats(positions)
    return {
        "Strategy": label,
        "CAGR": f"{cagr:.1%}",
        "Sharpe": f"{sharpe:.2f}",
        "MaxDD": f"{max_dd:.1%}",
        "Final($M)": f"{equity.iloc[-1] / 1e6:.2f}",
        "QLD%": f"{pct['QLD']:.0%}",
        "QQQ%": f"{pct['QQQ']:.0%}",
        "SHY%": f"{pct['SHY']:.0%}",
        "Changes": changes,
    }


def two_tier_baseline(qqq_close: pd.Series, sma200: pd.Series,
                       qld: pd.DataFrame, shy: pd.DataFrame, capital: float):
    """QLD/SHY baseline (no stretch overlay)."""
    n = len(qqq_close)
    signal = pd.Series("SHY", index=qqq_close.index)
    state = "SHY"
    for i in range(n):
        p = qqq_close.iloc[i]
        s = sma200.iloc[i]
        if pd.isna(s):
            signal.iloc[i] = state
            continue
        if state == "SHY" and p > s:
            state = "QLD"
        elif state == "QLD" and p < s:
            state = "SHY"
        signal.iloc[i] = state
    # Create a fake qqq for the helper (it just needs the structure)
    return run_three_asset(signal, qld, pd.DataFrame({"close": qqq_close}), shy, capital)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--start", default="2006-06-21")
    p.add_argument("--end", default="2025-12-31")
    p.add_argument("--fwd-days", type=int, default=60)
    p.add_argument("--capital", type=float, default=1_000_000)
    p.add_argument("--plot", action="store_true")
    p.add_argument("--output", default="stretch_overlay_backtest.png")
    args = p.parse_args()

    warmup = (pd.Timestamp(args.start) - pd.Timedelta(days=350)).strftime("%Y-%m-%d")
    print(f"\nLoading QQQ/QLD/SHY {warmup} → {args.end}...")
    qqq_full = load_ticker_data("QQQ", start=warmup, end=args.end)
    qld_full = load_ticker_data("QLD", start=args.start, end=args.end)
    shy_full = load_ticker_data("SHY", start=warmup, end=args.end)
    print(f"  QQQ: {len(qqq_full)}  QLD: {len(qld_full)}  SHY: {len(shy_full)} days")

    sma200_full = qqq_full["close"].rolling(200).mean()

    actual_start = max(pd.Timestamp(args.start), qld_full.index[0])

    # Phase 1 & 2 use the full QQQ series from warmup onward (so we have more data points)
    diag_mask = qqq_full.index >= actual_start
    stretch_distribution(qqq_full["close"][diag_mask], sma200_full[diag_mask])
    forward_returns_by_threshold(qqq_full["close"][diag_mask], sma200_full[diag_mask],
                                  days=args.fwd_days)

    # Phase 3: backtest
    qqq = qqq_full[qqq_full.index >= actual_start]
    qld = qld_full[qld_full.index >= actual_start]
    qqq_close = qqq["close"]
    sma200 = sma200_full[sma200_full.index >= actual_start]

    print(f"\n--- Phase 3: Strategy backtest ({qqq.index[0].date()} → {qqq.index[-1].date()}) ---")

    threshold_pairs = [
        ("Tight (15/12)", 0.15, 0.12),
        ("Medium (18/10)", 0.18, 0.10),
        ("Wide (20/10)", 0.20, 0.10),
        ("Aggressive (15/5)", 0.15, 0.05),
    ]

    rows = []

    # Baseline: QLD/SHY two-tier (no stretch overlay)
    bl_eq, bl_ret, bl_pos = two_tier_baseline(qqq_close, sma200, qld, shy_full, args.capital)
    rows.append(summarize("Baseline QLD/SHY (no overlay)", bl_eq, bl_ret, bl_pos))

    results_for_plot = {"Baseline QLD/SHY": bl_eq}
    for label, enter, exit_ in threshold_pairs:
        signal = stretch_signal(qqq_close, sma200, enter, exit_)
        eq, ret, pos = run_three_asset(signal, qld, qqq, shy_full, args.capital)
        rows.append(summarize(f"Stretch {label}", eq, ret, pos))
        results_for_plot[f"Stretch {label}"] = eq

    print()
    print(pd.DataFrame(rows).to_string(index=False))

    if args.plot:
        try:
            import matplotlib.pyplot as plt
            fig, ax = plt.subplots(figsize=(14, 7))
            colors = ["black", "steelblue", "darkgreen", "darkorange", "firebrick"]
            for (label, eq), c in zip(results_for_plot.items(), colors):
                eq.plot(ax=ax, label=label, linewidth=1.2, color=c)
            ax.set_title("Stretch-overlay strategy (QQQ stretch >X% above SMA200 → de-lever QLD→QQQ)")
            ax.set_ylabel("Portfolio Value ($)")
            ax.set_yscale("log")
            ax.legend(loc="upper left")
            ax.grid(True, alpha=0.3)
            plt.tight_layout()
            plt.savefig(args.output, dpi=150)
            print(f"\nPlot saved → {args.output}")
        except ImportError:
            pass


if __name__ == "__main__":
    main()

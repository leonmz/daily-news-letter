#!/usr/bin/env python3
"""Apples-to-apples: QLD vs theoretical 2x QQQ daily-reset vs path-independent 2x QQQ.

All three strategies use the SAME signal: QQQ price vs its own SMA200, pure cross
(no hysteresis), entering at close of cross day, holding until next cross.

Strategies:
  A) QLD real           : trades QLD at its actual price (daily-reset 2x ETF + tracking
                          error + 0.95% expense). Engine leverage=1.0.
  B) 2x QQQ theoretical : engine leverage=2.0 on QQQ. Mathematically equivalent to a
                          perfect-tracking daily-reset 2x QQQ ETF with 0.20% fee.
                          Difference vs A = QLD's tracking error + fee gap.
  C) 2x QQQ path-indep  : during each in-market segment, equity = entry × (P_t/P_entry)^2.
                          No daily reset → no vol drag. This is the LEAP / continuously-
                          rebalanced 2x model. 0.20% annual fee.
                          Difference vs B = pure daily-reset volatility decay.

Window: QLD inception 2006-06-21 → 2025-12-30.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd

from backtest.data import load_ticker_data
from backtest.engine import BacktestEngine
from backtest.metrics import calculate_cagr, calculate_max_drawdown, calculate_sharpe
from backtest.signals import basic_ma_signal


def run_path_independent_leverage(
    qqq_close: pd.Series,
    signal: pd.Series,
    leverage: float,
    annual_fee: float,
    initial_capital: float,
) -> tuple[pd.Series, pd.Series]:
    """Path-independent N-x exposure on QQQ.

    During each in-market segment, equity follows (P_t / P_entry) ** leverage,
    minus daily fee drag. Out of market: equity stays flat.

    Returns (equity_curve, daily_strategy_returns).
    """
    position = signal.shift(1).fillna(0).astype(int).values
    prices = qqq_close.values
    n = len(prices)
    daily_fee_factor = (1 - annual_fee) ** (1 / 252)

    equity = np.zeros(n)
    equity[0] = initial_capital
    current = initial_capital

    in_segment = False
    entry_price = None
    entry_equity = None
    fee_steps = 0

    for i in range(1, n):
        if position[i] == 1:
            if not in_segment:
                in_segment = True
                entry_price = prices[i - 1]
                entry_equity = current
                fee_steps = 1
            else:
                fee_steps += 1
            ratio = prices[i] / entry_price
            current = entry_equity * (ratio ** leverage) * (daily_fee_factor ** fee_steps)
        else:
            if in_segment:
                in_segment = False
                entry_price = None
                fee_steps = 0
            # equity stays at `current`
        equity[i] = current

    equity_curve = pd.Series(equity, index=qqq_close.index)
    daily_ret = equity_curve.pct_change().fillna(0)
    return equity_curve, daily_ret


def summarize(label: str, equity: pd.Series, daily_ret: pd.Series) -> dict:
    cagr = calculate_cagr(equity)
    sharpe = calculate_sharpe(daily_ret)
    max_dd, dd_start, dd_end = calculate_max_drawdown(equity)
    return {
        "Strategy": label,
        "CAGR": f"{cagr:.1%}",
        "Sharpe": f"{sharpe:.2f}",
        "MaxDD": f"{max_dd:.1%}",
        "DD Window": f"{dd_start} → {dd_end}",
        "Final($M)": f"{equity.iloc[-1] / 1e6:.2f}",
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--start", default="2006-06-21", help="QLD inception")
    p.add_argument("--end", default="2025-12-31")
    p.add_argument("--sma", type=int, default=200)
    p.add_argument("--capital", type=float, default=1_000_000)
    p.add_argument("--plot", action="store_true")
    p.add_argument("--output", default="apples_to_apples_2x.png")
    args = p.parse_args()

    # Warmup window so SMA200 is populated by args.start
    warmup_start = (pd.Timestamp(args.start) - pd.Timedelta(days=int(args.sma * 1.6))).strftime("%Y-%m-%d")
    print(f"\nLoading QQQ {warmup_start} → {args.end}, QLD {args.start} → {args.end}...")
    qqq_full = load_ticker_data("QQQ", start=warmup_start, end=args.end)
    qld_full = load_ticker_data("QLD", start=args.start, end=args.end)
    print(f"  QQQ: {len(qqq_full)} days  QLD: {len(qld_full)} days")

    # Signal: QQQ pure-cross SMA200 (entry_mult=exit_mult=1.0)
    full_signal = basic_ma_signal(
        qqq_full["close"], period=args.sma, entry_mult=1.0, exit_mult=1.0,
    )

    actual_start = max(pd.Timestamp(args.start), qld_full.index[0])
    mask = full_signal.index >= actual_start
    signal = full_signal[mask]
    qqq = qqq_full[qqq_full.index >= actual_start]
    qld = qld_full[qld_full.index >= actual_start]

    # Align QLD to QQQ index (same trading calendar but be safe)
    qld_aligned = qld["close"].reindex(qqq.index).ffill()
    qld_df = pd.DataFrame({"close": qld_aligned})

    print(f"  Backtest window: {qqq.index[0].date()} → {qqq.index[-1].date()} ({len(qqq)} days)")
    print(f"  Signal: QQQ SMA{args.sma} pure cross")

    engine = BacktestEngine()

    # A) QLD real (leverage=1.0 because QLD's price already reflects 2x daily reset)
    res_qld = engine.run(qld_df, signal, initial_capital=args.capital,
                          annual_fee=0.0095, leverage=1.0)

    # B) Theoretical 2x QQQ daily-reset (engine compounds 2x daily returns)
    res_2x = engine.run(qqq, signal, initial_capital=args.capital,
                        annual_fee=0.0020, leverage=2.0)

    # C) Path-independent 2x QQQ (no daily-reset vol drag)
    equity_pi, ret_pi = run_path_independent_leverage(
        qqq["close"], signal, leverage=2.0, annual_fee=0.0020,
        initial_capital=args.capital,
    )

    # Baselines
    qqq_bh = engine.run(qqq, pd.Series(1, index=qqq.index),
                        initial_capital=args.capital, annual_fee=0.0020, leverage=1.0)
    qld_bh = engine.run(qld_df, pd.Series(1, index=qqq.index),
                        initial_capital=args.capital, annual_fee=0.0095, leverage=1.0)

    # Daily return series for Sharpe
    def daily_strategy_ret(result) -> pd.Series:
        price_returns = result.equity_curve.pct_change().fillna(0)
        return price_returns  # equity-based daily return already accounts for in-market only

    rows = [
        summarize("QLD real (lev=1, 0.95% fee)", res_qld.equity_curve,
                  daily_strategy_ret(res_qld)),
        summarize("2x QQQ daily-reset (theoretical)", res_2x.equity_curve,
                  daily_strategy_ret(res_2x)),
        summarize("2x QQQ path-independent (LEAP-eq)", equity_pi, ret_pi),
        summarize("QQQ B&H", qqq_bh.equity_curve, daily_strategy_ret(qqq_bh)),
        summarize("QLD B&H", qld_bh.equity_curve, daily_strategy_ret(qld_bh)),
    ]

    print(f"\n{'=' * 110}")
    print("  SMA200 pure-cross timing — three 2x QQQ variants + buy-and-hold baselines")
    print(f"{'=' * 110}")
    print(pd.DataFrame(rows).to_string(index=False))

    # Decompose the gap
    cagr_qld = calculate_cagr(res_qld.equity_curve)
    cagr_2x = calculate_cagr(res_2x.equity_curve)
    cagr_pi = calculate_cagr(equity_pi)

    print("\n  Gap decomposition (CAGR):")
    print(f"    Path-indep 2x QQQ  : {cagr_pi:.2%}")
    print(f"    Daily-reset 2x QQQ : {cagr_2x:.2%}   gap = -{(cagr_pi - cagr_2x):.2%}  ← pure vol-decay cost")
    print(f"    QLD real           : {cagr_qld:.2%}   gap = -{(cagr_2x - cagr_qld):.2%}  ← QLD tracking + fee inefficiency")
    print(f"    Total QLD vs ideal :              gap = -{(cagr_pi - cagr_qld):.2%}")

    # Final value comparison
    f_qld = res_qld.equity_curve.iloc[-1]
    f_2x = res_2x.equity_curve.iloc[-1]
    f_pi = equity_pi.iloc[-1]
    print("\n  Final value ratio (vs QLD):")
    print(f"    2x daily-reset / QLD : {f_2x / f_qld:.2f}x  (you'd have ${f_2x/1e6:.1f}M instead of ${f_qld/1e6:.1f}M)")
    print(f"    Path-indep 2x / QLD  : {f_pi / f_qld:.2f}x  (you'd have ${f_pi/1e6:.1f}M instead of ${f_qld/1e6:.1f}M)")

    if args.plot:
        try:
            import matplotlib.pyplot as plt
            fig, ax = plt.subplots(figsize=(14, 7))
            equity_pi.plot(ax=ax, label="Path-indep 2x QQQ (LEAP-eq)",
                            linewidth=1.5, color="darkgreen")
            res_2x.equity_curve.plot(ax=ax, label="Daily-reset 2x QQQ (theoretical)",
                                       linewidth=1.3, color="orange")
            res_qld.equity_curve.plot(ax=ax, label="QLD real",
                                        linewidth=1.3, color="firebrick")
            qqq_bh.equity_curve.plot(ax=ax, label="QQQ B&H",
                                       linewidth=0.9, alpha=0.6, color="steelblue")
            qld_bh.equity_curve.plot(ax=ax, label="QLD B&H",
                                       linewidth=0.9, alpha=0.6, color="purple")
            ax.set_title("Apples-to-apples: 2x QQQ variants under SMA200 pure-cross timing")
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

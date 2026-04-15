#!/usr/bin/env python3
"""Cross-validate LEAP simulation leverage against UPRO (3x SPY ETF).

Answers the core question: does spending 70% of portfolio VALUE on LEAP
premium produce the intended leverage, or does it over-lever?

Run:
    python3 scripts/validate_leverage.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import math

import numpy as np
import pandas as pd

from backtest.data import load_ticker_data, load_vix6m_data
from backtest.engine import BacktestEngine
from backtest.metrics import calculate_cagr, calculate_max_drawdown
from backtest.signals import basic_ma_signal
from backtest.strategies.leap_simulator import (
    LEAPSimulator,
    bs_call_delta,
    bs_call_price,
    find_strike_for_delta,
    leap_iv_from_vix,
)

# =====================================================================
# Part 1: Omega math explained
# =====================================================================

def part1_omega_math():
    print("=" * 72)
    print("  PART 1: OPTION OMEGA (ELASTICITY) EXPLAINED")
    print("=" * 72)

    S = 450.0
    vix = 20.0
    iv = leap_iv_from_vix(vix)  # 0.185
    T = 126 / 252.0  # 6 months
    r = 0.02

    print(f"\nSetup: SPY=${S:.0f}, VIX={vix}, LEAP IV={iv:.3f}, T=6mo, r={r}")
    print()

    # Why omega is ~7x for delta=0.80
    K = find_strike_for_delta(S, T, r, iv, 0.80)
    C = bs_call_price(S, K, T, r, iv)
    delta = bs_call_delta(S, K, T, r, iv)
    intrinsic = S - K
    time_val = C - intrinsic
    omega = delta * S / C

    print("For delta=0.80 LEAP:")
    print(f"  Strike K       = ${K:.2f}")
    print(f"  Intrinsic S-K  = ${intrinsic:.2f}")
    print(f"  Time value     = ${time_val:.2f}")
    print(f"  Total premium  = ${C:.2f}")
    print(f"  Delta          = {delta:.4f}")
    print()
    print(f"  Omega = delta x S / C = {delta:.4f} x {S:.0f} / {C:.2f} = {omega:.2f}x")
    print()
    print("  WHY ~7x? The call costs $50.45 but controls $360 of delta-weighted")
    print("  notional (0.80 x $450). You're paying $50 to get $360 of exposure.")
    print("  That's a 7.14:1 ratio -- the built-in leverage of a deep ITM option.")
    print()
    print("  Even though delta is 0.80 (not 1.0), the option premium is only ~11%")
    print("  of spot, so the leverage ratio is high. This is NOT a bug in BS --")
    print("  it's fundamental to how options work.")

    # Omega across delta targets
    print()
    print("  Delta target sweep (SPY=$450, VIX=20, T=6mo):")
    print(f"  {'Delta':>6} {'K':>8} {'C':>8} {'Intrin':>8} {'TimeVal':>8} "
          f"{'Omega':>7} {'70% alloc lev':>14}")
    print(f"  {'-'*63}")

    for target_d in [0.60, 0.70, 0.80, 0.90, 0.95]:
        K_t = find_strike_for_delta(S, T, r, iv, target_d)
        C_t = bs_call_price(S, K_t, T, r, iv)
        d_t = bs_call_delta(S, K_t, T, r, iv)
        omega_t = d_t * S / C_t if C_t > 0 else 0
        intrin_t = max(S - K_t, 0)
        tv_t = C_t - intrin_t
        total_lev = 0.30 + 0.70 * omega_t
        print(f"  {target_d:>6.2f} {K_t:>8.2f} {C_t:>8.2f} {intrin_t:>8.2f} "
              f"{tv_t:>8.2f} {omega_t:>7.2f} {total_lev:>14.2f}x")

    print()
    print("  KEY INSIGHT: Even delta=0.95 has omega ~4.5x. There is NO delta")
    print("  target where 70%-of-portfolio-in-premium produces only 2.35x total.")
    print("  The only way to get 2.35x is to allocate by NOTIONAL, not by premium.")


# =====================================================================
# Part 2 & 3: UPRO cross-validation
# =====================================================================

def part2_upro_crossval():
    print()
    print("=" * 72)
    print("  PART 2: UPRO CROSS-VALIDATION")
    print("=" * 72)

    # UPRO inception: June 25, 2009. Use 2009-07-01 to 2025-12-31.
    start = "2009-07-01"
    end = "2025-12-31"

    print(f"\nLoading data: SPY, UPRO, VIX6M ({start} to {end})...")
    spy = load_ticker_data("SPY", start=start, end=end)
    upro = load_ticker_data("UPRO", start=start, end=end)
    vix = load_vix6m_data(start=start, end=end)

    # Align to common dates
    common_idx = spy.index.intersection(upro.index)
    spy = spy.loc[common_idx]
    upro = upro.loc[common_idx]
    print(f"  Common trading days: {len(common_idx)}")

    # Part 3: UPRO daily return vs 3 x SPY daily return
    print()
    print("-" * 72)
    print("  PART 3: DOES UPRO = 3x SPY DAILY?")
    print("-" * 72)

    spy_ret = spy["close"].pct_change().dropna()
    upro_ret = upro["close"].pct_change().dropna()
    # Align
    common_ret = spy_ret.index.intersection(upro_ret.index)
    spy_ret = spy_ret.loc[common_ret]
    upro_ret = upro_ret.loc[common_ret]

    ratio = upro_ret / spy_ret.replace(0, np.nan)
    ratio_clean = ratio.dropna()
    # Remove extreme outliers (SPY near zero)
    ratio_clean = ratio_clean[ratio_clean.abs() < 10]

    corr = spy_ret.corr(upro_ret)
    mean_ratio = ratio_clean.median()

    print(f"  Correlation(SPY daily, UPRO daily): {corr:.4f}")
    print(f"  Median ratio (UPRO_ret / SPY_ret):  {mean_ratio:.3f}x")
    print(f"  Mean ratio:                         {ratio_clean.mean():.3f}x")
    print(f"  UPRO expense ratio:                 0.91% annually")
    print()
    print(f"  UPRO achieves ~{mean_ratio:.2f}x daily tracking vs SPY.")
    print(f"  Slight shortfall from 3.0x is due to expense ratio + tracking error.")

    # Generate signal on SPY (SMA250 Basic_MA)
    signal = basic_ma_signal(spy["close"], period=250, entry_mult=1.04, exit_mult=0.95)

    # ----- Strategy A: SPY 1x with signal -----
    engine = BacktestEngine()
    res_spy1x = engine.run(spy, signal, leverage=1.0)

    # ----- Strategy B: SPY 3x flat leverage -----
    res_spy3x = engine.run(spy, signal, leverage=3.0)

    # ----- Strategy C: UPRO actual with SPY signal -----
    # We use the same SPY-derived signal but trade UPRO
    res_upro = engine.run(upro, signal, leverage=1.0)

    # ----- Strategy D: Our LEAP sim (current: 70% premium) -----
    sim_current = LEAPSimulator(
        delta_target=0.80, expiry_months=6, roll_months=6,
        bid_ask_spread=0.005, risk_free_rate=0.02,
        core_pct=0.30, leap_pct=0.70,
    )
    eq_leap_current = sim_current.simulate(spy, vix, signal, 1_000_000)

    # ----- Strategy E: LEAP sim capped at ~3x total notional -----
    # Target: 0.30x from core + 2.70x from LEAP = 3.0x total
    # Need omega contribution = 2.70x from leap_pct fraction
    # omega at VIX=20 ~ 7.14x.  leap_pct * omega = 2.70  =>  leap_pct = 2.70/7.14 = 0.378
    # But omega varies! Instead, allocate by notional:
    #   core_pct = 0.30 (of portfolio as stock)
    #   leap_pct = premium needed for 0.70x notional
    # At VIX=20: premium ≈ C/S ≈ 50.45/450 = 11.2% of notional
    # For 0.70x notional on a $1M portfolio: need $700k notional
    #   contracts = 700000 / (delta * S) = 700000 / 360 = 1944
    #   premium = 1944 * 50.45 = $98,075 → ~9.8% of portfolio
    # So: core_pct=0.30, leap_pct=0.098, cash=0.602
    #
    # But LEAPSimulator requires core_pct + leap_pct = 1.0
    # We need to modify the approach: use a wrapper that limits notional.
    # For now, estimate by finding the leap_pct that gives ~3x total leverage.
    # leap_pct * omega ≈ 2.70 → at typical omega=6 (average VIX~18):
    # leap_pct = 2.70 / 6 = 0.45. But this is a hack.
    #
    # Better approach: simulate directly with controlled leverage.
    # Use a modified simulator that caps notional at 2.35x or 3.0x.

    # For now, we'll approximate with a low leap_pct.
    # At omega~6.5 (typical), leap_pct=0.10 gives 0.10*6.5=0.65x from LEAP
    # Total with 0.90 core = 0.90 + 0.65 = 1.55x → too low.
    # Let's just use the flat leverage model as the "capped" version.
    # This IS the correct comparison: if 2.35x is the target, engine --leverage 2.35 is it.

    res_spy235x = engine.run(spy, signal, leverage=2.35)

    # Compute metrics for LEAP sim
    def _metrics_from_equity(eq):
        cagr = calculate_cagr(eq)
        dd, dd_s, dd_e = calculate_max_drawdown(eq)
        return cagr, dd, dd_s, dd_e

    cagr_leap, dd_leap, _, _ = _metrics_from_equity(eq_leap_current)

    # Estimate effective leverage of the LEAP sim from return ratio
    # effective_lev ≈ LEAP_daily_return / SPY_daily_return (when in market)
    position = signal.shift(1).fillna(0)
    spy_daily = spy["close"].pct_change().fillna(0)
    leap_daily = eq_leap_current.pct_change().fillna(0)
    in_market = position == 1
    spy_in = spy_daily[in_market].replace(0, np.nan).dropna()
    leap_in = leap_daily[in_market].reindex(spy_in.index).dropna()
    common = spy_in.index.intersection(leap_in.index)
    if len(common) > 100:
        ratio_leap = (leap_in.loc[common] / spy_in.loc[common]).dropna()
        ratio_leap = ratio_leap[ratio_leap.abs() < 20]  # remove outliers
        eff_lev = ratio_leap.median()
    else:
        eff_lev = float("nan")

    # =====================================================================
    # Part 5: Comparison table
    # =====================================================================
    print()
    print("=" * 72)
    print("  PART 5: COMPARISON TABLE")
    print("=" * 72)

    rows = [
        ("SPY 1x (signal)", res_spy1x.metrics.cagr, res_spy1x.metrics.max_drawdown,
         "1.00x", res_spy1x.metrics.final_value),
        ("SPY 2.35x flat", res_spy235x.metrics.cagr, res_spy235x.metrics.max_drawdown,
         "2.35x", res_spy235x.metrics.final_value),
        ("SPY 3x flat", res_spy3x.metrics.cagr, res_spy3x.metrics.max_drawdown,
         "3.00x", res_spy3x.metrics.final_value),
        ("UPRO actual (3x ETF)", res_upro.metrics.cagr, res_upro.metrics.max_drawdown,
         f"~{mean_ratio:.2f}x", res_upro.metrics.final_value),
        ("LEAP sim (current)", cagr_leap, dd_leap,
         f"~{eff_lev:.2f}x", float(eq_leap_current.iloc[-1])),
    ]

    print(f"\n  {'Strategy':<24} {'CAGR':>8} {'MaxDD':>8} {'Eff Lev':>9} "
          f"{'Final ($1M)':>14}")
    print(f"  {'-'*67}")
    for name, cagr, dd, lev, final in rows:
        print(f"  {name:<24} {cagr:>8.1%} {dd:>8.1%} {lev:>9} "
              f"${final:>13,.0f}")

    # Sanity check: UPRO vs 3x flat
    print()
    print("-" * 72)
    print("  SANITY CHECK: UPRO vs 3x FLAT")
    print("-" * 72)
    upro_cagr = res_upro.metrics.cagr
    flat3_cagr = res_spy3x.metrics.cagr
    print(f"  UPRO CAGR:    {upro_cagr:.2%}")
    print(f"  3x flat CAGR: {flat3_cagr:.2%}")
    print(f"  Gap:          {upro_cagr - flat3_cagr:+.2%}")
    print()
    if abs(upro_cagr - flat3_cagr) < 0.05:
        print("  UPRO and 3x flat are within 5% CAGR. This validates that")
        print("  BacktestEngine's flat leverage model correctly approximates")
        print("  a real 3x leveraged ETF (with some vol decay difference).")
    else:
        print("  SIGNIFICANT GAP between UPRO and 3x flat. Expected divergence")
        print("  sources: vol decay, UPRO expense ratio (0.91%), rebalancing.")

    # Where does LEAP sim sit on the leverage spectrum?
    print()
    print("-" * 72)
    print("  WHERE DOES THE LEAP SIM SIT?")
    print("-" * 72)
    print(f"  Estimated effective leverage: {eff_lev:.2f}x")
    print(f"  (median of LEAP_daily_return / SPY_daily_return when in market)")
    print()
    if eff_lev > 4.0:
        print(f"  The LEAP sim at {eff_lev:.1f}x leverage sits FAR ABOVE the 2.35x target.")
        print(f"  It behaves more like a {eff_lev:.0f}x leveraged ETF than a 2.35x strategy.")
        print()
        print("  CONCLUSION: The 70% premium allocation is OVER-LEVERED.")
        print("  To match the Google Sheet's 2.35x, the LEAP allocation should be")
        print("  by delta-weighted notional, not by premium cost.")
    elif eff_lev > 2.0:
        print(f"  The LEAP sim at {eff_lev:.1f}x is in the expected range for 2.35x.")
    else:
        print(f"  The LEAP sim at {eff_lev:.1f}x is BELOW the target -- check for bugs.")


# =====================================================================
# Part 4: The $700k question
# =====================================================================

def part4_notional_analysis():
    print()
    print("=" * 72)
    print("  PART 4: IS $700K IN PREMIUM BUYING TOO MANY CONTRACTS?")
    print("=" * 72)

    S = 450.0
    portfolio = 1_000_000
    vix = 20.0
    iv = leap_iv_from_vix(vix)
    T = 126 / 252.0
    r = 0.02

    K = find_strike_for_delta(S, T, r, iv, 0.80)
    C = bs_call_price(S, K, T, r, iv)
    delta = bs_call_delta(S, K, T, r, iv)
    C_ask = C * 1.0025

    print(f"\n  SPY=${S:.0f}, K=${K:.2f}, C=${C:.2f}, delta={delta:.4f}")
    print()

    # Current implementation: 70% of portfolio VALUE → premium
    leap_budget_prem = 0.70 * portfolio
    units_prem = leap_budget_prem / C_ask
    notional_prem = units_prem * delta * S
    lev_prem = (0.30 * portfolio + notional_prem) / portfolio

    print("  CURRENT: 70% of portfolio VALUE buys LEAP premium")
    print(f"    Budget:    ${leap_budget_prem:,.0f}")
    print(f"    Units:     {units_prem:,.0f}")
    print(f"    Notional:  ${notional_prem:,.0f} (= {units_prem:,.0f} x {delta:.2f} x ${S:.0f})")
    print(f"    Core:      ${0.30 * portfolio:,.0f}")
    print(f"    Total lev: ({0.30 * portfolio:,.0f} + {notional_prem:,.0f}) / {portfolio:,.0f}"
          f" = {lev_prem:.2f}x")
    print()

    # Alternative: 70% of portfolio as delta-weighted NOTIONAL
    notional_target = 0.70 * portfolio
    units_notional = notional_target / (delta * S)
    premium_needed = units_notional * C_ask
    lev_notional = (0.30 * portfolio + notional_target) / portfolio

    print("  ALTERNATIVE: 70% of portfolio as delta-weighted NOTIONAL")
    print(f"    Target notional: ${notional_target:,.0f}")
    print(f"    Units needed:    {units_notional:,.0f}")
    print(f"    Premium needed:  ${premium_needed:,.0f} ({premium_needed / portfolio:.1%} of portfolio)")
    print(f"    Core:            ${0.30 * portfolio:,.0f}")
    print(f"    Total lev:       ({0.30 * portfolio:,.0f} + {notional_target:,.0f}) / {portfolio:,.0f}"
          f" = {lev_notional:.2f}x")
    print()

    # What the Google Sheet 2.35x implies
    target_lev = 2.35
    leap_notional_for_235 = (target_lev - 0.30) * portfolio
    units_235 = leap_notional_for_235 / (delta * S)
    premium_235 = units_235 * C_ask
    pct_235 = premium_235 / portfolio

    print(f"  TO MATCH 2.35x TOTAL LEVERAGE:")
    print(f"    LEAP notional needed: ${leap_notional_for_235:,.0f}")
    print(f"    Units:                {units_235:,.0f}")
    print(f"    Premium:              ${premium_235:,.0f} ({pct_235:.1%} of portfolio)")
    print(f"    Remaining as cash:    ${portfolio - 0.30 * portfolio - premium_235:,.0f}"
          f" ({1 - 0.30 - pct_235:.1%})")
    print()

    over = lev_prem / target_lev
    print(f"  OVER-LEVERAGE FACTOR: {lev_prem:.2f}x / {target_lev}x = {over:.1f}x too much")
    print()
    print(f"  ANSWER: Yes, $700k in premium buys {units_prem:,.0f} contracts --")
    print(f"  about {units_prem / units_235:.1f}x more than the {units_235:,.0f} needed for 2.35x.")
    print(f"  The premium should be ~${premium_235:,.0f} ({pct_235:.1%}), not $700k (70%).")


# =====================================================================
# Main
# =====================================================================

if __name__ == "__main__":
    part1_omega_math()
    part4_notional_analysis()
    part2_upro_crossval()

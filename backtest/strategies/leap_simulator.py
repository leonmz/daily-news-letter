"""LEAP Call Option Simulator.

Black-Scholes based simulation of deep-ITM LEAP calls (delta ~0.80, 6-month expiry)
with historical VIX as the IV proxy.  Used by CoreLeapBacktest to model the
30% Core Stock + 70% LEAP strategy.

IV term-structure adjustment
-----------------------------
LEAPs have lower implied vol than 30-day options because markets mean-revert.
  LEAP_IV = VIX_decimal × 0.70  +  0.15 × 0.30
Example: VIX=20 → LEAP_IV = 0.14 + 0.045 = 18.5%

Signal convention (matches BacktestEngine)
------------------------------------------
signal[i] = 1 means "enter at close of day i".
The simulator shifts signal by 1 before applying, so position on day i is
determined by signal[i-1] — no look-ahead bias.

Roll mechanics
--------------
Buy a 6-month (≈126 trading-day) LEAP.  After roll_months×21 trading days,
sell at bid (−spread/2) and buy a fresh 6-month LEAP at ask (+spread/2).
Positions are also rebalanced back to core_pct/leap_pct on each roll/entry.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
from scipy.stats import norm

# ---------------------------------------------------------------------------
# Black-Scholes pricing functions
# ---------------------------------------------------------------------------

def bs_call_price(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """Black-Scholes European call price.

    Parameters
    ----------
    S     : spot price
    K     : strike price
    T     : time to expiry in years (≥ 0)
    r     : risk-free rate (annualised, decimal, e.g. 0.02)
    sigma : implied volatility (annualised, decimal, e.g. 0.20)

    Returns
    -------
    float : call option price ≥ 0
    """
    if T <= 0:
        return float(max(S - K, 0.0))
    if sigma <= 0:
        return float(max(S - K * math.exp(-r * T), 0.0))
    sqrt_T = math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * sqrt_T)
    d2 = d1 - sigma * sqrt_T
    price = S * float(norm.cdf(d1)) - K * math.exp(-r * T) * float(norm.cdf(d2))
    return max(price, 0.0)


def bs_call_delta(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """Black-Scholes call delta = N(d1).

    Returns a value in [0, 1].
    """
    if T <= 0:
        if S > K:
            return 1.0
        if S < K:
            return 0.0
        return 0.5
    if sigma <= 0:
        return 1.0 if S >= K * math.exp(-r * T) else 0.0
    sqrt_T = math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * sqrt_T)
    return float(norm.cdf(d1))


def find_strike_for_delta(
    S: float,
    T: float,
    r: float,
    sigma: float,
    target_delta: float = 0.80,
) -> float:
    """Find the strike that gives a target call delta (closed-form).

    Derivation
    ----------
    delta = N(d1)  →  d1 = N⁻¹(target_delta)

    d1 = [ln(S/K) + (r + σ²/2)·T] / (σ·√T)

    Solving for K:
        K = S · exp[(r + σ²/2)·T  −  d1·σ·√T]

    Parameters
    ----------
    S            : spot price
    T            : time to expiry in years
    r            : risk-free rate (decimal)
    sigma        : implied vol (decimal)
    target_delta : desired call delta in (0, 1), default 0.80

    Returns
    -------
    float : strike price
    """
    if T <= 1e-8 or sigma <= 1e-8:
        return S  # degenerate: return ATM strike
    d1_target = float(norm.ppf(target_delta))
    K = S * math.exp(
        (r + 0.5 * sigma ** 2) * T - d1_target * sigma * math.sqrt(T)
    )
    return float(K)


def leap_iv_from_vix(vix_pct: float) -> float:
    """Convert 30-day VIX (percentage, e.g. 20.5) to 6-month LEAP IV (decimal).

    Term-structure adjustment:
        LEAP_IV = VIX_decimal × 0.70  +  0.15 × 0.30

    Examples
    --------
    vix_pct=15  →  0.15×0.7 + 0.045 = 0.150
    vix_pct=20  →  0.20×0.7 + 0.045 = 0.185
    vix_pct=40  →  0.40×0.7 + 0.045 = 0.325
    """
    vix_decimal = vix_pct / 100.0
    return vix_decimal * 0.70 + 0.15 * 0.30


# ---------------------------------------------------------------------------
# LEAP Simulator
# ---------------------------------------------------------------------------

class LEAPSimulator:
    """Simulates holding a deep-ITM LEAP call alongside a core stock position.

    Strategy
    --------
    - When signal = 1 (in market):
        • core_pct  of portfolio in the underlying stock
        • leap_pct  of portfolio in a δ≈target_delta LEAP call
    - When signal = 0 (out of market): 100 % cash (no return, no decay)
    - Roll LEAP every roll_months × 21 trading days

    Parameters
    ----------
    delta_target    : target call delta at purchase (default 0.80)
    expiry_months   : LEAP expiry in months (default 6)
    roll_months     : months between rolls (default 6 = hold to expiry)
    bid_ask_spread  : round-trip spread fraction applied on buy/sell (default 0.5%)
    risk_free_rate  : annual risk-free rate (decimal, default 2%)
    core_pct        : fraction of portfolio in core stock (default 0.30)
    leap_pct        : fraction of portfolio in LEAP premium (default 0.70)
    """

    TRADING_DAYS_PER_MONTH: int = 21

    def __init__(
        self,
        delta_target: float = 0.80,
        expiry_months: int = 6,
        roll_months: int = 6,
        bid_ask_spread: float = 0.005,
        risk_free_rate: float = 0.02,
        core_pct: float = 0.30,
        leap_pct: float = 0.70,
    ):
        self.delta_target = delta_target
        self.expiry_months = expiry_months
        self.roll_months = roll_months
        self.bid_ask_spread = bid_ask_spread
        self.risk_free_rate = risk_free_rate
        self.core_pct = core_pct
        self.leap_pct = leap_pct

        if abs(core_pct + leap_pct - 1.0) > 1e-6:
            raise ValueError(f"core_pct + leap_pct must equal 1.0, got {core_pct + leap_pct}")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _leap_price(self, S: float, K: float, ttm_trading_days: int, iv: float) -> float:
        """Price a LEAP using BS, converting trading-day TTM to years."""
        ttm_years = max(ttm_trading_days, 1) / 252.0
        return bs_call_price(S, K, ttm_years, self.risk_free_rate, iv)

    def _entry_leap_ttm(self) -> int:
        """Total trading-day TTM at LEAP purchase."""
        return self.expiry_months * self.TRADING_DAYS_PER_MONTH

    def _roll_threshold(self) -> int:
        """Days-in-position threshold that triggers a roll."""
        return self.roll_months * self.TRADING_DAYS_PER_MONTH

    # ------------------------------------------------------------------
    # Main simulation
    # ------------------------------------------------------------------

    def simulate(
        self,
        prices: pd.DataFrame,
        vix: pd.DataFrame,
        signal: pd.Series,
        initial_capital: float = 1_000_000,
    ) -> pd.Series:
        """Simulate Core + LEAP portfolio over the price history.

        Parameters
        ----------
        prices          : DataFrame with a 'close' column (underlying price)
        vix             : DataFrame with a 'close' column (VIX in %, e.g. 20.5)
        signal          : pd.Series of 1/0 aligned with prices.index
        initial_capital : starting portfolio value in dollars

        Returns
        -------
        pd.Series : daily equity curve indexed by the same DatetimeIndex as prices
        """
        close = prices["close"]

        # Align VIX to price dates; forward-fill then back-fill any leading gaps
        vix_aligned = vix["close"].reindex(close.index).ffill().bfill()

        # Signal shift: position[i] = signal[i-1]  (no look-ahead)
        position = signal.shift(1).fillna(0)

        # ── Portfolio state ──────────────────────────────────────────
        portfolio: float = float(initial_capital)
        in_market: bool = False
        core_shares: float = 0.0
        leap_units: float = 0.0   # share-equivalent LEAP units held
        leap_strike: float = 0.0
        days_held: int = 0        # trading days since last entry / roll

        roll_at = self._roll_threshold()
        entry_ttm = self._entry_leap_ttm()

        equity_values: list[float] = []

        for i in range(len(close)):
            S = float(close.iloc[i])
            vix_pct = float(vix_aligned.iloc[i])
            iv = leap_iv_from_vix(vix_pct)
            pos = int(position.iloc[i])

            # ── Transition: cash → invested ──────────────────────────
            if not in_market and pos == 1:
                T_days = entry_ttm
                K = find_strike_for_delta(
                    S, T_days / 252.0, self.risk_free_rate, iv, self.delta_target
                )
                C = self._leap_price(S, K, T_days, iv)
                C_ask = C * (1.0 + self.bid_ask_spread / 2.0)

                core_shares = (self.core_pct * portfolio) / S
                leap_units = (self.leap_pct * portfolio) / max(C_ask, 1e-10)
                leap_strike = K
                days_held = 0
                in_market = True

            if in_market:
                days_held += 1
                ttm_days = entry_ttm - days_held

                # ── Roll ─────────────────────────────────────────────
                if days_held >= roll_at:
                    # Sell old LEAP at bid
                    C_old = self._leap_price(S, leap_strike, max(ttm_days, 0), iv)
                    C_bid = C_old * (1.0 - self.bid_ask_spread / 2.0)
                    portfolio = core_shares * S + leap_units * C_bid

                    # Buy new LEAP at ask, rebalance to core_pct/leap_pct
                    T_new = entry_ttm
                    K_new = find_strike_for_delta(
                        S, T_new / 252.0, self.risk_free_rate, iv, self.delta_target
                    )
                    C_new = self._leap_price(S, K_new, T_new, iv)
                    C_new_ask = C_new * (1.0 + self.bid_ask_spread / 2.0)

                    core_shares = (self.core_pct * portfolio) / S
                    leap_units = (self.leap_pct * portfolio) / max(C_new_ask, 1e-10)
                    leap_strike = K_new
                    days_held = 1          # today is day 1 of new LEAP
                    ttm_days = T_new - 1   # TTM after one day of the new LEAP

                # ── Transition: invested → cash ──────────────────────
                if pos == 0:
                    C_exit = self._leap_price(S, leap_strike, max(ttm_days, 1), iv)
                    C_bid = C_exit * (1.0 - self.bid_ask_spread / 2.0)
                    portfolio = core_shares * S + leap_units * C_bid

                    in_market = False
                    core_shares = 0.0
                    leap_units = 0.0
                    leap_strike = 0.0

                    equity_values.append(portfolio)
                else:
                    # ── Mark to market at mid ─────────────────────────
                    C_mid = self._leap_price(S, leap_strike, max(ttm_days, 1), iv)
                    equity_values.append(core_shares * S + leap_units * C_mid)

            else:
                # In cash
                equity_values.append(portfolio)

        return pd.Series(equity_values, index=close.index, dtype=float)

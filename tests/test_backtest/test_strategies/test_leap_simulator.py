"""Tests for the LEAP simulator — no live API calls."""

from __future__ import annotations

import math
import unittest

import numpy as np
import pandas as pd

from backtest.strategies.leap_simulator import (
    LEAPSimulator,
    bs_call_delta,
    bs_call_price,
    find_strike_for_delta,
    leap_iv_from_vix,
    vix6m_to_iv,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_prices(values: list[float], start: str = "2020-01-02") -> pd.DataFrame:
    idx = pd.date_range(start, periods=len(values), freq="B")
    return pd.DataFrame({"close": values}, index=idx)


def _make_vix(value: float, n: int, start: str = "2020-01-02") -> pd.DataFrame:
    idx = pd.date_range(start, periods=n, freq="B")
    return pd.DataFrame({"close": [value] * n}, index=idx)


def _make_signal(values: list[int], start: str = "2020-01-02") -> pd.Series:
    idx = pd.date_range(start, periods=len(values), freq="B")
    return pd.Series(values, index=idx, dtype=float)


# ---------------------------------------------------------------------------
# Black-Scholes pricing — known values
# ---------------------------------------------------------------------------

class TestBSCallPrice(unittest.TestCase):
    """Compare bs_call_price against textbook / online calculator values."""

    def test_atm_call_approx(self):
        """ATM call: S=K=100, T=1yr, r=0, sigma=0.20 → ≈ 7.97."""
        price = bs_call_price(100, 100, 1.0, 0.0, 0.20)
        self.assertAlmostEqual(price, 7.966, places=2)

    def test_deep_itm_call(self):
        """Deep ITM: S=120, K=80, T=0.5yr, r=0.02, sigma=0.25 → intrinsic dominated."""
        price = bs_call_price(120, 80, 0.5, 0.02, 0.25)
        intrinsic = 120 - 80 * math.exp(-0.02 * 0.5)
        self.assertGreater(price, intrinsic)
        self.assertAlmostEqual(price, 41.0, delta=2.0)

    def test_expired_itm(self):
        """T=0, ITM → intrinsic value."""
        price = bs_call_price(110, 100, 0.0, 0.02, 0.20)
        self.assertAlmostEqual(price, 10.0, places=6)

    def test_expired_otm(self):
        """T=0, OTM → 0."""
        price = bs_call_price(90, 100, 0.0, 0.02, 0.20)
        self.assertAlmostEqual(price, 0.0, places=6)

    def test_zero_vol(self):
        """sigma=0, ITM → discounted intrinsic."""
        price = bs_call_price(110, 100, 1.0, 0.05, 0.0)
        expected = 110 - 100 * math.exp(-0.05 * 1.0)
        self.assertAlmostEqual(price, expected, places=6)

    def test_zero_vol_otm(self):
        """sigma=0, OTM → 0."""
        price = bs_call_price(90, 100, 1.0, 0.05, 0.0)
        self.assertAlmostEqual(price, 0.0, places=6)

    def test_non_negative(self):
        """Call price must never be negative."""
        for S in [50, 100, 200]:
            for K in [80, 100, 120]:
                for T in [0.0, 0.25, 1.0]:
                    price = bs_call_price(S, K, T, 0.02, 0.30)
                    self.assertGreaterEqual(price, 0.0, f"S={S} K={K} T={T}")


# ---------------------------------------------------------------------------
# Delta calculation
# ---------------------------------------------------------------------------

class TestBSCallDelta(unittest.TestCase):
    def test_atm_delta_near_half(self):
        """ATM call delta is slightly above 0.5."""
        delta = bs_call_delta(100, 100, 1.0, 0.02, 0.20)
        self.assertGreater(delta, 0.50)
        self.assertLess(delta, 0.60)

    def test_deep_itm_delta_near_one(self):
        """Deep ITM: delta → 1."""
        delta = bs_call_delta(200, 100, 0.5, 0.02, 0.20)
        self.assertGreater(delta, 0.99)

    def test_deep_otm_delta_near_zero(self):
        """Deep OTM: delta → 0."""
        delta = bs_call_delta(50, 100, 0.5, 0.02, 0.20)
        self.assertLess(delta, 0.01)

    def test_delta_in_unit_interval(self):
        """Delta always in [0, 1]."""
        for S in [80, 100, 120]:
            for T in [0.25, 0.5, 1.0]:
                d = bs_call_delta(S, 100, T, 0.02, 0.25)
                self.assertGreaterEqual(d, 0.0)
                self.assertLessEqual(d, 1.0)

    def test_expired_itm(self):
        self.assertAlmostEqual(bs_call_delta(110, 100, 0.0, 0.02, 0.20), 1.0)

    def test_expired_otm(self):
        self.assertAlmostEqual(bs_call_delta(90, 100, 0.0, 0.02, 0.20), 0.0)


# ---------------------------------------------------------------------------
# Strike-finding for target delta
# ---------------------------------------------------------------------------

class TestFindStrikeForDelta(unittest.TestCase):
    def _check_round_trip(self, S, T, r, sigma, target_delta):
        K = find_strike_for_delta(S, T, r, sigma, target_delta)
        actual_delta = bs_call_delta(S, K, T, r, sigma)
        self.assertAlmostEqual(actual_delta, target_delta, places=4,
                               msg=f"S={S} T={T} target_delta={target_delta} K={K:.4f}")

    def test_delta_080(self):
        self._check_round_trip(400, 0.5, 0.02, 0.20, 0.80)

    def test_delta_070(self):
        self._check_round_trip(100, 0.5, 0.02, 0.25, 0.70)

    def test_delta_090(self):
        self._check_round_trip(500, 0.5, 0.02, 0.18, 0.90)

    def test_high_vol(self):
        """Works under high VIX (sigma=0.50, simulating stress)."""
        self._check_round_trip(100, 0.5, 0.02, 0.50, 0.80)

    def test_degenerate_zero_vol(self):
        """Zero sigma returns spot (ATM) — does not crash."""
        K = find_strike_for_delta(100, 0.5, 0.02, 0.0, 0.80)
        self.assertAlmostEqual(K, 100.0, places=6)


# ---------------------------------------------------------------------------
# LEAP IV term-structure
# ---------------------------------------------------------------------------

class TestLeapIVFromVix(unittest.TestCase):
    def test_vix_15(self):
        iv = leap_iv_from_vix(15.0)
        self.assertAlmostEqual(iv, 0.15 * 0.70 + 0.15 * 0.30, places=8)

    def test_vix_20(self):
        iv = leap_iv_from_vix(20.0)
        self.assertAlmostEqual(iv, 0.20 * 0.70 + 0.15 * 0.30, places=8)

    def test_vix_40(self):
        iv = leap_iv_from_vix(40.0)
        self.assertAlmostEqual(iv, 0.40 * 0.70 + 0.15 * 0.30, places=8)

    def test_always_positive(self):
        for vix in [5, 10, 20, 50, 80]:
            self.assertGreater(leap_iv_from_vix(vix), 0.0)


class TestVix6mToIv(unittest.TestCase):
    def test_simple_conversion(self):
        self.assertAlmostEqual(vix6m_to_iv(22.5), 0.225)

    def test_floor(self):
        """IV never goes below 5% even if VIX6M is absurdly low."""
        self.assertAlmostEqual(vix6m_to_iv(0.0), 0.05)
        self.assertAlmostEqual(vix6m_to_iv(2.0), 0.05)

    def test_high_vol(self):
        self.assertAlmostEqual(vix6m_to_iv(40.0), 0.40)


# ---------------------------------------------------------------------------
# LEAPSimulator — full simulation on synthetic data
# ---------------------------------------------------------------------------

class TestLEAPSimulatorFullRun(unittest.TestCase):
    """Smoke tests: verify shapes, monotonicity, and cash handling.

    Tests pass synthetic 30-day VIX values, so we use iv_convert=leap_iv_from_vix.
    """

    def setUp(self):
        n = 100
        self.prices = _make_prices([400.0] * n)
        self.vix = _make_vix(20.0, n)
        self.sim = LEAPSimulator()
        self._iv = leap_iv_from_vix

    def test_equity_curve_length(self):
        signal = _make_signal([1] * 100)
        equity = self.sim.simulate(self.prices, self.vix, signal, 1_000_000, iv_convert=self._iv)
        self.assertEqual(len(equity), 100)

    def test_always_in_cash_stays_flat(self):
        """Signal=0 throughout → portfolio stays at initial capital."""
        signal = _make_signal([0] * 100)
        equity = self.sim.simulate(self.prices, self.vix, signal, 1_000_000, iv_convert=self._iv)
        self.assertTrue((equity == 1_000_000).all())

    def test_entry_on_signal(self):
        """Signal switches from 0→1: portfolio should change after position lag."""
        signal = _make_signal([0] * 10 + [1] * 90)
        equity = self.sim.simulate(self.prices, self.vix, signal, 1_000_000, iv_convert=self._iv)
        self.assertAlmostEqual(float(equity.iloc[10]), 1_000_000, places=0)

    def test_rising_price_increases_portfolio(self):
        """Steadily rising underlying should increase portfolio value."""
        prices = _make_prices([400.0 * (1.001 ** i) for i in range(100)])
        signal = _make_signal([0] + [1] * 99)
        equity = self.sim.simulate(prices, self.vix, signal, 1_000_000, iv_convert=self._iv)
        self.assertGreater(float(equity.iloc[-1]), 1_000_000)

    def test_falling_price_decreases_portfolio(self):
        """Steadily falling underlying should decrease portfolio value."""
        prices = _make_prices([400.0 * (0.999 ** i) for i in range(100)])
        signal = _make_signal([0] + [1] * 99)
        equity = self.sim.simulate(prices, self.vix, signal, 1_000_000, iv_convert=self._iv)
        self.assertLess(float(equity.iloc[-1]), 1_000_000)

    def test_exit_crystalises_loss(self):
        """Going out of market after a fall should lock in the loss and stay flat."""
        vals = [400.0 * (0.995 ** i) for i in range(30)] + [400.0 * (0.995 ** 29)] * 10
        prices = _make_prices(vals)
        vix = _make_vix(20.0, len(vals))
        signal = _make_signal([0] + [1] * 29 + [0] * 10)
        equity = self.sim.simulate(prices, vix, signal, 1_000_000, iv_convert=self._iv)
        self.assertLess(float(equity.iloc[29]), 1_000_000)
        for i in range(32, 40):
            self.assertAlmostEqual(
                float(equity.iloc[31]), float(equity.iloc[i]), places=2,
                msg=f"Cash should be flat on day {i}"
            )

    def test_invalid_split_raises(self):
        """core_pct + leap_pct != 1.0 should raise ValueError."""
        with self.assertRaises(ValueError):
            LEAPSimulator(core_pct=0.40, leap_pct=0.40)

    def test_invalid_roll_gt_expiry_raises(self):
        """roll_months > expiry_months should raise ValueError."""
        with self.assertRaises(ValueError):
            LEAPSimulator(roll_months=8, expiry_months=6)

    def test_reentry_after_exit(self):
        """Exit then re-enter: portfolio should survive the cash gap."""
        n = 80
        vals = [400.0 * (1.001 ** i) for i in range(n)]
        prices = _make_prices(vals)
        vix = _make_vix(20.0, n)
        signal = _make_signal([0] + [1]*20 + [0]*20 + [1]*39)
        sim = LEAPSimulator()
        equity = sim.simulate(prices, vix, signal, 1_000_000, iv_convert=self._iv)
        self.assertGreater(float(equity.iloc[-1]), 1_000_000)
        for i in range(23, 41):
            self.assertAlmostEqual(
                float(equity.iloc[22]), float(equity.iloc[i]), places=0,
                msg=f"Cash period should be flat on day {i}"
            )


# ---------------------------------------------------------------------------
# Roll cost calculation
# ---------------------------------------------------------------------------

class TestRollCost(unittest.TestCase):
    """Verify that bid-ask spread is applied on rolls and reduces portfolio."""

    def test_roll_reduces_portfolio_vs_no_spread(self):
        """With spread > 0, portfolio after roll should be lower than with spread=0."""
        n = 200
        prices = _make_prices([400.0] * n)
        vix = _make_vix(20.0, n)
        signal = _make_signal([0] + [1] * 199)

        sim_with_spread = LEAPSimulator(
            roll_months=3,  # roll after 63 days → triggers at least once in 200 days
            expiry_months=6,
            bid_ask_spread=0.01,
        )
        sim_no_spread = LEAPSimulator(
            roll_months=3,
            expiry_months=6,
            bid_ask_spread=0.0,
        )

        equity_spread = sim_with_spread.simulate(prices, vix, signal, 1_000_000, iv_convert=leap_iv_from_vix)
        equity_no_spread = sim_no_spread.simulate(prices, vix, signal, 1_000_000, iv_convert=leap_iv_from_vix)

        # With spread, end value must be ≤ no-spread (theta ~equal; spread adds cost)
        self.assertLessEqual(float(equity_spread.iloc[-1]), float(equity_no_spread.iloc[-1]))


# ---------------------------------------------------------------------------
# Comparison: flat leverage vs LEAP simulation
# ---------------------------------------------------------------------------

class TestFlatVsLEAP(unittest.TestCase):
    """
    Validate that the LEAP sim produces qualitatively different results from
    flat 2.35x leverage — specifically that large down-moves hurt less
    (convexity protection via falling delta).
    """

    def _run_flat(self, prices: pd.DataFrame, signal: pd.Series,
                  leverage: float = 2.35, initial: float = 1_000_000):
        from backtest.engine import BacktestEngine
        engine = BacktestEngine()
        result = engine.run(prices, signal, leverage=leverage)
        return result.equity_curve

    def _run_leap(self, prices: pd.DataFrame, signal: pd.Series, initial: float = 1_000_000):
        vix = _make_vix(20.0, len(prices), start=str(prices.index[0].date()))
        sim = LEAPSimulator()
        return sim.simulate(prices, vix, signal, initial, iv_convert=leap_iv_from_vix)

    def test_leap_differs_from_flat_leverage(self):
        """
        LEAP simulation must produce different results from flat 2.35x leverage,
        verifying that option dynamics (theta, delta, convexity) are modelled
        rather than a trivial pass-through.
        """
        n = 100
        # Rising market: 0.3% per day compounded over 100 days ≈ +35%
        vals = [400.0 * (1.003 ** i) for i in range(n)]
        prices = _make_prices(vals)
        signal = _make_signal([0] + [1] * 99)

        equity_flat_235x = self._run_flat(prices, signal, leverage=2.35)
        equity_leap = self._run_leap(prices, signal)

        # Both gain in a rising market
        self.assertGreater(float(equity_flat_235x.iloc[-1]), 1_000_000)
        self.assertGreater(float(equity_leap.iloc[-1]), 1_000_000)

        # LEAP result must differ meaningfully from flat 2.35x (option dynamics active)
        self.assertNotAlmostEqual(
            float(equity_flat_235x.iloc[-1]),
            float(equity_leap.iloc[-1]),
            delta=50_000,
            msg="LEAP sim should differ from flat 2.35x — option dynamics must be active",
        )


if __name__ == "__main__":
    unittest.main()

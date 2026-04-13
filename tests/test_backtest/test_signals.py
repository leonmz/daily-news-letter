"""Tests for signal generators.

All tests use synthetic price data to avoid live API calls.
"""

import numpy as np
import pandas as pd
import pytest

from src.backtest.signals import basic_ma_signal, dual_ma_signal, vix_optimized_signal


def _make_prices(values, start="2010-01-04") -> pd.Series:
    """Build a daily price Series from a list of floats."""
    idx = pd.bdate_range(start=start, periods=len(values))
    return pd.Series(values, index=idx, name="close", dtype=float)


def _make_df(values, start="2010-01-04") -> pd.DataFrame:
    s = _make_prices(values, start)
    return s.to_frame(name="close")


# ---------------------------------------------------------------------------
# basic_ma_signal
# ---------------------------------------------------------------------------

class TestBasicMaSignal:
    def test_all_zeros_before_warmup(self):
        # SMA period=5, first 5 bars have no SMA → all 0
        prices = _make_prices([100] * 10)
        sig = basic_ma_signal(prices, period=5)
        assert sig.iloc[:5].sum() == 0

    def test_entry_fires_above_band(self):
        """Price jumps well above SMA*1.04 → signal enters market.

        With period=3 and prices [100,100,100,X,...]:
        SMA at index 3 = avg(100,100,X). To enter: X > avg(100,100,X)*1.04
        Solving: X > (200+X)/3*1.04 → 1.96X > 208 → X > 106.12.
        Use X=108 to safely trigger entry.
        """
        prices = _make_prices([100, 100, 100, 108, 108, 108])
        sig = basic_ma_signal(prices, period=3, entry_mult=1.04, exit_mult=0.95)
        assert sig.iloc[3] == 1

    def test_no_entry_inside_band(self):
        """Price between exit and entry thresholds does not trigger entry."""
        # SMA(3) at index 3 = avg(100,100,103)=101; threshold=101*1.04=105.04; 103 < 105 → stays out
        prices = _make_prices([100, 100, 100, 103, 103, 103])
        sig = basic_ma_signal(prices, period=3, entry_mult=1.04, exit_mult=0.95)
        assert sig.sum() == 0

    def test_exit_fires_below_band(self):
        """After entering, price dropping below SMA*0.95 triggers exit."""
        # At index 3: prices=[100,100,100,108] → SMA=102.67, threshold=106.77; 108 > 106.77 → enter
        # At index 4: prices=[100,100,108,85] → SMA=97.67, exit_thresh=92.78; 85 < 92.78 → exit
        prices = _make_prices([100, 100, 100, 108, 85, 85])
        sig = basic_ma_signal(prices, period=3, entry_mult=1.04, exit_mult=0.95)
        assert sig.iloc[3] == 1   # entered
        assert sig.iloc[4] == 0   # exited

    def test_hysteresis_prevents_exit_inside_band(self):
        """Price between exit and entry thresholds while in market → stay in."""
        # Enter at index 3 (price=108). At index 4: price=99.
        # SMA at index 4 = avg(100,100,108,99)[last 3] = avg(100,108,99)=102.33
        # exit_thresh = 102.33 * 0.95 = 97.22; 99 > 97.22 → stay in
        prices = _make_prices([100, 100, 100, 108, 99, 99])
        sig = basic_ma_signal(prices, period=3, entry_mult=1.04, exit_mult=0.95)
        assert sig.iloc[3] == 1
        assert sig.iloc[4] == 1  # still in — 99 > exit threshold
        assert sig.iloc[5] == 1  # still in

    def test_output_only_zero_or_one(self):
        prices = _make_prices(np.random.uniform(90, 110, 300).tolist())
        sig = basic_ma_signal(prices, period=50)
        assert set(sig.unique()).issubset({0, 1})

    def test_series_length_matches_input(self):
        prices = _make_prices([100] * 100)
        sig = basic_ma_signal(prices, period=20)
        assert len(sig) == 100

    def test_index_matches_input(self):
        prices = _make_prices([100] * 50)
        sig = basic_ma_signal(prices, period=10)
        pd.testing.assert_index_equal(sig.index, prices.index)

    def test_stays_out_if_price_never_enters(self):
        # Flat price at SMA level — never crosses 1.04x threshold
        prices = _make_prices([100.0] * 100)
        sig = basic_ma_signal(prices, period=20, entry_mult=1.04)
        assert sig.sum() == 0

    def test_re_entry_after_exit(self):
        """After exit, another rally triggers re-entry."""
        base = [100] * 10
        rally1 = [107] * 5   # enter
        drop = [90] * 5      # exit
        rally2 = [107] * 5   # re-enter
        prices = _make_prices(base + rally1 + drop + rally2)
        sig = basic_ma_signal(prices, period=5, entry_mult=1.04, exit_mult=0.95)
        # Should be in market during rally2
        assert sig.iloc[-1] == 1


# ---------------------------------------------------------------------------
# vix_optimized_signal
# ---------------------------------------------------------------------------

class TestVixOptimizedSignal:
    def _base_vix(self, prices, val=20.0) -> pd.Series:
        return pd.Series(val, index=prices.index, dtype=float)

    def test_vix_gate_prevents_entry(self):
        """High VIX (>25) prevents entering even if MA condition is met."""
        prices = _make_prices([100, 100, 100, 106, 106])
        vix = self._base_vix(prices, val=28.0)
        sig = vix_optimized_signal(
            prices, vix, period=3, entry_mult=1.04, vix_entry_max=25.0
        )
        assert sig.sum() == 0

    def test_vix_force_exit(self):
        """VIX spike above vix_exit_min forces exit even if MA says hold."""
        prices = _make_prices([100, 100, 100, 108, 108, 108])
        vix = pd.Series(
            [20, 20, 20, 20, 35, 35], index=prices.index, dtype=float
        )
        sig = vix_optimized_signal(
            prices, vix, period=3, entry_mult=1.04, vix_exit_min=30.0
        )
        assert sig.iloc[3] == 1   # entered when VIX=20
        assert sig.iloc[4] == 0   # forced out when VIX=35

    def test_low_vix_allows_entry(self):
        """Low VIX allows normal entry."""
        prices = _make_prices([100, 100, 100, 108, 108])
        vix = self._base_vix(prices, val=18.0)
        sig = vix_optimized_signal(
            prices, vix, period=3, entry_mult=1.04, vix_entry_max=25.0
        )
        assert sig.iloc[3] == 1


# ---------------------------------------------------------------------------
# dual_ma_signal
# ---------------------------------------------------------------------------

class TestDualMaSignal:
    def test_golden_cross_entry(self):
        """Fast MA crossing above slow MA triggers entry."""
        # Slow uptrend: first 10 bars flat at 100, then rise so fast>slow
        flat = [100.0] * 10
        rise = [101, 102, 103, 104, 105, 106, 107, 108, 109, 110]
        prices = _make_prices(flat + rise)
        sig = dual_ma_signal(prices, fast=3, slow=5)
        # After enough bars, fast > slow and signal = 1
        assert sig.iloc[-1] == 1

    def test_death_cross_exit(self):
        """Fast MA crossing below slow MA triggers exit."""
        rise = [100 + i for i in range(15)]
        fall = [115 - i * 2 for i in range(15)]
        prices = _make_prices(rise + fall)
        sig = dual_ma_signal(prices, fast=3, slow=7)
        # Should eventually exit during the fall
        assert sig.iloc[-1] == 0

    def test_no_signal_before_warmup(self):
        prices = _make_prices([100.0] * 30)
        sig = dual_ma_signal(prices, fast=5, slow=20)
        assert sig.iloc[:20].sum() == 0

    def test_output_only_zero_or_one(self):
        np.random.seed(42)
        prices = _make_prices(np.random.uniform(90, 110, 300).tolist())
        sig = dual_ma_signal(prices, fast=20, slow=50)
        assert set(sig.unique()).issubset({0, 1})

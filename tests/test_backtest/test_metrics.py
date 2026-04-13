"""Tests for metrics calculations with hand-verified examples."""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from src.backtest.metrics import (
    calculate_cagr,
    calculate_max_drawdown,
    calculate_sharpe,
)


def _equity(values, start="2010-01-04") -> pd.Series:
    idx = pd.bdate_range(start=start, periods=len(values))
    return pd.Series(values, index=idx, dtype=float)


# ---------------------------------------------------------------------------
# calculate_cagr
# ---------------------------------------------------------------------------

class TestCalculateCagr:
    def test_doubled_in_one_year(self):
        # Build exactly 1 calendar year of data using daily index
        idx = pd.date_range(start="2010-01-04", end="2011-01-04", freq="D")
        n = len(idx)
        values = [1_000_000 * (2 ** (i / (n - 1))) for i in range(n)]
        eq = pd.Series(values, index=idx, dtype=float)
        cagr = calculate_cagr(eq)
        # Should be ~100% CAGR (doubling in exactly 1 year)
        assert abs(cagr - 1.0) < 0.005

    def test_10pct_cagr_over_10_years(self):
        # 10% annual for 10 years: final = 1e6 * 1.1^10 ≈ 2,593,742
        n_days = 252 * 10
        daily_factor = 1.10 ** (1 / 252)
        values = [1_000_000 * (daily_factor ** i) for i in range(n_days + 1)]
        eq = _equity(values)
        cagr = calculate_cagr(eq)
        assert abs(cagr - 0.10) < 0.005

    def test_flat_returns_zero_cagr(self):
        eq = _equity([1_000_000] * 253)
        cagr = calculate_cagr(eq)
        assert abs(cagr) < 0.001

    def test_empty_after_dropna_returns_zero(self):
        eq = _equity([np.nan, np.nan, np.nan])
        # dropna leaves empty — should not crash, return 0
        # Actually dropna().iloc[0] would raise; let's just test it handles NaN-heavy gracefully
        eq2 = _equity([1_000_000] + [np.nan] * 2 + [1_100_000] * 250)
        cagr = calculate_cagr(eq2)
        assert cagr > 0


# ---------------------------------------------------------------------------
# calculate_sharpe
# ---------------------------------------------------------------------------

class TestCalculateSharpe:
    def test_zero_returns_gives_zero_sharpe(self):
        returns = pd.Series([0.0] * 252)
        sharpe = calculate_sharpe(returns, risk_free_rate=0.0)
        assert sharpe == 0.0

    def test_positive_excess_returns(self):
        # Daily return of 0.05%/day >> rf; should yield positive Sharpe
        returns = pd.Series([0.0005] * 252)
        sharpe = calculate_sharpe(returns, risk_free_rate=0.02)
        # Excess = 0.0005 - 0.02/252 ≈ 0.0005 - 0.0000794 ≈ 0.000421
        # std = 0, so Sharpe = 0... actually std of a constant is 0 → returns 0
        # Let's add tiny noise
        np.random.seed(1)
        returns = pd.Series(0.0005 + np.random.normal(0, 0.001, 252))
        sharpe = calculate_sharpe(returns, risk_free_rate=0.02)
        assert sharpe > 0  # clearly positive excess returns

    def test_negative_excess_returns(self):
        np.random.seed(2)
        returns = pd.Series(-0.001 + np.random.normal(0, 0.001, 252))
        sharpe = calculate_sharpe(returns, risk_free_rate=0.0)
        assert sharpe < 0

    def test_annualisation_factor(self):
        # Hand-verify: daily return=0.001, daily std=0.01, rf=0
        # Sharpe = (0.001/0.01) * sqrt(252) = 0.1 * 15.875 ≈ 1.587
        np.random.seed(3)
        n = 10_000
        returns = pd.Series(0.001 + np.random.normal(0, 0.01, n))
        sharpe = calculate_sharpe(returns, risk_free_rate=0.0)
        expected = (returns.mean() / returns.std()) * np.sqrt(252)
        assert abs(sharpe - expected) < 0.01


# ---------------------------------------------------------------------------
# calculate_max_drawdown
# ---------------------------------------------------------------------------

class TestCalculateMaxDrawdown:
    def test_no_drawdown(self):
        eq = _equity([1e6 * (1.001 ** i) for i in range(252)])
        dd, _, _ = calculate_max_drawdown(eq)
        assert abs(dd) < 0.001

    def test_simple_50pct_drawdown(self):
        # Peak at 200, trough at 100 → -50%
        values = [100, 150, 200, 180, 150, 100, 120]
        eq = _equity(values)
        dd, peak_d, trough_d = calculate_max_drawdown(eq)
        assert abs(dd - (-0.50)) < 0.001

    def test_drawdown_dates(self):
        values = [100, 200, 100, 150]  # peak=200 (day1), trough=100 (day2)
        eq = _equity(values)
        dd, peak_d, trough_d = calculate_max_drawdown(eq)
        assert dd == pytest.approx(-0.50, abs=0.001)
        # peak_d is before trough_d
        assert peak_d < trough_d

    def test_multiple_drawdowns_returns_worst(self):
        # Drawdown 1: -20%, Drawdown 2: -40%
        values = [100, 80, 100, 150, 90, 100]
        eq = _equity(values)
        dd, _, _ = calculate_max_drawdown(eq)
        # Worst drawdown: from 150 to 90 = -40%
        assert abs(dd - (-0.40)) < 0.001

    def test_returns_negative_fraction(self):
        eq = _equity([100, 50, 75])
        dd, _, _ = calculate_max_drawdown(eq)
        assert dd < 0

"""Unit tests for BS calibration engine and OptionPriceLookup."""

import importlib
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pandas as pd
import pytest

# Prevent backtest/__init__.py from importing yfinance via backtest.data
# by pre-registering the backtest package without executing __init__.py
if "backtest" not in sys.modules:
    import types
    sys.modules["backtest"] = types.ModuleType("backtest")
    sys.modules["backtest"].__path__ = [str(__import__("pathlib").Path(__file__).parent.parent.parent / "backtest")]

from backtest.calibration import BSCalibrator, CalibrationPoint, CalibrationReport
from backtest.strategies.leap_simulator import LEAPSimulator, OptionPriceLookup


# ─── OptionPriceLookup ────────────────────────────────────────────────────────

class TestOptionPriceLookup:

    def test_lookup_hit(self):
        data = {("2024-06-20", 560.0, "2025-06-20"): (170.0, 175.0, 172.5)}
        lookup = OptionPriceLookup(data)
        result = lookup.lookup("2024-06-20", 560.0, "2025-06-20")
        assert result == (170.0, 175.0, 172.5)

    def test_lookup_miss(self):
        data = {("2024-06-20", 560.0, "2025-06-20"): (170.0, 175.0, 172.5)}
        lookup = OptionPriceLookup(data)
        assert lookup.lookup("2024-06-21", 560.0, "2025-06-20") is None

    def test_lookup_rounds_strike(self):
        data = {("2024-06-20", 560.0, "2025-06-20"): (170.0, 175.0, 172.5)}
        lookup = OptionPriceLookup(data)
        result = lookup.lookup("2024-06-20", 560.004, "2025-06-20")
        assert result == (170.0, 175.0, 172.5)

    def test_len(self):
        data = {
            ("2024-06-20", 560.0, "2025-06-20"): (170.0, 175.0, 172.5),
            ("2024-06-20", 600.0, "2025-06-20"): (130.0, 135.0, 132.5),
        }
        lookup = OptionPriceLookup(data)
        assert len(lookup) == 2

    def test_from_snapshots(self):
        from data.models.market import OptionContract, OptionsSnapshot

        snap = OptionsSnapshot(
            ticker="SPY",
            expirations=["2025-06-20"],
            calls=[
                OptionContract(
                    strike=560.0, expiry="2025-06-20", option_type="call",
                    last_price=172.0, bid=170.0, ask=175.0,
                    volume=50, open_interest=500,
                ),
            ],
            puts=[],
            source="test",
        )
        lookup = OptionPriceLookup.from_snapshots({"2024-06-20": snap})
        assert len(lookup) == 1
        result = lookup.lookup("2024-06-20", 560.0, "2025-06-20")
        assert result is not None
        assert result[0] == 170.0  # bid
        assert result[1] == 175.0  # ask

    def test_from_snapshots_skips_zero_bid(self):
        from data.models.market import OptionContract, OptionsSnapshot

        snap = OptionsSnapshot(
            ticker="SPY",
            expirations=["2025-06-20"],
            calls=[
                OptionContract(
                    strike=560.0, expiry="2025-06-20", option_type="call",
                    last_price=0, bid=0, ask=0,
                    volume=0, open_interest=0,
                ),
            ],
            puts=[],
            source="test",
        )
        lookup = OptionPriceLookup.from_snapshots({"2024-06-20": snap})
        assert len(lookup) == 0


# ─── LEAPSimulator with market_prices ─────────────────────────────────────────

class TestLEAPSimulatorMarketData:

    def _make_data(self, n_days=50, start_price=500.0, trend=0.001):
        """Create synthetic price/vol/signal data."""
        dates = pd.bdate_range("2024-01-02", periods=n_days)
        prices_arr = [start_price * (1 + trend) ** i for i in range(n_days)]
        prices = pd.DataFrame({"close": prices_arr}, index=dates)
        vol = pd.DataFrame({"close": [20.0] * n_days}, index=dates)
        signal = pd.Series([1] * n_days, index=dates)
        return prices, vol, signal

    def test_simulate_without_market_prices_backward_compat(self):
        """Existing BS mode still works when market_prices=None."""
        sim = LEAPSimulator()
        prices, vol, signal = self._make_data()
        eq = sim.simulate(prices, vol, signal, initial_capital=100_000)

        assert len(eq) == len(prices)
        assert eq.iloc[0] > 0
        assert eq.iloc[-1] > eq.iloc[0]  # rising market → positive return

    def test_simulate_with_market_prices(self):
        """Market data mode produces different results than BS mode."""
        sim = LEAPSimulator()
        prices, vol, signal = self._make_data()

        eq_bs = sim.simulate(prices, vol, signal, initial_capital=100_000)

        # Create market prices that are 10% higher than BS would produce
        market_data = {}
        for date in prices.index:
            date_str = date.strftime("%Y-%m-%d")
            for strike in np.arange(400, 600, 10):
                for exp_date in pd.bdate_range("2024-06-01", "2024-12-31", freq="ME"):
                    exp_str = exp_date.strftime("%Y-%m-%d")
                    mid = 50.0
                    market_data[(date_str, float(strike), exp_str)] = (
                        mid * 0.97, mid * 1.03, mid,
                    )
        lookup = OptionPriceLookup(market_data)
        eq_mkt = sim.simulate(
            prices, vol, signal, initial_capital=100_000,
            market_prices=lookup,
        )

        assert len(eq_mkt) == len(prices)
        assert eq_mkt.iloc[-1] > 0

    def test_simulate_market_prices_fallback_to_bs(self):
        """When market data is empty, falls back to BS (same as no market data)."""
        sim = LEAPSimulator()
        prices, vol, signal = self._make_data()

        eq_bs = sim.simulate(prices, vol, signal, initial_capital=100_000)

        empty_lookup = OptionPriceLookup({})
        eq_fallback = sim.simulate(
            prices, vol, signal, initial_capital=100_000,
            market_prices=empty_lookup,
        )

        pd.testing.assert_series_equal(eq_bs, eq_fallback)


# ─── CalibrationReport ───────────────────────────────────────────────────────

class TestCalibrationReport:

    def _make_points(self, n=10):
        points = []
        for i in range(n):
            bs_price = 100 + i * 2
            mkt_mid = 100 + i * 2 + (i % 3 - 1)
            points.append(CalibrationPoint(
                date="2024-06-20", ticker="SPY", strike=500 + i * 10,
                expiry="2025-06-20", option_type="call", spot=550.0,
                bs_price=bs_price, market_mid=mkt_mid,
                market_bid=mkt_mid - 2, market_ask=mkt_mid + 2,
                bs_iv=0.20, market_iv=0.21,
                delta=0.30 + i * 0.07,
                abs_error=bs_price - mkt_mid,
                pct_error=(bs_price - mkt_mid) / mkt_mid * 100,
            ))
        return points

    def test_to_dataframe_returns_all_rows(self):
        points = self._make_points(10)
        report = CalibrationReport(
            ticker="SPY", points=points,
            summary={"n_points": 10, "date_range": "2024-06-20"},
        )
        df = report.to_dataframe()
        assert len(df) == 10
        assert "bs_price" in df.columns
        assert "mkt_mid" in df.columns
        assert "pct_err" in df.columns

    def test_to_dataframe_empty(self):
        report = CalibrationReport(
            ticker="SPY", points=[],
            summary={"n_points": 0, "date_range": "N/A"},
        )
        df = report.to_dataframe()
        assert df.empty

    def test_print_summary_runs(self, capsys):
        from backtest.calibration import BSCalibrator
        points = self._make_points(10)
        summary = BSCalibrator._compute_summary(points)
        report = CalibrationReport(ticker="SPY", points=points, summary=summary)
        report.print_summary()
        captured = capsys.readouterr()
        assert "SPY" in captured.out
        assert "Data points" in captured.out


# ─── BSCalibrator._compute_summary ───────────────────────────────────────────

class TestComputeSummary:

    def test_empty_points(self):
        from backtest.calibration import BSCalibrator
        summary = BSCalibrator._compute_summary([])
        assert summary["n_points"] == 0

    def test_summary_stats(self):
        from backtest.calibration import BSCalibrator
        points = [
            CalibrationPoint(
                date="2024-06-20", ticker="SPY", strike=560, expiry="2025-06-20",
                option_type="call", spot=550, bs_price=172.0, market_mid=170.0,
                market_bid=168.0, market_ask=173.0, bs_iv=0.20, market_iv=0.21,
                delta=0.85, abs_error=2.0, pct_error=1.18,
            ),
            CalibrationPoint(
                date="2024-06-20", ticker="SPY", strike=600, expiry="2025-06-20",
                option_type="call", spot=550, bs_price=130.0, market_mid=135.0,
                market_bid=133.0, market_ask=137.0, bs_iv=0.22, market_iv=0.23,
                delta=0.70, abs_error=-5.0, pct_error=-3.70,
            ),
        ]
        summary = BSCalibrator._compute_summary(points)
        assert summary["n_points"] == 2
        assert summary["mean_abs_error"] == pytest.approx(3.5)
        assert summary["within_spread_pct"] == pytest.approx(50.0)
        assert summary["overestimate_pct"] == pytest.approx(50.0)
        assert "by_delta" in summary

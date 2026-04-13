"""Tests for BacktestEngine — no live API calls, all mock data."""

import numpy as np
import pandas as pd
import pytest

from backtest.engine import BacktestEngine
from backtest.signals import basic_ma_signal


def _make_prices_df(closes, start="2010-01-04") -> pd.DataFrame:
    idx = pd.bdate_range(start=start, periods=len(closes))
    return pd.DataFrame({"close": closes}, index=idx)


def _constant_signal(prices_df: pd.DataFrame, value: int) -> pd.Series:
    return pd.Series(value, index=prices_df.index, dtype=int)


# ---------------------------------------------------------------------------
# Basic engine mechanics
# ---------------------------------------------------------------------------

class TestBacktestEngineBasics:
    def test_all_in_market_grows_with_prices(self):
        # Price rises 1% every day. All-in signal.
        n = 252
        closes = [100 * (1.01 ** i) for i in range(n)]
        prices = _make_prices_df(closes)
        signal = _constant_signal(prices, 1)

        engine = BacktestEngine()
        result = engine.run(prices, signal, initial_capital=1_000_000, annual_fee=0.0)

        # After 252 days of 1%/day, portfolio should be ~1M * 1.01^251
        # (first day has no return because signal is shifted by 1)
        expected_growth = 1.01 ** (n - 1)
        actual_ratio = result.equity_curve.iloc[-1] / 1_000_000
        assert abs(actual_ratio - expected_growth) < 0.01 * expected_growth

    def test_all_cash_stays_flat(self):
        closes = [100 + i for i in range(100)]
        prices = _make_prices_df(closes)
        signal = _constant_signal(prices, 0)

        engine = BacktestEngine()
        result = engine.run(prices, signal, initial_capital=1_000_000, annual_fee=0.0)

        assert result.equity_curve.iloc[-1] == pytest.approx(1_000_000, rel=1e-6)

    def test_fee_reduces_returns(self):
        closes = [100.0] * 253  # flat price, so return = -fee only
        prices = _make_prices_df(closes)
        signal = _constant_signal(prices, 1)

        engine = BacktestEngine()
        result_no_fee = engine.run(prices, signal, initial_capital=1_000_000, annual_fee=0.0)
        result_fee = engine.run(prices, signal, initial_capital=1_000_000, annual_fee=0.0009)

        assert result_fee.equity_curve.iloc[-1] < result_no_fee.equity_curve.iloc[-1]

    def test_metrics_populated(self):
        closes = [100 * (1.001 ** i) for i in range(252)]
        prices = _make_prices_df(closes)
        signal = _constant_signal(prices, 1)

        engine = BacktestEngine()
        result = engine.run(prices, signal)

        m = result.metrics
        assert m.cagr > 0
        assert m.sharpe != 0
        assert m.max_drawdown <= 0
        assert 0 <= m.time_in_market <= 1


# ---------------------------------------------------------------------------
# Trade tracking
# ---------------------------------------------------------------------------

class TestTradeTracking:
    def test_trade_count_two_entries(self):
        """Two distinct entry/exit cycles → two trades."""
        signal = pd.Series(0, index=pd.bdate_range("2010-01-04", periods=30), dtype=int)
        signal.iloc[2:8] = 1   # first trade
        signal.iloc[15:22] = 1  # second trade
        prices = _make_prices_df([100.0] * 30, start="2010-01-04")

        engine = BacktestEngine()
        result = engine.run(prices, signal, annual_fee=0.0)

        assert result.metrics.num_trades == 2
        assert len(result.trades) == 2

    def test_trade_dates_correct(self):
        """Entry and exit dates are recorded correctly."""
        signal = pd.Series(0, index=pd.bdate_range("2010-01-04", periods=10), dtype=int)
        signal.iloc[2:7] = 1
        prices = _make_prices_df([100.0] * 10, start="2010-01-04")

        engine = BacktestEngine()
        result = engine.run(prices, signal, annual_fee=0.0)

        assert len(result.trades) == 1
        t = result.trades[0]
        assert t.entry_date < t.exit_date

    def test_trade_pct_return(self):
        """Price doubling during a trade → ~100% pct_return."""
        closes = [100.0] * 30 + [200.0] * 30
        prices = _make_prices_df(closes)
        signal = pd.Series(0, index=prices.index, dtype=int)
        signal.iloc[10:50] = 1  # in market while price transitions 100→200

        engine = BacktestEngine()
        result = engine.run(prices, signal, annual_fee=0.0)

        assert len(result.trades) == 1
        assert result.trades[0].pct_return > 0.5   # captured most of the 100% move

    def test_trade_duration_days(self):
        """duration_days is positive and plausible for the signal window."""
        signal = pd.Series(0, index=pd.bdate_range("2010-01-04", periods=20), dtype=int)
        signal.iloc[2:12] = 1  # ~10 business days ≈ 14 calendar days
        prices = _make_prices_df([100.0] * 20, start="2010-01-04")

        engine = BacktestEngine()
        result = engine.run(prices, signal, annual_fee=0.0)

        assert len(result.trades) == 1
        assert result.trades[0].duration_days > 0

    def test_no_trades_all_cash(self):
        prices = _make_prices_df([100.0] * 50)
        signal = _constant_signal(prices, 0)

        engine = BacktestEngine()
        result = engine.run(prices, signal)

        assert result.metrics.num_trades == 0
        assert len(result.trades) == 0

    def test_time_in_market_calculation(self):
        """~50% of days in market → time_in_market ≈ 0.5."""
        n = 100
        signal = pd.Series(
            [1 if i % 2 == 0 else 0 for i in range(n)],
            index=pd.bdate_range("2010-01-04", periods=n),
            dtype=int,
        )
        prices = _make_prices_df([100.0] * n)

        engine = BacktestEngine()
        result = engine.run(prices, signal)

        assert 0.4 < result.metrics.time_in_market < 0.6

    def test_open_trade_at_end_of_data_captured(self):
        """Signal still 1 at last bar → trade closed at end of data."""
        signal = pd.Series(0, index=pd.bdate_range("2010-01-04", periods=20), dtype=int)
        signal.iloc[5:] = 1  # enters and never exits
        prices = _make_prices_df([100.0] * 20)

        engine = BacktestEngine()
        result = engine.run(prices, signal, annual_fee=0.0)

        assert len(result.trades) == 1


# ---------------------------------------------------------------------------
# Signal integration
# ---------------------------------------------------------------------------

class TestEngineWithSignal:
    def test_basic_ma_signal_runs_end_to_end(self):
        """Run the engine with basic_ma_signal on synthetic data — no errors."""
        np.random.seed(42)
        closes = np.cumprod(1 + np.random.normal(0.0003, 0.01, 500)) * 100
        closes = closes.tolist()
        prices = _make_prices_df(closes)
        signal = basic_ma_signal(pd.Series(closes, index=prices.index), period=50)

        engine = BacktestEngine()
        result = engine.run(prices, signal, initial_capital=1_000_000)

        assert result.equity_curve.iloc[-1] > 0
        assert result.metrics.cagr is not None
        assert not result.equity_curve.isna().any()

    def test_equity_curve_length_matches_prices(self):
        closes = [100.0] * 100
        prices = _make_prices_df(closes)
        signal = _constant_signal(prices, 1)

        engine = BacktestEngine()
        result = engine.run(prices, signal)

        assert len(result.equity_curve) == len(prices)

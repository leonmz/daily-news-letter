"""Tests for BacktestEngine — no live API calls, all mock data."""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from src.backtest.engine import BacktestEngine, TAX_RATE
from src.backtest.signals import basic_ma_signal


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
        actual_ratio = result.equity_curve_pretax.iloc[-1] / 1_000_000
        assert abs(actual_ratio - expected_growth) < 0.01 * expected_growth

    def test_all_cash_stays_flat(self):
        closes = [100 + i for i in range(100)]
        prices = _make_prices_df(closes)
        signal = _constant_signal(prices, 0)

        engine = BacktestEngine()
        result = engine.run(prices, signal, initial_capital=1_000_000, annual_fee=0.0)

        assert result.equity_curve_pretax.iloc[-1] == pytest.approx(1_000_000, rel=1e-6)

    def test_fee_reduces_returns(self):
        closes = [100.0] * 253  # flat price, so return = -fee only
        prices = _make_prices_df(closes)
        signal = _constant_signal(prices, 1)

        engine = BacktestEngine()
        result_no_fee = engine.run(prices, signal, initial_capital=1_000_000, annual_fee=0.0)
        result_fee = engine.run(prices, signal, initial_capital=1_000_000, annual_fee=0.0009)

        assert result_fee.equity_curve_pretax.iloc[-1] < result_no_fee.equity_curve_pretax.iloc[-1]

    def test_metrics_populated(self):
        closes = [100 * (1.001 ** i) for i in range(252)]
        prices = _make_prices_df(closes)
        signal = _constant_signal(prices, 1)

        engine = BacktestEngine()
        result = engine.run(prices, signal)

        m = result.metrics
        assert m.cagr_pretax > 0
        assert m.sharpe != 0
        assert m.max_drawdown <= 0
        assert 0 <= m.time_in_market <= 1


# ---------------------------------------------------------------------------
# Tax mechanics
# ---------------------------------------------------------------------------

class TestTaxMechanics:
    def test_single_gain_trade_taxed(self):
        """One trade: 100% gain → 37.1% of the gain is taxed."""
        # Price doubles over the period
        n = 100
        closes = [100.0] * 50 + [200.0] * 50
        prices = _make_prices_df(closes)

        # Signal: in for bars 25-74, out for rest
        signal = pd.Series(0, index=prices.index, dtype=int)
        signal.iloc[25:75] = 1

        engine = BacktestEngine()
        result = engine.run(prices, signal, initial_capital=1_000_000, annual_fee=0.0)

        # There should be exactly one completed trade
        assert len(result.trades) == 1
        trade = result.trades[0]

        # Gain should be positive (price goes from 100→200 during hold)
        assert trade.gain > 0
        # Tax paid should be ~37.1% of gain
        assert abs(trade.tax_paid / trade.gain - TAX_RATE) < 0.01

    def test_loss_trade_no_tax(self):
        """Trade at a loss: no tax paid."""
        closes = [200.0] * 50 + [100.0] * 50
        prices = _make_prices_df(closes)

        signal = pd.Series(0, index=prices.index, dtype=int)
        signal.iloc[20:80] = 1  # enter at 200, exit at 100

        engine = BacktestEngine()
        result = engine.run(prices, signal, initial_capital=1_000_000, annual_fee=0.0)

        for trade in result.trades:
            if trade.gain < 0:
                assert trade.tax_paid == 0.0

    def test_after_tax_below_pretax(self):
        """After-tax equity is always <= pre-tax equity when there are gains."""
        closes = [100 * (1.002 ** i) for i in range(300)]
        prices = _make_prices_df(closes)
        signal = basic_ma_signal(pd.Series(closes, index=prices.index), period=20)

        engine = BacktestEngine()
        result = engine.run(prices, signal, initial_capital=1_000_000, annual_fee=0.0)

        # After-tax final value should be <= pre-tax final value
        assert result.equity_curve_aftertax.iloc[-1] <= result.equity_curve_pretax.iloc[-1]


# ---------------------------------------------------------------------------
# Trade tracking
# ---------------------------------------------------------------------------

class TestTradeTracking:
    def test_trade_count_two_entries(self):
        """Two distinct entry/exit cycles → two trades."""
        signal = pd.Series(0, index=pd.bdate_range("2010-01-04", periods=30), dtype=int)
        signal.iloc[2:8] = 1   # first trade
        signal.iloc[15:22] = 1  # second trade
        closes = [100.0] * 30
        prices = _make_prices_df(closes, start="2010-01-04")

        engine = BacktestEngine()
        result = engine.run(prices, signal, annual_fee=0.0)

        assert result.metrics.num_trades == 2
        assert len(result.trades) == 2

    def test_trade_dates_correct(self):
        """Entry and exit dates are recorded correctly."""
        signal = pd.Series(0, index=pd.bdate_range("2010-01-04", periods=10), dtype=int)
        signal.iloc[2:7] = 1  # in from bar 2 to bar 6
        closes = [100.0] * 10
        prices = _make_prices_df(closes, start="2010-01-04")

        engine = BacktestEngine()
        result = engine.run(prices, signal, annual_fee=0.0)

        assert len(result.trades) == 1
        t = result.trades[0]
        assert t.entry_date < t.exit_date

    def test_no_trades_all_cash(self):
        prices = _make_prices_df([100.0] * 50)
        signal = _constant_signal(prices, 0)

        engine = BacktestEngine()
        result = engine.run(prices, signal)

        assert result.metrics.num_trades == 0
        assert len(result.trades) == 0

    def test_time_in_market_calculation(self):
        """50% of days in market → time_in_market ≈ 0.5 (after shift adjustment)."""
        n = 100
        signal = pd.Series(
            [1 if i % 2 == 0 else 0 for i in range(n)],
            index=pd.bdate_range("2010-01-04", periods=n),
            dtype=int,
        )
        prices = _make_prices_df([100.0] * n)

        engine = BacktestEngine()
        result = engine.run(prices, signal)

        # position = signal.shift(1); ~50% should be in market
        assert 0.4 < result.metrics.time_in_market < 0.6


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

        assert result.equity_curve_pretax.iloc[-1] > 0
        assert result.metrics.cagr_pretax is not None
        assert not result.equity_curve_pretax.isna().any()

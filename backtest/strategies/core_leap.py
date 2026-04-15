"""Core Stock + LEAP Backtest Strategy.

Orchestrates the full 30% Core + 70% LEAP backtest:
  1. Load underlying prices + VIX
  2. Generate Basic_MA signal (SMA250, entry 1.04×, exit 0.95×)
  3. Simulate portfolio via LEAPSimulator
  4. Compute BacktestMetrics and return a BacktestResult

Validation targets for SPY SMA250, default params (from Google Sheet):
  CAGR    ≈ 25 %
  Sharpe  ≈ 0.64
  MaxDD   ≈ -63 %
  Final   ≈ tens of millions from $1 M

These numbers differ from flat 2.35x leverage (CAGR≈18 %, MaxDD≈-44 %)
because the LEAP simulation models:
  • theta decay (reduces returns slightly vs flat leverage)
  • convexity protection on large down-moves (delta falls, loss smaller)
  • roll transaction costs (bid-ask spread twice per 6 months)
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from backtest.engine import BacktestResult, Trade
from backtest.metrics import BacktestMetrics, calculate_metrics
from backtest.strategies.leap_simulator import LEAPSimulator


class CoreLeapBacktest:
    """Backtests the Core Stock + LEAP strategy.

    Parameters
    ----------
    simulator : LEAPSimulator
        Pre-configured simulator.  If None, uses default params
        (delta=0.80, 6-month expiry, 0.5 % spread, 2 % rf, 30/70 split).
    """

    def __init__(self, simulator: LEAPSimulator | None = None):
        self.simulator = simulator or LEAPSimulator()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        underlying: str = "SPY",
        sma_period: int = 250,
        entry_mult: float = 1.04,
        exit_mult: float = 0.95,
        start: str = "2002-01-01",
        end: str = "2025-12-31",
        initial_capital: float = 1_000_000,
    ) -> BacktestResult:
        """Run the full Core + LEAP backtest.

        Parameters
        ----------
        underlying      : any yfinance ticker (default "SPY")
        sma_period      : SMA lookback for the Basic_MA signal (default 250)
        entry_mult      : entry threshold multiplier on SMA (default 1.04)
        exit_mult       : exit threshold multiplier on SMA (default 0.95)
        start / end     : date range for historical data
        initial_capital : starting portfolio value in dollars

        Returns
        -------
        BacktestResult  : equity_curve, trades, metrics, signal_history, position_history
        """
        from backtest.data import load_ticker_data, load_vix_data
        from backtest.signals import basic_ma_signal

        prices = load_ticker_data(underlying, start=start, end=end)
        vix = load_vix_data(start=start, end=end)

        signal = basic_ma_signal(
            prices["close"],
            period=sma_period,
            entry_mult=entry_mult,
            exit_mult=exit_mult,
        )

        return self._run_from_data(prices, vix, signal, initial_capital)

    def run_from_data(
        self,
        prices: pd.DataFrame,
        vix: pd.DataFrame,
        signal: pd.Series,
        initial_capital: float = 1_000_000,
    ) -> BacktestResult:
        """Run backtest from pre-loaded data (useful for testing without live API).

        Parameters
        ----------
        prices         : DataFrame with 'close' column
        vix            : DataFrame with 'close' column (VIX %, e.g. 20.5)
        signal         : pd.Series of 1/0 aligned with prices.index
        initial_capital: starting portfolio value

        Returns
        -------
        BacktestResult
        """
        return self._run_from_data(prices, vix, signal, initial_capital)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run_from_data(
        self,
        prices: pd.DataFrame,
        vix: pd.DataFrame,
        signal: pd.Series,
        initial_capital: float,
    ) -> BacktestResult:
        equity_curve = self.simulator.simulate(prices, vix, signal, initial_capital)

        position = signal.shift(1).fillna(0)

        # Daily returns for Sharpe calculation
        daily_returns = equity_curve.pct_change().fillna(0)
        strategy_returns = pd.Series(
            np.where(position == 1, daily_returns.values, 0.0),
            index=equity_curve.index,
        )

        trades = self._identify_trades(equity_curve, position)

        metrics = calculate_metrics(
            equity_curve=equity_curve,
            daily_returns=strategy_returns,
            signal=position,
            num_trades=len(trades),
        )

        return BacktestResult(
            equity_curve=equity_curve,
            trades=trades,
            metrics=metrics,
            signal_history=signal,
            position_history=position,
        )

    @staticmethod
    def _identify_trades(
        equity_curve: pd.Series,
        position: pd.Series,
    ) -> list[Trade]:
        """Detect round-trip trades from position transitions."""
        trades: list[Trade] = []
        in_trade = False
        entry_idx: int | None = None

        pos_arr = position.values
        n = len(pos_arr)

        for i in range(1, n):
            prev = pos_arr[i - 1]
            curr = pos_arr[i]

            if not in_trade and prev == 0 and curr == 1:
                in_trade = True
                entry_idx = i

            elif in_trade and prev == 1 and curr == 0:
                in_trade = False
                trades.append(
                    Trade(
                        entry_date=equity_curve.index[entry_idx].date(),
                        exit_date=equity_curve.index[i].date(),
                        entry_equity=float(equity_curve.iloc[entry_idx]),
                        exit_equity=float(equity_curve.iloc[i]),
                    )
                )
                entry_idx = None

        # Close any open trade at end of data
        if in_trade and entry_idx is not None:
            trades.append(
                Trade(
                    entry_date=equity_curve.index[entry_idx].date(),
                    exit_date=equity_curve.index[-1].date(),
                    entry_equity=float(equity_curve.iloc[entry_idx]),
                    exit_equity=float(equity_curve.iloc[-1]),
                )
            )

        return trades

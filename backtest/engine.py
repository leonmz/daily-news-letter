"""Core backtesting engine.

Design:
- Signal[i] = 1 means "enter at close of day i; hold through day i+1".
- The engine uses signal.shift(1): position on day i is determined by signal[i-1].
- Fees applied only when in market (daily: (1-annual_fee)^(1/252)).
- Phase 1: pre-tax only. Tax simulation deferred to Phase 3.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from .metrics import BacktestMetrics, calculate_metrics


@dataclass
class Trade:
    entry_date: date
    exit_date: date
    entry_equity: float
    exit_equity: float

    @property
    def pct_return(self) -> float:
        if self.entry_equity == 0:
            return 0.0
        return (self.exit_equity - self.entry_equity) / self.entry_equity

    @property
    def duration_days(self) -> int:
        return (
            pd.Timestamp(self.exit_date) - pd.Timestamp(self.entry_date)
        ).days


@dataclass
class BacktestResult:
    equity_curve: pd.Series
    trades: list[Trade]
    metrics: BacktestMetrics
    signal_history: pd.Series    # raw signal from the generator
    position_history: pd.Series  # shifted signal actually applied to returns


class BacktestEngine:
    """Signal-based backtester. Pre-tax only."""

    def run(
        self,
        prices: pd.DataFrame,
        signal: pd.Series,
        initial_capital: float = 1_000_000,
        annual_fee: float = 0.0009,
        leverage: float = 1.0,
    ) -> BacktestResult:
        """Run backtest.

        Args:
            prices: DataFrame with a 'close' column, DatetimeIndex.
            signal: Series of 1/0 aligned with prices.index.
            initial_capital: Starting portfolio value in dollars.
            annual_fee: Annual expense ratio applied daily when in market.
            leverage: Return multiplier when in market (default 1.0 = unlevered).
                      Daily return is clipped at -100% to prevent negative equity.
                      Use 2.35 to replicate the Google Sheet's Core+LEAP structure:
                      ~30% core stock + 70% deep-ITM LEAP ≈ 2.35x effective leverage,
                      producing ~18% CAGR / 0.67 Sharpe / -44% MaxDD on SPY SMA250.

        Returns:
            BacktestResult with equity_curve, trades, and metrics.
        """
        close = prices["close"].reindex(signal.index).ffill()

        # Position: today's return earned based on yesterday's signal
        position = signal.shift(1).fillna(0)

        daily_fee_factor = (1 - annual_fee) ** (1 / 252)
        price_returns = close.pct_change().fillna(0)

        # Apply leverage; clip at -100% so equity can never go negative
        levered_returns = (price_returns * leverage).clip(lower=-1.0)

        # Equity curve: compound daily
        equity_factors = np.where(
            position == 1,
            (1 + levered_returns) * daily_fee_factor,
            1.0,
        )
        equity_values = initial_capital * np.cumprod(equity_factors)
        equity_curve = pd.Series(equity_values, index=close.index)

        # Trade tracking
        trades = self._identify_trades(close, position, equity_curve)

        # Daily returns for Sharpe (levered, only days in market)
        strategy_returns = pd.Series(
            np.where(position == 1, levered_returns, 0.0),
            index=close.index,
        )

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

    def _identify_trades(
        self,
        close: pd.Series,
        position: pd.Series,
        equity_curve: pd.Series,
    ) -> list[Trade]:
        """Extract round-trip trades from the position series."""
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
                        entry_date=close.index[entry_idx].date(),
                        exit_date=close.index[i].date(),
                        entry_equity=float(equity_curve.iloc[entry_idx]),
                        exit_equity=float(equity_curve.iloc[i]),
                    )
                )
                entry_idx = None

        # Close any open trade at end of data
        if in_trade and entry_idx is not None:
            trades.append(
                Trade(
                    entry_date=close.index[entry_idx].date(),
                    exit_date=close.index[-1].date(),
                    entry_equity=float(equity_curve.iloc[entry_idx]),
                    exit_equity=float(equity_curve.iloc[-1]),
                )
            )

        return trades

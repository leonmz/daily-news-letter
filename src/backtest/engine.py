"""Core backtesting engine.

Design:
- Signal[i] = 1 means "enter at close of day i, exit at close of day i+1 or later".
- The engine uses signal.shift(1): position on day i is determined by signal[i-1].
- Fees applied only when in market (daily: (1-annual_fee)^(1/252)).
- Tax applied at each trade exit: 37.1% on gains (federal 23.8% + CA 13.3%).
- Losses are not taxed (simplified: no tax-loss harvesting in Phase 1).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from .metrics import BacktestMetrics, calculate_metrics

# Combined tax rate: federal LTCG 20% + NIIT 3.8% + CA 13.3%
TAX_RATE = 0.238 + 0.133  # 0.371


@dataclass
class Trade:
    entry_date: date
    exit_date: date
    entry_equity: float   # Portfolio value when entering
    exit_equity_pretax: float
    gain: float           # exit_equity_pretax - entry_equity
    tax_paid: float
    exit_equity_aftertax: float

    @property
    def pct_return(self) -> float:
        return (self.exit_equity_pretax - self.entry_equity) / self.entry_equity


@dataclass
class BacktestResult:
    equity_curve_pretax: pd.Series
    equity_curve_aftertax: pd.Series
    trades: list[Trade]
    metrics: BacktestMetrics
    signal_history: pd.Series   # the raw signal (not shifted)
    position_history: pd.Series  # shifted signal actually applied


class BacktestEngine:
    """Signal-based backtester with tax simulation."""

    def run(
        self,
        prices: pd.DataFrame,
        signal: pd.Series,
        initial_capital: float = 1_000_000,
        annual_fee: float = 0.0009,
    ) -> BacktestResult:
        """Run backtest.

        Args:
            prices: DataFrame with a 'close' column, DatetimeIndex.
            signal: Series of 1/0 aligned with prices.index.
            initial_capital: Starting portfolio value in dollars.
            annual_fee: Annual expense ratio (applied daily when in market).

        Returns:
            BacktestResult.
        """
        close = prices["close"].reindex(signal.index).ffill()

        # Position: today's return is earned based on yesterday's signal
        position = signal.shift(1).fillna(0)

        daily_fee_factor = (1 - annual_fee) ** (1 / 252)
        price_returns = close.pct_change().fillna(0)

        # --- Pre-tax equity curve ---
        # Each day: multiply by (1 + return)*fee_factor if in market, else 1.0
        equity_factors = np.where(
            position == 1,
            (1 + price_returns) * daily_fee_factor,
            1.0,
        )
        equity_pretax = initial_capital * np.cumprod(equity_factors)
        equity_pretax_series = pd.Series(equity_pretax, index=close.index)

        # --- Trade identification and after-tax equity curve ---
        trades, equity_aftertax_series = self._simulate_with_tax(
            close, position, price_returns, initial_capital, annual_fee, equity_pretax_series
        )

        # Daily strategy returns (for Sharpe) — use pre-tax position returns
        strategy_returns = pd.Series(
            np.where(position == 1, price_returns, 0.0),
            index=close.index,
        )

        num_trades = len(trades)
        metrics = calculate_metrics(
            equity_pretax_series,
            equity_aftertax_series,
            strategy_returns,
            position,
            num_trades,
        )

        return BacktestResult(
            equity_curve_pretax=equity_pretax_series,
            equity_curve_aftertax=equity_aftertax_series,
            trades=trades,
            metrics=metrics,
            signal_history=signal,
            position_history=position,
        )

    def _simulate_with_tax(
        self,
        close: pd.Series,
        position: pd.Series,
        price_returns: pd.Series,
        initial_capital: float,
        annual_fee: float,
        equity_pretax_series: pd.Series,
    ) -> tuple[list[Trade], pd.Series]:
        """Walk forward trade-by-trade, applying tax at each exit.

        The after-tax equity diverges from the pre-tax equity because
        each trade exit reduces capital by the tax owed on gains.
        """
        daily_fee_factor = (1 - annual_fee) ** (1 / 252)
        n = len(close)
        equity_at = np.empty(n)
        equity_at[0] = initial_capital

        trades: list[Trade] = []

        current_equity = initial_capital
        trade_entry_equity: float | None = None
        trade_entry_date: date | None = None
        in_trade = False

        for i in range(1, n):
            prev_pos = position.iloc[i - 1]
            curr_pos = position.iloc[i]

            if prev_pos == 1:
                ret = price_returns.iloc[i]
                current_equity *= (1 + ret) * daily_fee_factor
            # else: in cash, no change

            # Detect entry: we just started being in market today
            if prev_pos == 0 and curr_pos == 1 and not in_trade:
                in_trade = True
                trade_entry_equity = current_equity
                trade_entry_date = close.index[i].date()

            # Detect exit: position flips 1→0 (or end of data while in trade)
            if in_trade and prev_pos == 1 and curr_pos == 0:
                in_trade = False
                exit_equity_pretax = current_equity
                gain = exit_equity_pretax - trade_entry_equity
                tax = max(0.0, gain * TAX_RATE)
                current_equity -= tax
                exit_equity_aftertax = current_equity

                trades.append(
                    Trade(
                        entry_date=trade_entry_date,
                        exit_date=close.index[i].date(),
                        entry_equity=trade_entry_equity,
                        exit_equity_pretax=exit_equity_pretax,
                        gain=gain,
                        tax_paid=tax,
                        exit_equity_aftertax=exit_equity_aftertax,
                    )
                )
                trade_entry_equity = None
                trade_entry_date = None

            equity_at[i] = current_equity

        # If still in trade at end of data, close it
        if in_trade and trade_entry_equity is not None:
            exit_equity_pretax = current_equity
            gain = exit_equity_pretax - trade_entry_equity
            tax = max(0.0, gain * TAX_RATE)
            after_tax = current_equity - tax
            trades.append(
                Trade(
                    entry_date=trade_entry_date,
                    exit_date=close.index[-1].date(),
                    entry_equity=trade_entry_equity,
                    exit_equity_pretax=exit_equity_pretax,
                    gain=gain,
                    tax_paid=tax,
                    exit_equity_aftertax=after_tax,
                )
            )
            # Note: we don't update equity_at[-1] here since we show
            # the "if we liquidated today" after-tax value separately.
            # For the equity curve, we keep current_equity (no liquidation).

        equity_aftertax_series = pd.Series(equity_at, index=close.index)
        return trades, equity_aftertax_series

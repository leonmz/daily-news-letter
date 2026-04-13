"""Performance metrics for backtesting results."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd


@dataclass
class BacktestMetrics:
    cagr: float              # Annualized return (pre-tax)
    sharpe: float            # Sharpe ratio (annualized, rf=2%)
    max_drawdown: float      # Max drawdown as negative fraction, e.g. -0.45
    max_dd_start: date
    max_dd_end: date
    time_in_market: float    # Fraction of days in market
    num_trades: int
    final_value: float


def calculate_cagr(equity_curve: pd.Series) -> float:
    """Compound Annual Growth Rate.

    Args:
        equity_curve: Portfolio value indexed by date.

    Returns:
        CAGR as a decimal (e.g. 0.18 for 18%).
    """
    curve = equity_curve.dropna()
    if len(curve) < 2:
        return 0.0
    start = curve.iloc[0]
    end = curve.iloc[-1]
    n_days = (curve.index[-1] - curve.index[0]).days
    years = n_days / 365.25
    if years <= 0 or start <= 0:
        return 0.0
    return (end / start) ** (1 / years) - 1


def calculate_sharpe(returns: pd.Series, risk_free_rate: float = 0.02) -> float:
    """Annualized Sharpe ratio.

    Args:
        returns: Daily strategy returns (not cumulative).
        risk_free_rate: Annual risk-free rate.

    Returns:
        Sharpe ratio.
    """
    rf_daily = risk_free_rate / 252
    excess = returns - rf_daily
    std = excess.std()
    if std == 0:
        return 0.0
    return float((excess.mean() / std) * np.sqrt(252))


def calculate_max_drawdown(equity_curve: pd.Series) -> tuple[float, date, date]:
    """Maximum drawdown from peak to trough.

    Args:
        equity_curve: Portfolio value indexed by date.

    Returns:
        (max_drawdown_fraction, peak_date, trough_date)
        max_drawdown_fraction is negative, e.g. -0.456.
    """
    curve = equity_curve.dropna()
    running_max = curve.cummax()
    drawdown = (curve - running_max) / running_max

    min_dd = float(drawdown.min())
    trough_date = drawdown.idxmin()
    peak_date = running_max[:trough_date].idxmax()

    return min_dd, peak_date.date(), trough_date.date()


def calculate_metrics(
    equity_curve: pd.Series,
    daily_returns: pd.Series,
    signal: pd.Series,
    num_trades: int,
) -> BacktestMetrics:
    """Compute all metrics from equity curve and position signal.

    Args:
        equity_curve: Portfolio value over time.
        daily_returns: Strategy daily returns (used for Sharpe).
        signal: Shifted position (1=in market) as actually applied.
        num_trades: Number of completed round-trip trades.

    Returns:
        BacktestMetrics dataclass.
    """
    cagr = calculate_cagr(equity_curve)
    sharpe = calculate_sharpe(daily_returns)
    max_dd, dd_start, dd_end = calculate_max_drawdown(equity_curve)
    time_in_market = float(signal.mean())

    return BacktestMetrics(
        cagr=cagr,
        sharpe=sharpe,
        max_drawdown=max_dd,
        max_dd_start=dd_start,
        max_dd_end=dd_end,
        time_in_market=time_in_market,
        num_trades=num_trades,
        final_value=float(equity_curve.iloc[-1]),
    )

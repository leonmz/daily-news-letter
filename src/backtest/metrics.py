"""Performance metrics for backtesting results."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd


@dataclass
class BacktestMetrics:
    cagr_pretax: float          # Annualized return before taxes
    cagr_aftertax: float        # Annualized return after taxes
    sharpe: float               # Sharpe ratio (annualized, rf=2%)
    max_drawdown: float         # Max drawdown as negative fraction, e.g. -0.45
    max_dd_start: date          # Date drawdown peak began
    max_dd_end: date            # Date trough hit
    time_in_market: float       # Fraction of days in market, e.g. 0.72
    num_trades: int             # Number of round-trip trades
    final_value_pretax: float
    final_value_aftertax: float


def calculate_cagr(equity_curve: pd.Series) -> float:
    """Compound Annual Growth Rate.

    Args:
        equity_curve: Portfolio value indexed by date.

    Returns:
        CAGR as a decimal (e.g. 0.18 for 18%).
    """
    start = equity_curve.dropna().iloc[0]
    end = equity_curve.dropna().iloc[-1]
    n_days = (equity_curve.index[-1] - equity_curve.index[0]).days
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
    if excess.std() == 0:
        return 0.0
    return (excess.mean() / excess.std()) * np.sqrt(252)


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

    min_dd = drawdown.min()
    trough_date = drawdown.idxmin()

    # Peak is the last time the running max was at the trough-day value
    peak_date = running_max[:trough_date].idxmax()

    return float(min_dd), peak_date.date(), trough_date.date()


def calculate_metrics(
    equity_curve_pretax: pd.Series,
    equity_curve_aftertax: pd.Series,
    daily_returns: pd.Series,
    signal: pd.Series,
    num_trades: int,
) -> BacktestMetrics:
    """Compute all metrics from equity curves and signal.

    Args:
        equity_curve_pretax: Pre-tax portfolio value.
        equity_curve_aftertax: After-tax portfolio value.
        daily_returns: Strategy daily returns (pre-tax, used for Sharpe).
        signal: Shifted position signal (1 = in market) as applied.
        num_trades: Number of completed round-trip trades.

    Returns:
        BacktestMetrics dataclass.
    """
    cagr_pre = calculate_cagr(equity_curve_pretax)
    cagr_after = calculate_cagr(equity_curve_aftertax)
    sharpe = calculate_sharpe(daily_returns)
    max_dd, dd_start, dd_end = calculate_max_drawdown(equity_curve_aftertax)
    time_in_market = float(signal.mean())

    return BacktestMetrics(
        cagr_pretax=cagr_pre,
        cagr_aftertax=cagr_after,
        sharpe=sharpe,
        max_drawdown=max_dd,
        max_dd_start=dd_start,
        max_dd_end=dd_end,
        time_in_market=time_in_market,
        num_trades=num_trades,
        final_value_pretax=float(equity_curve_pretax.iloc[-1]),
        final_value_aftertax=float(equity_curve_aftertax.iloc[-1]),
    )

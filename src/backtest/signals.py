"""Signal generators for backtesting strategies.

Each function returns a pandas Series of 1 (in market) or 0 (out of market),
indexed by date, aligned with the input prices index.

Signal semantics: signal[i] = 1 means "be in market from day i's close
to day i+1's close". The engine shifts the signal by 1 before applying returns.
"""

import pandas as pd
import numpy as np


def basic_ma_signal(
    prices: pd.Series,
    period: int = 250,
    entry_mult: float = 1.04,
    exit_mult: float = 0.95,
) -> pd.Series:
    """Basic MA with hysteresis band.

    Entry: close > SMA(period) * entry_mult
    Exit:  close < SMA(period) * exit_mult

    Hysteresis prevents whipsaw: entry and exit thresholds differ,
    creating a band where the current position is held unchanged.

    Args:
        prices: Daily close prices (pd.Series indexed by date).
        period: SMA lookback period in trading days.
        entry_mult: Multiplier above SMA required to enter market.
        exit_mult: Multiplier below SMA required to exit market.

    Returns:
        pd.Series of 1/0 aligned with prices index.
    """
    sma = prices.rolling(period).mean()

    signal = pd.Series(0, index=prices.index, dtype=int)
    in_market = False

    for i in range(len(prices)):
        if pd.isna(sma.iloc[i]):
            signal.iloc[i] = 0
            continue

        close = prices.iloc[i]
        sma_val = sma.iloc[i]

        if not in_market and close > sma_val * entry_mult:
            in_market = True
        elif in_market and close < sma_val * exit_mult:
            in_market = False

        signal.iloc[i] = 1 if in_market else 0

    return signal


def vix_optimized_signal(
    prices: pd.Series,
    vix: pd.Series,
    period: int = 250,
    entry_mult: float = 1.04,
    exit_mult: float = 0.95,
    vix_entry_max: float = 25.0,
    vix_exit_min: float = 30.0,
) -> pd.Series:
    """Basic MA + VIX filter.

    Same as basic_ma_signal but with VIX conditions:
    - Can only enter if VIX <= vix_entry_max
    - Must exit if VIX >= vix_exit_min (overrides MA signal)

    Args:
        prices: Daily close prices.
        vix: Daily VIX close values (must share date index or be alignable).
        period: SMA lookback period.
        entry_mult: Multiplier above SMA to enter.
        exit_mult: Multiplier below SMA to exit.
        vix_entry_max: Max VIX allowed to enter.
        vix_exit_min: VIX level that forces exit.

    Returns:
        pd.Series of 1/0.
    """
    sma = prices.rolling(period).mean()

    # Align VIX to prices index (forward-fill gaps like weekends)
    vix_aligned = vix.reindex(prices.index).ffill()

    signal = pd.Series(0, index=prices.index, dtype=int)
    in_market = False

    for i in range(len(prices)):
        if pd.isna(sma.iloc[i]):
            signal.iloc[i] = 0
            continue

        close = prices.iloc[i]
        sma_val = sma.iloc[i]
        vix_val = vix_aligned.iloc[i]

        # VIX force-exit overrides everything
        if in_market and not pd.isna(vix_val) and vix_val >= vix_exit_min:
            in_market = False
        elif in_market and close < sma_val * exit_mult:
            in_market = False
        elif not in_market and close > sma_val * entry_mult:
            # VIX gate: only enter if VIX is calm enough
            if pd.isna(vix_val) or vix_val <= vix_entry_max:
                in_market = True

        signal.iloc[i] = 1 if in_market else 0

    return signal


def dual_ma_signal(
    prices: pd.Series,
    fast: int = 50,
    slow: int = 200,
) -> pd.Series:
    """Golden cross / death cross signal.

    Entry: fast SMA crosses above slow SMA (golden cross).
    Exit:  fast SMA crosses below slow SMA (death cross).

    Args:
        prices: Daily close prices.
        fast: Fast SMA period.
        slow: Slow SMA period.

    Returns:
        pd.Series of 1/0.
    """
    fast_sma = prices.rolling(fast).mean()
    slow_sma = prices.rolling(slow).mean()

    signal = pd.Series(0, index=prices.index, dtype=int)
    in_market = False

    for i in range(len(prices)):
        if pd.isna(fast_sma.iloc[i]) or pd.isna(slow_sma.iloc[i]):
            signal.iloc[i] = 0
            continue

        fast_val = fast_sma.iloc[i]
        slow_val = slow_sma.iloc[i]

        if not in_market and fast_val > slow_val:
            in_market = True
        elif in_market and fast_val < slow_val:
            in_market = False

        signal.iloc[i] = 1 if in_market else 0

    return signal

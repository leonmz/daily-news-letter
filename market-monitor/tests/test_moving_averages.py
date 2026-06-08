"""Unit tests for monitor.moving_averages — pure functions, no network I/O."""

import numpy as np
import pandas as pd

from monitor.moving_averages import compute_ma_comparison

PERIODS = [5, 10, 50, 200]


def _df(closes) -> pd.DataFrame:
    idx = pd.date_range(end="2026-01-01", periods=len(closes), freq="B")
    return pd.DataFrame({"Close": np.asarray(closes, dtype=float)}, index=idx)


def _uptrend(n: int, start: float = 100.0, step: float = 1.0) -> pd.DataFrame:
    return _df([start + i * step for i in range(n)])


def test_all_above_strong_uptrend():
    res = compute_ma_comparison("SPY", _uptrend(260), PERIODS)
    assert res is not None
    assert res.ticker == "SPY"
    assert [lv.period for lv in res.levels] == PERIODS
    for lv in res.levels:
        assert lv.above is True
        assert lv.deviation_pct > 0


def test_insufficient_history_boundary():
    # Needs max(period)+1 = 201 rows.
    assert compute_ma_comparison("SPY", _uptrend(200), PERIODS) is None
    assert compute_ma_comparison("SPY", _uptrend(201), PERIODS) is not None


def test_custom_periods():
    res = compute_ma_comparison("SPY", _uptrend(60), [5, 10, 50])
    assert res is not None
    assert [lv.period for lv in res.levels] == [5, 10, 50]


def test_mixed_above_below():
    # Long uptrend then a short shallow pullback: short SMAs end up above price
    # (recent decline), long SMA stays below price (still in the uptrend).
    up = [100.0 + i for i in range(260)]
    down = [up[-1] - 3.0 * (k + 1) for k in range(8)]
    res = compute_ma_comparison("QQQ", _df(up + down), PERIODS)
    assert res is not None
    for lv in res.levels:
        assert lv.above == (lv.deviation_pct >= 0)
    assert any(not lv.above for lv in res.levels)
    assert any(lv.above for lv in res.levels)


def test_no_close_or_empty():
    assert compute_ma_comparison("SPY", pd.DataFrame({"Open": [1, 2, 3]}), PERIODS) is None
    assert compute_ma_comparison("SPY", pd.DataFrame(), PERIODS) is None

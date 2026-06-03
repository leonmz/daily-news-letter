"""Unit tests for newsletter.moving_averages — pure-function tests, no network I/O."""

import numpy as np
import pandas as pd

from newsletter.moving_averages import (
    compute_ma_comparison,
    format_ma_section,
    MAComparison,
    MALevel,
    SMA_PERIODS,
)


def _make_df(closes: np.ndarray) -> pd.DataFrame:
    """Build a minimal OHLCV-style DataFrame with the given Close series."""
    idx = pd.date_range(end="2025-01-01", periods=len(closes), freq="B")
    return pd.DataFrame({"Close": closes}, index=idx)


def _strong_uptrend(n: int = 260, start: float = 100.0, step: float = 1.0) -> pd.DataFrame:
    """Monotonic strong-uptrend Close series so price >> every SMA."""
    closes = np.array([start + i * step for i in range(n)], dtype=float)
    return _make_df(closes)


# 1. All SMAs below price (strong uptrend)
def test_all_above():
    df = _strong_uptrend(n=260, start=100.0, step=1.0)
    result = compute_ma_comparison("QQQ", df)

    assert result is not None
    assert result.ticker == "QQQ"
    assert len(result.levels) == 4
    assert [lv.period for lv in result.levels] == [50, 100, 200, 250]
    for lv in result.levels:
        assert lv.above is True, f"SMA{lv.period} expected above=True, got {lv.above}"
        assert lv.deviation_pct > 0, (
            f"SMA{lv.period} expected deviation_pct>0, got {lv.deviation_pct}"
        )


# 2. Mixed above/below: long uptrend then sharp pullback
def test_mixed_above_below():
    # 200 days of steady uptrend, then 60 days of decline.
    up = np.array([100.0 + i * 1.0 for i in range(200)], dtype=float)        # 100 -> 299
    down = np.array([299.0 - (i + 1) * 1.5 for i in range(60)], dtype=float)  # 299 -> 209
    closes = np.concatenate([up, down])
    df = _make_df(closes)

    result = compute_ma_comparison("QQQ", df)
    assert result is not None
    assert len(result.levels) == 4

    # The above flag must match the deviation sign (above iff deviation_pct >= 0).
    for lv in result.levels:
        assert lv.above == (lv.deviation_pct >= 0), (
            f"SMA{lv.period}: above={lv.above} but deviation_pct={lv.deviation_pct}"
        )

    # At least one level must be below (we want a real mix, not all-True/all-False).
    above_flags = [lv.above for lv in result.levels]
    assert any(flag is False for flag in above_flags), (
        f"Expected at least one SMA below price; got above_flags={above_flags}"
    )

    # Specifically, SMA250 should be below price (price ~209, SMA250 mean is
    # over a long uptrend window so its average ~> 209).
    sma250 = next(lv for lv in result.levels if lv.period == 250)
    assert sma250.above is False, (
        f"Expected SMA250 above=False after pullback; got value={sma250.value}, price={result.price}"
    )


# 3. Explicit level count and ordering
def test_level_count_and_periods():
    df = _strong_uptrend(n=260)
    result = compute_ma_comparison("QQQ", df)

    assert result is not None
    assert len(result.levels) == 4
    assert [lv.period for lv in result.levels] == [50, 100, 200, 250]
    assert [lv.period for lv in result.levels] == SMA_PERIODS


# 4. Insufficient history → None; boundary checks at 250 and 251
def test_insufficient_history():
    # 200 rows — way under SMA250 requirement.
    df_200 = _strong_uptrend(n=200)
    assert compute_ma_comparison("QQQ", df_200) is None

    # 250 rows — still one short (needs max(SMA_PERIODS)+1 = 251).
    df_250 = _strong_uptrend(n=250)
    assert compute_ma_comparison("QQQ", df_250) is None

    # 251 rows — exactly enough.
    df_251 = _strong_uptrend(n=251)
    result = compute_ma_comparison("QQQ", df_251)
    assert result is not None
    assert len(result.levels) == 4


# 5. Markdown rendering contains all expected elements
def test_format_markdown():
    comparison = MAComparison(
        ticker="QQQ",
        price=500.0,
        levels=[
            MALevel(period=50, value=480.0, deviation_pct=4.17, above=True),
            MALevel(period=200, value=520.0, deviation_pct=-3.85, above=False),
        ],
    )
    out = format_ma_section([comparison])

    assert "## 📈 SMA Comparison" in out
    assert "**QQQ**" in out
    assert "$500.00" in out
    assert "🟢" in out
    assert "🔴" in out
    assert "SMA" in out

    # Need at least one positive (+X.X%) and one negative (-X.X%) deviation.
    import re
    assert re.search(r"\+\d+\.\d%", out), f"Expected a +X.X% in output:\n{out}"
    assert re.search(r"-\d+\.\d%", out), f"Expected a -X.X% in output:\n{out}"


# 6. Empty input → empty string
def test_format_empty():
    assert format_ma_section([]) == ""

"""Unit tests for FREDProvider — all fredapi calls mocked."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.providers.fred import FREDProvider
from src.providers.base import AuthError


# ─── Construction ─────────────────────────────────────────────────────────────

def test_requires_api_key():
    with pytest.raises(AuthError):
        FREDProvider("")


# ─── get_indicator ────────────────────────────────────────────────────────────

def _make_series(values: list, dates: list[str]) -> pd.Series:
    idx = pd.to_datetime(dates)
    return pd.Series(values, index=idx)


@pytest.mark.asyncio
async def test_get_indicator_fedfunds():
    provider = FREDProvider("testkey")

    series = _make_series([4.25], ["2026-03-19"])

    with patch.object(provider, "_get_client") as mock_fn:
        fred = MagicMock()
        mock_fn.return_value = fred
        fred.get_series.return_value = series

        result = await provider.get_indicator("FEDFUNDS")

    assert result is not None
    assert result.series_id == "FEDFUNDS"
    assert result.value == pytest.approx(4.25)
    assert result.unit == "percent"
    assert result.source == "fred"


@pytest.mark.asyncio
async def test_get_indicator_skips_nan_and_uses_prior():
    """If most recent value is NaN, should fall back to second-to-last."""
    import math
    provider = FREDProvider("testkey")

    series = _make_series(
        [4.25, float("nan")],
        ["2026-03-01", "2026-04-01"],
    )

    with patch.object(provider, "_get_client") as mock_fn:
        fred = MagicMock()
        mock_fn.return_value = fred
        fred.get_series.return_value = series

        result = await provider.get_indicator("FEDFUNDS")

    assert result is not None
    assert result.value == pytest.approx(4.25)


@pytest.mark.asyncio
async def test_get_indicator_empty_series_returns_none():
    provider = FREDProvider("testkey")

    with patch.object(provider, "_get_client") as mock_fn:
        fred = MagicMock()
        mock_fn.return_value = fred
        fred.get_series.return_value = pd.Series([], dtype=float)

        result = await provider.get_indicator("FEDFUNDS")

    assert result is None


@pytest.mark.asyncio
async def test_get_indicator_exception_returns_none():
    provider = FREDProvider("testkey")

    with patch.object(provider, "_get_client") as mock_fn:
        fred = MagicMock()
        mock_fn.return_value = fred
        fred.get_series.side_effect = RuntimeError("network error")

        result = await provider.get_indicator("FEDFUNDS")

    assert result is None


# ─── get_yield_curve ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_yield_curve_returns_points():
    provider = FREDProvider("testkey")

    def mock_get_series(series_id, **kwargs):
        rates = {
            "DGS1MO": 4.30, "DGS3MO": 4.35, "DGS6MO": 4.32,
            "DGS1": 4.28, "DGS2": 4.10, "DGS5": 4.05,
            "DGS10": 4.15, "DGS20": 4.40, "DGS30": 4.45,
        }
        rate = rates.get(series_id, 4.0)
        return _make_series([rate], ["2026-04-10"])

    with patch.object(provider, "_get_client") as mock_fn:
        fred = MagicMock()
        mock_fn.return_value = fred
        fred.get_series.side_effect = mock_get_series

        curve = await provider.get_yield_curve()

    assert curve is not None
    assert len(curve.points) == 9  # all 9 maturities
    rate_10y = curve.get_rate("10Y")
    rate_2y = curve.get_rate("2Y")
    assert rate_10y == pytest.approx(4.15)
    assert rate_2y == pytest.approx(4.10)
    spread = curve.spread_10y_2y()
    assert spread == pytest.approx(0.05)
    assert curve.is_inverted is False


@pytest.mark.asyncio
async def test_get_yield_curve_detects_inversion():
    provider = FREDProvider("testkey")

    def mock_get_series(series_id, **kwargs):
        # 2Y > 10Y → inverted
        rates = {
            "DGS1MO": 5.50, "DGS3MO": 5.40, "DGS6MO": 5.30,
            "DGS1": 5.20, "DGS2": 5.00, "DGS5": 4.50,
            "DGS10": 4.20, "DGS20": 4.30, "DGS30": 4.40,
        }
        rate = rates.get(series_id, 4.0)
        return _make_series([rate], ["2026-04-10"])

    with patch.object(provider, "_get_client") as mock_fn:
        fred = MagicMock()
        mock_fn.return_value = fred
        fred.get_series.side_effect = mock_get_series

        curve = await provider.get_yield_curve()

    assert curve is not None
    assert curve.is_inverted is True
    spread = curve.spread_10y_2y()
    assert spread < 0


@pytest.mark.asyncio
async def test_get_yield_curve_exception_returns_none():
    provider = FREDProvider("testkey")

    with patch.object(provider, "_get_client") as mock_fn:
        fred = MagicMock()
        mock_fn.return_value = fred
        fred.get_series.side_effect = RuntimeError("FRED down")

        curve = await provider.get_yield_curve()

    assert curve is None

"""FRED (Federal Reserve Economic Data) provider via fredapi SDK."""

import logging
import math
from datetime import datetime, timezone
from typing import Optional

from src.models.macro import MacroIndicator, YieldCurve, YieldCurvePoint
from src.providers.base import AuthError

logger = logging.getLogger(__name__)

_SOURCE = "fred"

_YIELD_SERIES = {
    "1M": "DGS1MO", "3M": "DGS3MO", "6M": "DGS6MO",
    "1Y": "DGS1", "2Y": "DGS2", "5Y": "DGS5",
    "10Y": "DGS10", "20Y": "DGS20", "30Y": "DGS30",
}

_SERIES_NAMES = {
    "FEDFUNDS": ("Federal Funds Rate", "percent", "monthly"),
    "DGS10": ("10-Year Treasury Yield", "percent", "daily"),
    "DGS2": ("2-Year Treasury Yield", "percent", "daily"),
    "DGS1MO": ("1-Month Treasury Yield", "percent", "daily"),
    "CPIAUCSL": ("CPI All Urban Consumers", "index", "monthly"),
    "CPILFESL": ("Core CPI (ex food & energy)", "index", "monthly"),
    "UNRATE": ("Unemployment Rate", "percent", "monthly"),
    "GDP": ("Real GDP", "billions", "quarterly"),
    "M2SL": ("M2 Money Supply", "billions", "monthly"),
    "DEXUSEU": ("USD/EUR Exchange Rate", "rate", "daily"),
}


def _first_valid(series) -> tuple[Optional[float], Optional[datetime]]:
    """Return the first non-NaN (value, date) from a descending FRED series."""
    for i in range(len(series) - 1, -1, -1):
        v = float(series.iloc[i])
        try:
            if not math.isnan(v):
                dt = series.index[i].to_pydatetime()
                return v, dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            continue
    return None, None


class FREDProvider:
    def __init__(self, api_key: str):
        if not api_key:
            raise AuthError("FRED_API_KEY is required")
        self._api_key = api_key
        self._client = None

    def _get_client(self):
        if self._client is None:
            from fredapi import Fred
            self._client = Fred(api_key=self._api_key)
        return self._client

    async def get_indicator(self, series_id: str) -> Optional[MacroIndicator]:
        try:
            series = self._get_client().get_series(series_id, limit=5, sort_order="desc")
            if series is None or series.empty:
                logger.warning("FRED: no data for series %s", series_id)
                return None

            value, obs_dt = _first_valid(series)
            if value is None:
                logger.warning("FRED: all recent observations are NaN for %s", series_id)
                return None

            name, unit, freq = _SERIES_NAMES.get(series_id, (series_id, "value", None))
            return MacroIndicator(
                series_id=series_id, name=name, value=value, unit=unit,
                observation_date=obs_dt, source=_SOURCE, frequency=freq,
            )
        except Exception as e:
            logger.error("FRED get_indicator(%s) failed: %s", series_id, e)
            return None

    async def get_yield_curve(self) -> Optional[YieldCurve]:
        try:
            fred = self._get_client()
            points, obs_dates = [], []

            for maturity, series_id in _YIELD_SERIES.items():
                try:
                    series = fred.get_series(series_id, limit=5, sort_order="desc")
                    if series is None or series.empty:
                        continue
                    val, obs_date = _first_valid(series)
                    if val is None:
                        continue
                    points.append(YieldCurvePoint(
                        maturity=maturity, rate=val, series_id=series_id,
                        observation_date=obs_date, source=_SOURCE,
                    ))
                    obs_dates.append(obs_date)
                except Exception as e:
                    logger.debug("FRED yield curve %s failed: %s", series_id, e)

            if not points:
                return None

            curve = YieldCurve(
                points=points, as_of=max(obs_dates), source=_SOURCE,
            )
            spread = curve.spread_10y_2y()
            if spread is not None:
                curve.is_inverted = spread < 0
            return curve
        except Exception as e:
            logger.error("FRED get_yield_curve failed: %s", e)
            return None

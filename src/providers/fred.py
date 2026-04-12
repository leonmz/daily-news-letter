"""FRED (Federal Reserve Economic Data) provider via fredapi SDK."""

import logging
from datetime import datetime, timezone
from typing import Optional

from src.models.macro import MacroIndicator, YieldCurve, YieldCurvePoint
from src.providers.base import AuthError, ProviderError

logger = logging.getLogger(__name__)

_SOURCE = "fred"

# FRED series IDs for yield curve maturities
_YIELD_SERIES = {
    "1M": "DGS1MO",
    "3M": "DGS3MO",
    "6M": "DGS6MO",
    "1Y": "DGS1",
    "2Y": "DGS2",
    "5Y": "DGS5",
    "10Y": "DGS10",
    "20Y": "DGS20",
    "30Y": "DGS30",
}

# Human-readable names for common series
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


class FREDProvider:
    """
    FRED economic data provider.

    Free API, no rate limit for reasonable use.
    Returns the most recent observation for any series.
    """

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
        """
        Return the latest observation for a FRED series.
        series_id examples: "FEDFUNDS", "UNRATE", "CPIAUCSL", "DGS10"
        """
        try:
            fred = self._get_client()
            series = fred.get_series(series_id, limit=1, sort_order="desc")
            if series is None or series.empty:
                logger.warning("FRED: no data for series %s", series_id)
                return None

            latest_date = series.index[-1]
            latest_value = float(series.iloc[-1])

            if pd_is_nan(latest_value):
                # Try second-to-last
                if len(series) > 1:
                    latest_date = series.index[-2]
                    latest_value = float(series.iloc[-2])
                else:
                    return None

            name, unit, freq = _SERIES_NAMES.get(series_id, (series_id, "value", None))

            obs_dt = latest_date.to_pydatetime()
            if obs_dt.tzinfo is None:
                obs_dt = obs_dt.replace(tzinfo=timezone.utc)

            return MacroIndicator(
                series_id=series_id,
                name=name,
                value=latest_value,
                unit=unit,
                observation_date=obs_dt,
                source=_SOURCE,
                frequency=freq,
            )

        except Exception as e:
            logger.error("FRED get_indicator(%s) failed: %s", series_id, e)
            return None

    async def get_yield_curve(self) -> Optional[YieldCurve]:
        """Fetch current yield curve (1M through 30Y Treasury yields)."""
        try:
            fred = self._get_client()
            points = []
            obs_dates = []

            for maturity, series_id in _YIELD_SERIES.items():
                try:
                    series = fred.get_series(series_id, limit=5, sort_order="desc")
                    if series is None or series.empty:
                        continue

                    # Get the most recent non-NaN value
                    val = None
                    obs_date = None
                    for i in range(len(series) - 1, -1, -1):
                        v = float(series.iloc[i])
                        if not pd_is_nan(v):
                            val = v
                            obs_date = series.index[i].to_pydatetime()
                            break

                    if val is None:
                        continue

                    if obs_date.tzinfo is None:
                        obs_date = obs_date.replace(tzinfo=timezone.utc)

                    points.append(YieldCurvePoint(
                        maturity=maturity,
                        rate=val,
                        series_id=series_id,
                        observation_date=obs_date,
                        source=_SOURCE,
                    ))
                    obs_dates.append(obs_date)

                except Exception as e:
                    logger.debug("FRED yield curve %s failed: %s", series_id, e)
                    continue

            if not points:
                return None

            as_of = max(obs_dates) if obs_dates else datetime.now(timezone.utc)

            # Determine inversion: 2Y > 10Y
            curve = YieldCurve(points=points, as_of=as_of, source=_SOURCE)
            spread = curve.spread_10y_2y()
            if spread is not None:
                curve.is_inverted = spread < 0

            return curve

        except Exception as e:
            logger.error("FRED get_yield_curve failed: %s", e)
            return None


def pd_is_nan(value) -> bool:
    """Safe NaN check that works without importing math."""
    try:
        import math
        return math.isnan(value)
    except (TypeError, ValueError):
        return False

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class MacroIndicator:
    series_id: str         # FRED series ID, e.g. "FEDFUNDS"
    name: str              # human-readable name
    value: float
    unit: str              # "percent", "billions", etc.
    observation_date: datetime
    source: str = "fred"
    frequency: Optional[str] = None  # "daily", "monthly", "quarterly"
    next_release: Optional[datetime] = None


@dataclass
class YieldCurvePoint:
    maturity: str          # "1M", "3M", "6M", "1Y", "2Y", "5Y", "10Y", "30Y"
    rate: float            # percent
    series_id: str
    observation_date: datetime
    source: str = "fred"


@dataclass
class YieldCurve:
    points: list[YieldCurvePoint]
    as_of: datetime
    source: str = "fred"
    is_inverted: bool = False

    def get_rate(self, maturity: str) -> Optional[float]:
        for p in self.points:
            if p.maturity == maturity:
                return p.rate
        return None

    def spread_10y_2y(self) -> Optional[float]:
        r10 = self.get_rate("10Y")
        r2 = self.get_rate("2Y")
        if r10 is not None and r2 is not None:
            return r10 - r2
        return None

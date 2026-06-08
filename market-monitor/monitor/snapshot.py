"""Snapshot dataclasses — one moment's readings for all monitored instruments."""

from __future__ import annotations

from dataclasses import dataclass

from monitor.moving_averages import MAComparison


@dataclass
class Reading:
    symbol: str                 # raw symbol, e.g. "SPY", "^VIX"
    price: float                # ETF price or index level
    ma: MAComparison | None = None


@dataclass
class Snapshot:
    timestamp: str              # ISO-8601 local (Pacific) time
    date: str                   # YYYY-MM-DD (Pacific) — day-key for the baseline
    readings: list[Reading]

    def prices(self) -> dict[str, float]:
        """Symbol → price/level map (used as the baseline/reference values)."""
        return {r.symbol: r.price for r in self.readings}

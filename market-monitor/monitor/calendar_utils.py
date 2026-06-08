"""NYSE trading-day + regular-hours helpers (US/Eastern).

The holiday calendar is hard-coded per year (extend it each January, or swap in
a library). If a year is missing, all weekdays are treated as trading days.
"""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

# NYSE full-day closures (observed dates). Source: nyse.com/markets/hours-calendars
NYSE_HOLIDAYS: dict[int, set[str]] = {
    2025: {
        "2025-01-01", "2025-01-20", "2025-02-17", "2025-04-18", "2025-05-26",
        "2025-06-19", "2025-07-04", "2025-09-01", "2025-11-27", "2025-12-25",
    },
    2026: {
        "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25",
        "2026-06-19", "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25",
    },
    2027: {
        "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26", "2027-05-31",
        "2027-06-18", "2027-07-05", "2027-09-06", "2027-11-25", "2027-12-24",
    },
}

MARKET_OPEN = time(9, 30)
MARKET_CLOSE = time(16, 0)


def is_trading_day(d: datetime) -> bool:
    """True if ``d`` (any timezone) falls on a NYSE trading day."""
    if d.weekday() > 4:  # Saturday / Sunday
        return False
    holidays = NYSE_HOLIDAYS.get(d.year)
    if holidays is None:
        return True
    return d.strftime("%Y-%m-%d") not in holidays


def is_market_open(now: datetime | None = None) -> bool:
    """True if US equities are in the regular session right now (ET 9:30–16:00)."""
    now_et = (now or datetime.now(ET)).astimezone(ET)
    if not is_trading_day(now_et):
        return False
    return MARKET_OPEN <= now_et.time() <= MARKET_CLOSE

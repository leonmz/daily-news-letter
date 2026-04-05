"""Local tests for market_data and llm_analyzer — no live API calls."""

import unittest
from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from market_data import _is_trading_day, get_last_trading_day, NYSE_HOLIDAYS, ET
from llm_analyzer import build_analysis_prompt


class TestIsTradingDay(unittest.TestCase):
    # 1. Known 2025 holiday
    def test_is_trading_day_2025_holiday(self):
        d = datetime(2025, 1, 1, tzinfo=ET)  # New Year's Day 2025
        self.assertFalse(_is_trading_day(d))

    # 2. Known 2027 holiday
    def test_is_trading_day_2027_holiday(self):
        d = datetime(2027, 3, 26, tzinfo=ET)  # Good Friday 2027
        self.assertFalse(_is_trading_day(d))

    # 3. Unknown year — should not crash, weekday → True
    def test_is_trading_day_unknown_year(self):
        d = datetime(2028, 1, 3, tzinfo=ET)  # Monday, year not in NYSE_HOLIDAYS
        result = _is_trading_day(d)
        self.assertTrue(result)

    # 4. Weekend → False
    def test_is_trading_day_weekend(self):
        sat = datetime(2026, 1, 3, tzinfo=ET)  # Saturday
        self.assertFalse(_is_trading_day(sat))


class TestGetLastTradingDay(unittest.TestCase):
    # 5. Before market close (10:00am) on a Monday → returns prior Friday
    def test_get_last_trading_day_before_close_uses_prior_day(self):
        # Monday 2026-05-04 10:00am ET — before 4pm close
        monday_morning = datetime(2026, 5, 4, 10, 0, 0, tzinfo=ET)
        with patch("market_data.datetime") as mock_dt:
            mock_dt.now.return_value = monday_morning
            mock_dt.strptime = datetime.strptime
            result = get_last_trading_day()
        self.assertEqual(result, "2026-05-01")  # Friday before

    # 6. After market close (17:00) on a Monday → returns that Monday
    def test_get_last_trading_day_after_close(self):
        # Monday 2026-05-04 17:00 ET — after 4pm close
        monday_evening = datetime(2026, 5, 4, 17, 0, 0, tzinfo=ET)
        with patch("market_data.datetime") as mock_dt:
            mock_dt.now.return_value = monday_evening
            mock_dt.strptime = datetime.strptime
            result = get_last_trading_day()
        self.assertEqual(result, "2026-05-04")


class TestBuildAnalysisPromptSigns(unittest.TestCase):
    def _make_movers(self, key: str, change_pct: float) -> dict:
        return {
            key: [
                {
                    "ticker": "AAPL",
                    "name": "Apple",
                    "price": 200.0,
                    "change_pct": change_pct,
                    "volume": 1_000_000,
                    "sector_raw": "Technology",
                }
            ]
        }

    # 7. Positive blue chip → "+2.5%"
    def test_sign_positive_blue_chip(self):
        movers = self._make_movers("blue_chips", 2.5)
        prompt = build_analysis_prompt(movers, {})
        self.assertIn("+2.5%", prompt)

    # 8. Negative blue chip → "-1.3%" and NOT "+-1.3%"
    def test_sign_negative_blue_chip(self):
        movers = self._make_movers("blue_chips", -1.3)
        prompt = build_analysis_prompt(movers, {})
        self.assertIn("-1.3%", prompt)
        self.assertNotIn("+-1.3%", prompt)

    # 9. Positive watchlist → "+0.8%"
    def test_sign_positive_watchlist(self):
        movers = self._make_movers("watchlist", 0.8)
        prompt = build_analysis_prompt(movers, {})
        self.assertIn("+0.8%", prompt)


if __name__ == "__main__":
    unittest.main()

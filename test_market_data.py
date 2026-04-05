"""Local tests for market_data — no live API calls."""

import unittest
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from market_data import _is_trading_day, get_last_trading_day, NYSE_HOLIDAYS_2026, ET


class TestTradingDay(unittest.TestCase):
    def test_all_holidays_are_not_trading_days(self):
        for h in NYSE_HOLIDAYS_2026:
            d = datetime.strptime(h, "%Y-%m-%d").replace(tzinfo=ET)
            self.assertFalse(_is_trading_day(d), f"{h} should not be a trading day")

    def test_weekend(self):
        sat = datetime(2026, 4, 4, 12, 0, tzinfo=ET)  # Saturday
        sun = datetime(2026, 4, 5, 12, 0, tzinfo=ET)  # Sunday
        self.assertFalse(_is_trading_day(sat))
        self.assertFalse(_is_trading_day(sun))

    def test_regular_day(self):
        tue = datetime(2026, 4, 7, 12, 0, tzinfo=ET)  # Tuesday
        self.assertTrue(_is_trading_day(tue))


class TestGetLastTradingDay(unittest.TestCase):
    def test_all_holidays_skip_to_previous(self):
        for h in sorted(NYSE_HOLIDAYS_2026):
            d = datetime.strptime(h, "%Y-%m-%d").replace(hour=12, tzinfo=ET)
            with patch("market_data.datetime") as mock_dt:
                mock_dt.now.return_value = d
                mock_dt.strptime = datetime.strptime
                result = get_last_trading_day()
                result_dt = datetime.strptime(result, "%Y-%m-%d").replace(tzinfo=ET)
                self.assertTrue(_is_trading_day(result_dt), f"{h} -> {result} should be trading day")
                self.assertLess(result, h, f"{h} -> {result} should be before holiday")

    def test_weekend_skips_to_friday(self):
        sun = datetime(2026, 3, 15, 12, 0, tzinfo=ET)  # Sunday
        with patch("market_data.datetime") as mock_dt:
            mock_dt.now.return_value = sun
            mock_dt.strptime = datetime.strptime
            result = get_last_trading_day()
            self.assertEqual(result, "2026-03-13")  # Friday


if __name__ == "__main__":
    unittest.main()

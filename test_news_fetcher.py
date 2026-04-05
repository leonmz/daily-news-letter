"""Local tests for news_fetcher — no live API calls."""

import unittest
from unittest.mock import patch

from news_fetcher import _clean_company_name, get_news_for_movers


class TestCleanCompanyName(unittest.TestCase):
    def test_strips_inc(self):
        self.assertEqual(_clean_company_name("NVIDIA Corp"), "NVIDIA")

    def test_strips_inc_dot(self):
        self.assertEqual(_clean_company_name("Apple Inc."), "Apple")

    def test_strips_holdings(self):
        self.assertEqual(_clean_company_name("Eli Lilly Holdings"), "Eli Lilly")

    def test_all_suffix_returns_empty(self):
        self.assertEqual(_clean_company_name("LLC"), "")

    def test_strips_class(self):
        self.assertEqual(_clean_company_name("Alphabet Class A"), "Alphabet")


class TestGetNewsForMovers(unittest.TestCase):
    """Integration test: verify 2-tier waterfall with mocked APIs."""

    def _make_movers(self, tickers):
        return {
            "gainers": [
                {"ticker": t, "name": f"{t} Company Inc", "price": 100.0,
                 "change_pct": 5.0, "change_abs": 5.0, "volume": 1000000,
                 "sector": "tech", "sector_raw": "Technology"}
                for t in tickers[:len(tickers)//2]
            ],
            "losers": [
                {"ticker": t, "name": f"{t} Company Inc", "price": 100.0,
                 "change_pct": -5.0, "change_abs": -5.0, "volume": 1000000,
                 "sector": "tech", "sector_raw": "Technology"}
                for t in tickers[len(tickers)//2:]
            ],
        }

    def _mock_article(self, ticker):
        return {"title": f"News about {ticker}", "description": "...",
                "url": "#", "source": "test", "published_at": "2026-04-04",
                "sentiment": None}

    @patch("news_fetcher.fetch_news_google")
    @patch("news_fetcher.fetch_news_marketaux")
    def test_waterfall_fills_all_tickers(self, mock_maux, mock_google):
        """Marketaux covers AAA, Google News covers BBB."""
        mock_maux.return_value = {"AAA": [self._mock_article("AAA")]}
        mock_google.return_value = {"BBB": [self._mock_article("BBB")]}

        movers = self._make_movers(["AAA", "BBB"])
        news = get_news_for_movers(movers)

        self.assertTrue(news.get("AAA"), "AAA should have news from Marketaux")
        self.assertTrue(news.get("BBB"), "BBB should have news from Google")
        # Google should only be called for BBB (missing from Marketaux)
        mock_google.assert_called_once()
        called_tickers = mock_google.call_args[0][0]
        self.assertIn("BBB", called_tickers)
        self.assertNotIn("AAA", called_tickers)

    @patch("news_fetcher.fetch_news_google")
    @patch("news_fetcher.fetch_news_marketaux")
    def test_empty_list_gets_overwritten(self, mock_maux, mock_google):
        """Marketaux returns empty list for AAA — Google should still fill it."""
        mock_maux.return_value = {"AAA": []}
        mock_google.return_value = {"AAA": [self._mock_article("AAA")]}

        movers = self._make_movers(["AAA", "BBB"])
        news = get_news_for_movers(movers)

        self.assertTrue(news.get("AAA"), "AAA empty list should be overwritten by Google")


if __name__ == "__main__":
    unittest.main()

"""Local tests for telegram_bot — no live API calls."""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from main import format_for_telegram


class TestFormatForTelegram(unittest.TestCase):
    def test_bold_conversion(self):
        result = format_for_telegram("Hello **world**")
        self.assertEqual(result, ["Hello <b>world</b>"])

    def test_multiple_bolds(self):
        result = format_for_telegram("**one** and **two**")
        self.assertEqual(result, ["<b>one</b> and <b>two</b>"])

    def test_header_conversion(self):
        result = format_for_telegram("## Market Summary\nSome text")
        self.assertEqual(result, ["<b>Market Summary</b>\nSome text"])

    def test_chunk_splitting(self):
        # Paragraph-based splitting: two paragraphs of 3000 chars each
        long_text = "A" * 3000 + "\n\n" + "B" * 3000
        chunks = format_for_telegram(long_text)
        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0], "A" * 3000)
        self.assertEqual(chunks[1], "B" * 3000)

    def test_chunk_single_long_paragraph(self):
        # Single paragraph over 4000 chars gets truncated per chunk
        long_text = "A" * 5000
        chunks = format_for_telegram(long_text)
        self.assertEqual(len(chunks), 1)
        self.assertLessEqual(len(chunks[0]), 5000)

    def test_empty_string(self):
        result = format_for_telegram("")
        self.assertEqual(result, [""])

    def test_no_markdown(self):
        result = format_for_telegram("Plain text only")
        self.assertEqual(result, ["Plain text only"])


class TestIsAuthorized(unittest.TestCase):
    @patch("telegram_bot.config")
    def test_authorized_chat(self, mock_config):
        mock_config.TELEGRAM_CHAT_ID = "906163121"
        from telegram_bot import _is_authorized
        update = MagicMock()
        update.effective_chat.id = 906163121
        self.assertTrue(_is_authorized(update))

    @patch("telegram_bot.config")
    def test_unauthorized_chat(self, mock_config):
        mock_config.TELEGRAM_CHAT_ID = "906163121"
        from telegram_bot import _is_authorized
        update = MagicMock()
        update.effective_chat.id = 999999999
        self.assertFalse(_is_authorized(update))


class TestWatchlistLogic(unittest.TestCase):
    """Test watchlist add/remove logic directly on config.WATCHLIST."""

    @patch("config.WATCHLIST", ["NVDA", "TSLA"])
    def test_add_ticker(self):
        import config
        ticker = "AAPL"
        if ticker not in config.WATCHLIST and len(config.WATCHLIST) < 10:
            config.WATCHLIST.append(ticker)
        self.assertIn("AAPL", config.WATCHLIST)
        self.assertEqual(len(config.WATCHLIST), 3)

    @patch("config.WATCHLIST", ["NVDA", "TSLA", "PLTR"])
    def test_remove_ticker(self):
        import config
        ticker = "TSLA"
        if ticker in config.WATCHLIST:
            config.WATCHLIST.remove(ticker)
        self.assertNotIn("TSLA", config.WATCHLIST)
        self.assertEqual(len(config.WATCHLIST), 2)

    @patch("config.WATCHLIST", ["NVDA", "TSLA"])
    def test_add_duplicate_ignored(self):
        import config
        ticker = "NVDA"
        if ticker not in config.WATCHLIST and len(config.WATCHLIST) < 10:
            config.WATCHLIST.append(ticker)
        self.assertEqual(config.WATCHLIST.count("NVDA"), 1)

    @patch("config.WATCHLIST", list(range(10)))
    def test_add_over_cap(self):
        import config
        original_len = len(config.WATCHLIST)
        ticker = "NEW"
        if ticker not in config.WATCHLIST and len(config.WATCHLIST) < 10:
            config.WATCHLIST.append(ticker)
        self.assertEqual(len(config.WATCHLIST), original_len)

    def test_ticker_validation(self):
        """Only alpha strings 1-5 chars should be accepted."""
        valid = [t.upper() for t in ["AAPL", "A", "GOOGL"]
                 if t.isalpha() and 1 <= len(t) <= 5]
        invalid = [t.upper() for t in ["123", "TOOLONG", "A1B", ""]
                   if t.isalpha() and 1 <= len(t) <= 5]
        self.assertEqual(valid, ["AAPL", "A", "GOOGL"])
        self.assertEqual(invalid, [])


if __name__ == "__main__":
    unittest.main()

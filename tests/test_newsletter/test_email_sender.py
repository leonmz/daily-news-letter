"""Local tests for email_sender — no live SMTP / network calls."""

import unittest
from unittest.mock import MagicMock, patch

from newsletter.email_sender import (
    _subject_from_digest,
    markdown_to_html,
    send_email,
)


class TestMarkdownToHtml(unittest.TestCase):
    def test_bold(self):
        html = markdown_to_html("Hello **world**")
        self.assertIn("<strong>world</strong>", html)

    def test_headings(self):
        html = markdown_to_html("## Section\n\n### Sub")
        self.assertIn("<h2", html)
        self.assertIn("Section", html)
        self.assertIn("<h3", html)
        self.assertIn("Sub", html)

    def test_horizontal_rule(self):
        html = markdown_to_html("above\n\n---\n\nbelow")
        self.assertIn("<hr", html)

    def test_escaping(self):
        html = markdown_to_html("5 < 10 & cats > dogs <script>alert(1)</script>")
        self.assertIn("&lt;", html)
        self.assertIn("&amp;", html)
        self.assertNotIn("<script>", html)

    def test_linkify(self):
        html = markdown_to_html("See https://example.com/x for details.")
        self.assertIn('href="https://example.com/x"', html)

    def test_linkify_strips_trailing_period(self):
        html = markdown_to_html("Visit https://example.com.")
        self.assertIn('href="https://example.com"', html)

    def test_wraps_document(self):
        html = markdown_to_html("hi")
        self.assertTrue(html.startswith("<!DOCTYPE html>"))
        self.assertIn("max-width:600px", html)

    def test_heading_then_body_wraps_body_in_paragraph(self):
        # Digest shape: heading immediately followed by body (no blank line).
        html = markdown_to_html("### ▲ NVDA (+8.5%) — Product\nNVIDIA launched a chip.")
        self.assertIn("<h3", html)
        self.assertIn('<p style="margin:8px 0;">NVIDIA launched a chip.</p>', html)


class TestSubjectExtraction(unittest.TestCase):
    def test_extracts_first_header_strips_markdown(self):
        digest = "📊 **Daily Market Digest** — June 03, 2026\n\n## Summary\n..."
        self.assertEqual(
            _subject_from_digest(digest),
            "📊 Daily Market Digest — June 03, 2026",
        )

    def test_strips_heading_marker(self):
        self.assertEqual(_subject_from_digest("# Title\n\nbody"), "Title")

    def test_empty_returns_empty(self):
        self.assertEqual(_subject_from_digest("   \n\n  "), "")


class TestSendEmail(unittest.TestCase):
    def _config(self, **overrides):
        defaults = dict(
            EMAIL_ENABLED=True,
            SMTP_HOST="smtp.gmail.com",
            SMTP_PORT=587,
            SMTP_USERNAME="me@gmail.com",
            SMTP_PASSWORD="pw",
            EMAIL_FROM="",
            EMAIL_TO="a@x.com, b@y.com",
        )
        defaults.update(overrides)
        cfg = MagicMock()
        for key, value in defaults.items():
            setattr(cfg, key, value)
        return cfg

    def test_disabled_returns_false_and_skips_smtp(self):
        with patch("newsletter.email_sender.config", self._config(EMAIL_ENABLED=False)), \
             patch("newsletter.email_sender.smtplib.SMTP") as mock_smtp, \
             patch("newsletter.email_sender.smtplib.SMTP_SSL") as mock_ssl:
            self.assertFalse(send_email("digest"))
            mock_smtp.assert_not_called()
            mock_ssl.assert_not_called()

    def test_missing_config_returns_false_and_skips_smtp(self):
        cfg = self._config(SMTP_HOST="", SMTP_PASSWORD="", EMAIL_TO="")
        with patch("newsletter.email_sender.config", cfg), \
             patch("newsletter.email_sender.smtplib.SMTP") as mock_smtp, \
             patch("newsletter.email_sender.smtplib.SMTP_SSL") as mock_ssl:
            self.assertFalse(send_email("digest"))
            mock_smtp.assert_not_called()
            mock_ssl.assert_not_called()

    def test_starttls_path_587(self):
        server = MagicMock()
        with patch("newsletter.email_sender.config", self._config(SMTP_PORT=587)), \
             patch("newsletter.email_sender.smtplib.SMTP") as mock_smtp:
            mock_smtp.return_value.__enter__.return_value = server
            result = send_email("📊 **Digest**\n\nbody")

        self.assertTrue(result)
        server.starttls.assert_called_once()
        server.login.assert_called_once_with("me@gmail.com", "pw")
        server.send_message.assert_called_once()
        sent = server.send_message.call_args[0][0]
        self.assertEqual(sent["To"], "a@x.com, b@y.com")
        self.assertEqual(sent["From"], "me@gmail.com")

    def test_ssl_path_465_uses_email_from(self):
        server = MagicMock()
        cfg = self._config(SMTP_PORT=465, EMAIL_FROM="from@x.com", EMAIL_TO="a@x.com")
        with patch("newsletter.email_sender.config", cfg), \
             patch("newsletter.email_sender.smtplib.SMTP_SSL") as mock_ssl, \
             patch("newsletter.email_sender.smtplib.SMTP") as mock_smtp:
            mock_ssl.return_value.__enter__.return_value = server
            result = send_email("digest text")

        self.assertTrue(result)
        mock_smtp.assert_not_called()  # SSL path must not use plain SMTP
        server.starttls.assert_not_called()
        server.login.assert_called_once_with("me@gmail.com", "pw")
        server.send_message.assert_called_once()
        sent = server.send_message.call_args[0][0]
        self.assertEqual(sent["From"], "from@x.com")

    def test_multipart_has_plain_and_html(self):
        server = MagicMock()
        with patch("newsletter.email_sender.config", self._config()), \
             patch("newsletter.email_sender.smtplib.SMTP") as mock_smtp:
            mock_smtp.return_value.__enter__.return_value = server
            send_email("hello **world**")

        sent = server.send_message.call_args[0][0]
        leaf_types = [p.get_content_type() for p in sent.walk() if not p.is_multipart()]
        self.assertIn("text/plain", leaf_types)
        self.assertIn("text/html", leaf_types)
        # HTML must be last so clients prefer it (multipart/alternative ordering)
        self.assertEqual(leaf_types[-1], "text/html")

    def test_send_failure_returns_false(self):
        with patch("newsletter.email_sender.config", self._config()), \
             patch("newsletter.email_sender.smtplib.SMTP", side_effect=OSError("boom")) as mock_smtp:
            self.assertFalse(send_email("digest"))
            mock_smtp.assert_called_once()  # proves we reached SMTP, not an earlier guard


if __name__ == "__main__":
    unittest.main()

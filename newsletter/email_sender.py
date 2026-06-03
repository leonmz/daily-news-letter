"""Email delivery — SMTP push of the daily digest (HTML + plain-text).

Parallel to ``formatter.send_telegram()``: config-gated, returns ``False`` and
skips quietly when unconfigured so it never breaks the Telegram delivery path.
Pure stdlib (``smtplib`` + ``email``) — no third-party dependency.
"""

import html as _html
import re
import smtplib
import ssl
from email.message import EmailMessage

from newsletter import config

_URL_RE = re.compile(r"https?://[^\s<>\"]+")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_HEADING_RE = re.compile(r"^(#{1,3})\s+(.*)$")
_HR_RE = re.compile(r"-{3,}")

# Inline CSS per heading level (keeps the HTML self-contained for mail clients).
_HEADING_STYLE = {
    1: "margin:20px 0 8px;font-size:22px;",
    2: "margin:18px 0 6px;font-size:19px;",
    3: "margin:14px 0 4px;font-size:16px;",
}


def _linkify(escaped: str) -> str:
    """Wrap bare URLs in <a> tags. Operates on already-HTML-escaped text."""

    def repl(match: re.Match) -> str:
        url = match.group(0)
        trail = ""
        # Don't swallow sentence punctuation that trails a URL.
        while url and url[-1] in ".,!?)":
            trail = url[-1] + trail
            url = url[:-1]
        return f'<a href="{url}" style="color:#1a73e8;">{url}</a>{trail}'

    return _URL_RE.sub(repl, escaped)


def _inline(text: str) -> str:
    """HTML-escape, then apply inline markdown (**bold**) and linkify URLs."""
    escaped = _html.escape(text)
    escaped = _BOLD_RE.sub(r"<strong>\1</strong>", escaped)
    return _linkify(escaped)


def markdown_to_html(text: str) -> str:
    """Convert the digest markdown into a self-contained, styled HTML document.

    Handles the small markdown subset the digest uses: #/##/### headings,
    **bold**, --- horizontal rules, blank-line paragraphs, and bare URLs.
    Text is HTML-escaped before formatting so catalyst text containing
    & < > stays safe.

    Rendered line-by-line (not block-by-block) so a heading directly followed
    by a body line — the digest's `### TICKER …\nbody…` shape — still wraps the
    body in its own <p>.
    """
    parts: list[str] = []
    paragraph: list[str] = []

    def flush_paragraph() -> None:
        if paragraph:
            parts.append(f'<p style="margin:8px 0;">{"<br>".join(paragraph)}</p>')
            paragraph.clear()

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            flush_paragraph()
            continue
        if _HR_RE.fullmatch(line):
            flush_paragraph()
            parts.append('<hr style="border:none;border-top:1px solid #e0e0e0;margin:16px 0;">')
            continue
        heading = _HEADING_RE.match(line)
        if heading:
            flush_paragraph()
            level = len(heading.group(1))
            parts.append(f'<h{level} style="{_HEADING_STYLE[level]}">{_inline(heading.group(2))}</h{level}>')
            continue
        paragraph.append(_inline(line))
    flush_paragraph()

    body = "\n".join(parts)
    return (
        '<!DOCTYPE html><html><body style="margin:0;padding:0;background:#f5f5f5;">'
        '<div style="max-width:600px;margin:0 auto;padding:24px;'
        "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;"
        'font-size:15px;line-height:1.5;color:#1a1a1a;background:#ffffff;">'
        f"{body}"
        "</div></body></html>"
    )


def _recipients() -> list[str]:
    return [addr.strip() for addr in config.EMAIL_TO.split(",") if addr.strip()]


def _subject_from_digest(text: str) -> str:
    """Derive a subject line from the digest's first non-empty line."""
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        line = re.sub(r"^#+\s*", "", line)  # strip heading markers
        line = _BOLD_RE.sub(r"\1", line)    # strip bold markers
        return line
    return ""


def send_email(text: str, subject: str | None = None) -> bool:
    """Send the digest via SMTP as a multipart (plain-text + HTML) email.

    Config-gated: returns ``False`` (and prints why) when ``EMAIL_ENABLED`` is
    false or required SMTP settings are missing. Never raises — mirrors
    ``send_telegram()``.
    """
    if not config.EMAIL_ENABLED:
        print("[email] Disabled (EMAIL_ENABLED=false), skipping...")
        return False

    recipients = _recipients()
    missing = [
        name
        for name, value in (
            ("SMTP_HOST", config.SMTP_HOST),
            ("SMTP_USERNAME", config.SMTP_USERNAME),
            ("SMTP_PASSWORD", config.SMTP_PASSWORD),
        )
        if not value
    ]
    if not recipients:
        missing.append("EMAIL_TO")
    if missing:
        print(f"[email] Not configured (missing: {', '.join(missing)}), skipping...")
        return False

    try:
        msg = EmailMessage()
        msg["Subject"] = subject or _subject_from_digest(text) or "Daily Market Digest"
        msg["From"] = config.EMAIL_FROM or config.SMTP_USERNAME
        msg["To"] = ", ".join(recipients)
        msg.set_content(text)  # text/plain part
        msg.add_alternative(markdown_to_html(text), subtype="html")  # text/html part

        if config.SMTP_PORT == 465:
            ctx = ssl.create_default_context()
            with smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT, timeout=30, context=ctx) as server:
                server.login(config.SMTP_USERNAME, config.SMTP_PASSWORD)
                server.send_message(msg)
        else:
            with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=30) as server:
                server.starttls(context=ssl.create_default_context())
                server.login(config.SMTP_USERNAME, config.SMTP_PASSWORD)
                server.send_message(msg)
        print(f"[email] ✅ Digest sent to {len(recipients)} recipient(s)!")
        return True
    except Exception as e:
        print(f"[email] ❌ Send failed: {e}")
        return False

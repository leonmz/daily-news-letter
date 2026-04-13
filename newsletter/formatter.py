"""Formatting utilities for Telegram output.

Extracted from main.py so both the bot and the CLI runner can import without
circular dependencies (main → bot → main was the old cycle).
"""

import re
import requests


def format_for_telegram(text: str) -> list[str]:
    """Convert markdown to Telegram HTML and split into chunks under 4000 chars."""
    html = text
    html = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", html)
    html = re.sub(r"^##\s*(.+)$", r"<b>\1</b>", html, flags=re.MULTILINE)

    if len(html) <= 4000:
        return [html] if html else [""]

    chunks = []
    current = ""
    for paragraph in html.split("\n\n"):
        candidate = (current + "\n\n" + paragraph) if current else paragraph
        if len(candidate) > 4000:
            if current:
                chunks.append(current)
            current = paragraph[:4000] if len(paragraph) > 4000 else paragraph
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks if chunks else [""]


def format_compact_summary(digest: str) -> str:
    """Parse full LLM digest into compact one-line-per-ticker format.

    Handles both the old format:
        ### ▲ TICKER (+X.XX%) $XXX.XX | Vol: XXM — Catalyst type
    and the new format with company name:
        ### ▲ TICKER (Company Name) (+X.XX%) $XXX.XX | Vol: XXM — Catalyst type

    Returns lines like:
        ▲ NVDA (NVIDIA) +8.5% | GPU demand surge on data center contracts
        ▼ XOM (Exxon) -3.2% | Falling oil prices on OPEC output increase

    Returns empty string if no matching lines are found.
    """
    pattern = re.compile(
        r"^#{2,3}\s*(▲|▼)\s+([A-Z][A-Z0-9.\-]{0,8})"
        r"(?:\s+\(([^)]+)\))?"
        r"\s+\(([+-]?\d+\.?\d*)%\)"
        r"[^\n]*?—\s*(.+?)$",
        re.MULTILINE,
    )
    lines = []
    for m in pattern.finditer(digest):
        arrow, ticker, company, pct, catalyst = m.groups()
        sign = "+" if not pct.startswith("-") and not pct.startswith("+") else ""
        company_part = f" ({company})" if company else ""
        lines.append(f"{arrow} {ticker}{company_part} {sign}{pct}% | {catalyst.strip()}")
    return "\n".join(lines)


def send_telegram(text: str) -> bool:
    """Send digest via Telegram Bot API (simple HTTP, no bot library needed)."""
    from newsletter.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN.startswith("your_"):
        print("[telegram] Not configured, skipping...")
        return False

    try:
        chunks = format_for_telegram(text)
        for chunk in chunks:
            resp = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={
                    "chat_id": TELEGRAM_CHAT_ID,
                    "text": chunk,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
                timeout=15,
            )
            resp.raise_for_status()
        print("[telegram] ✅ Digest sent!")
        return True
    except Exception as e:
        print(f"[telegram] ❌ Send failed: {e}")
        return False

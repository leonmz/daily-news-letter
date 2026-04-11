"""
Use Gemini API to analyze top movers + their news,
produce a structured daily digest grouped by sector.
"""

import json

from google import genai

from config import GEMINI_API_KEY, ANTHROPIC_API_KEY, SECTOR_DISPLAY


SYSTEM_PROMPT = """You are a concise financial market analyst. Your job is to produce
a daily market digest for a retail investor. You will receive:
1. Top market movers (gainers and losers) with price data and sector info
2. Related news articles for each ticker

Your task:
- Group the movers by sector
- For each mover, identify the PRIMARY catalyst / driver (earnings, macro, sector rotation,
  regulatory, product launch, analyst upgrade/downgrade, M&A, etc.)
- Write 1-2 sentence summary of WHY each stock moved
- If no clear news driver exists, say "No clear catalyst; likely sector/market-wide move"
- Add a 2-3 sentence overall market summary at the top

Output format (use exactly this structure):

## Market summary
[2-3 sentences on overall market tone today]

## [Sector emoji + name]
### ▲ TICKER (Company Name) (+X.XX%) $XXX.XX | Vol: XXM — Catalyst type
[1-2 sentence explanation]

### ▼ TICKER (Company Name) (-X.XX%) $XXX.XX | Vol: XXM — Catalyst type
[1-2 sentence explanation]

Always include the company name, current price and volume (in millions, e.g. "Vol: 85M") in each mover line.
Keep it crisp. No fluff. No disclaimers. The reader is sophisticated."""


def build_analysis_prompt(movers: dict, news: dict) -> str:
    """Build the user prompt with movers + news data."""
    sections = []

    sections.append("# TODAY'S TOP MOVERS\n")

    for direction, label in [
        ("gainers", "TOP GAINERS"),
        ("losers", "TOP LOSERS"),
        ("blue_chips", "BLUE CHIP MOVERS"),
        ("watchlist", "YOUR HOLDINGS"),
    ]:
        sections.append(f"\n## {label}")
        for m in movers.get(direction, []):
            ticker = m["ticker"]
            sign = "+" if m["change_pct"] >= 0 else ""
            sections.append(
                f"\n**{ticker}** ({m.get('name', ticker)})"
                f"\n  Price: ${m['price']:.2f} | Change: {sign}{m['change_pct']}%"
                f" | Volume: {m.get('volume', 'N/A'):,}"
                f"\n  Sector: {m.get('sector_raw', 'Unknown')}"
            )

            # Attach news
            ticker_news = news.get(ticker, [])
            if ticker_news:
                sections.append(f"  Related news ({len(ticker_news)} articles):")
                for i, article in enumerate(ticker_news, 1):
                    sections.append(
                        f"    {i}. [{article['source']}] {article['title']}"
                    )
                    if article.get("description"):
                        desc = article["description"][:300]
                        sections.append(f"       {desc}")
                    if article.get("sentiment") is not None:
                        sections.append(
                            f"       Sentiment score: {article['sentiment']}"
                        )
            else:
                sections.append("  Related news: None found")

    return "\n".join(sections)


def analyze_movers(movers: dict, news: dict) -> str:
    """Send movers + news to Gemini and get back a formatted digest.
    Falls back to Anthropic Claude if Gemini is not configured."""
    user_prompt = build_analysis_prompt(movers, news)

    # Try Gemini first
    if GEMINI_API_KEY and not GEMINI_API_KEY.startswith("your_"):
        try:
            client = genai.Client(api_key=GEMINI_API_KEY)
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=f"{SYSTEM_PROMPT}\n\n{user_prompt}",
            )
            return response.text
        except Exception as e:
            print(f"[llm] Gemini API error: {e}")

    # Fallback to Anthropic Claude
    if ANTHROPIC_API_KEY and not ANTHROPIC_API_KEY.startswith("your_"):
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            message = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=2000,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )
            return message.content[0].text
        except Exception as e:
            print(f"[llm] Claude API error: {e}")

    return _fallback_summary(movers, news)


def _format_volume(vol) -> str:
    """Format volume as human-readable string (e.g. 85M, 1.2B, 500K)."""
    if not vol:
        return "N/A"
    vol = int(vol)
    if vol >= 1_000_000_000:
        return f"{vol / 1_000_000_000:.1f}B"
    if vol >= 1_000_000:
        return f"{vol / 1_000_000:.0f}M"
    if vol >= 1_000:
        return f"{vol / 1_000:.0f}K"
    return str(vol)


def _fallback_summary(movers: dict, news: dict) -> str:
    """Simple template-based summary when LLM is unavailable."""
    lines = ["## Market movers (no LLM analysis)\n"]

    def _mover_line(m: dict) -> str:
        arrow = "▲" if m["change_pct"] >= 0 else "▼"
        sign = "+" if m["change_pct"] >= 0 else ""
        vol = _format_volume(m.get("volume"))
        name = m.get("name", m["ticker"])
        return (
            f"{arrow} **{m['ticker']}** ({name}) ({sign}{m['change_pct']}%)"
            f" ${m['price']:.2f} | Vol: {vol}"
        )

    # Blue chips section
    if movers.get("blue_chips"):
        lines.append("\n### 📈 Blue Chip Movers")
        for m in movers["blue_chips"]:
            lines.append(_mover_line(m))
            ticker_news = news.get(m["ticker"], [])
            if ticker_news:
                lines.append(f"  → {ticker_news[0]['title'][:100]}")

    # Watchlist section
    if movers.get("watchlist"):
        lines.append("\n### 👀 Your Holdings")
        for m in movers["watchlist"]:
            lines.append(_mover_line(m))
            ticker_news = news.get(m["ticker"], [])
            if ticker_news:
                lines.append(f"  → {ticker_news[0]['title'][:100]}")

    # Group top movers by sector
    by_sector: dict[str, list] = {}
    for direction in ["gainers", "losers"]:
        for m in movers.get(direction, []):
            sector = m.get("sector", "other")
            by_sector.setdefault(sector, []).append(
                {**m, "direction": direction}
            )

    for sector, items in sorted(by_sector.items()):
        display = SECTOR_DISPLAY.get(sector, sector.title())
        lines.append(f"\n### {display}")
        for m in items:
            lines.append(_mover_line(m))
            ticker_news = news.get(m["ticker"], [])
            if ticker_news:
                lines.append(f"  → {ticker_news[0]['title'][:100]}")

    return "\n".join(lines)


# ---- Quick test ----
if __name__ == "__main__":
    # Test with mock data
    mock_movers = {
        "gainers": [
            {
                "ticker": "NVDA",
                "name": "NVIDIA Corp",
                "price": 950.50,
                "change_pct": 8.5,
                "change_abs": 74.5,
                "volume": 85000000,
                "sector": "tech",
                "sector_raw": "Technology",
            }
        ],
        "losers": [
            {
                "ticker": "XOM",
                "name": "Exxon Mobil",
                "price": 105.20,
                "change_pct": -3.2,
                "change_abs": -3.48,
                "volume": 22000000,
                "sector": "energy",
                "sector_raw": "Energy",
            }
        ],
    }
    mock_news = {
        "NVDA": [
            {
                "title": "NVIDIA announces next-gen Blackwell Ultra GPU",
                "description": "NVIDIA revealed its next GPU architecture...",
                "source": "reuters",
                "url": "https://example.com",
                "published_at": "2026-04-04",
                "sentiment": 0.85,
            }
        ],
        "XOM": [],
    }

    result = analyze_movers(mock_movers, mock_news)
    print(result)

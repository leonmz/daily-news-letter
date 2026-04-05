"""
Fetch news for given tickers / sectors.

Tier 1: Marketaux API (optional, free tier: 100 req/day, provides sentiment)
Tier 2: Google News RSS (primary workhorse, free, per-ticker search)
"""

import re
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Optional

import feedparser
import requests

from config import MARKETAUX_API_KEY, MARKETAUX_BASE


# ── Marketaux API (optional, provides sentiment) ──────────────

def fetch_news_marketaux(
    tickers: list[str],
    limit_per_ticker: int = 3,
    hours_back: int = 24,
) -> dict[str, list[dict]]:
    """
    Fetch news from Marketaux for a list of tickers.
    Returns {ticker: [article, ...]}
    """
    if not MARKETAUX_API_KEY or MARKETAUX_API_KEY.startswith("your_"):
        return {}

    result = {}
    published_after = (
        datetime.now(timezone.utc) - timedelta(hours=hours_back)
    ).strftime("%Y-%m-%dT%H:%M")

    # Marketaux supports comma-separated tickers (max 5 per call)
    for i in range(0, len(tickers), 5):
        batch = tickers[i : i + 5]
        symbols = ",".join(batch)

        try:
            resp = requests.get(
                f"{MARKETAUX_BASE}/news/all",
                params={
                    "api_token": MARKETAUX_API_KEY,
                    "symbols": symbols,
                    "filter_entities": "true",
                    "published_after": published_after,
                    "language": "en",
                    "limit": limit_per_ticker * len(batch),
                },
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()

            for article in data.get("data", []):
                article_tickers = {
                    e["symbol"]
                    for e in article.get("entities", [])
                    if e.get("symbol") in batch
                }
                if not article_tickers:
                    article_tickers = set(batch)

                parsed = {
                    "title": article.get("title", ""),
                    "description": article.get("description", ""),
                    "url": article.get("url", ""),
                    "source": article.get("source", ""),
                    "published_at": article.get("published_at", ""),
                    "sentiment": _extract_sentiment(article, batch),
                }

                for t in article_tickers:
                    result.setdefault(t, [])
                    if len(result[t]) < limit_per_ticker:
                        result[t].append(parsed)

            time.sleep(0.5)

        except Exception as e:
            print(f"[marketaux] Error fetching news for {symbols}: {e}")

    return result


def _extract_sentiment(article: dict, tickers: list[str]) -> Optional[float]:
    """Extract average sentiment score for relevant tickers from Marketaux entities."""
    scores = []
    for entity in article.get("entities", []):
        if entity.get("symbol") in tickers:
            score = entity.get("sentiment_score")
            if score is not None:
                scores.append(score)
    return round(sum(scores) / len(scores), 3) if scores else None


# ── Company name helpers ──────────────────────────────────────

_NAME_SUFFIXES = re.compile(
    r"\b(Inc\.?|Corp\.?|Ltd\.?|Co\.?|Holdings?|Group|Plc|LLC|LP|N\.?V\.?"
    r"|Class [A-Z]|Cl [A-Z]|Common Stock|Ordinary Shares)\b",
    re.IGNORECASE,
)


def _clean_company_name(name: str) -> str:
    """Strip corporate suffixes to get a matchable company name."""
    cleaned = _NAME_SUFFIXES.sub("", name).strip()
    cleaned = re.sub(r"[,.\s]+$", "", cleaned).strip()
    return cleaned


# ── Google News RSS (primary news source) ─────────────────────

_GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"
_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


def fetch_news_google(
    tickers: list[str],
    ticker_names: dict[str, str] | None = None,
    limit_per_ticker: int = 3,
) -> dict[str, list[dict]]:
    """
    Fetch news via Google News RSS search per ticker.
    Free, no API key, targeted per-ticker.
    """
    if ticker_names is None:
        ticker_names = {}

    result = {}
    for ticker in tickers:
        name = ticker_names.get(ticker)
        cleaned = _clean_company_name(name) if name else ""
        t = ticker.upper()
        if cleaned and (len(cleaned) >= 6 or len(cleaned.split()) >= 2):
            query = f'"{cleaned}" OR "{t}" stock'
        else:
            query = f'"{t}" stock'

        url = f"{_GOOGLE_NEWS_RSS}?q={urllib.parse.quote(query)}&hl=en-US&gl=US&ceid=US:en&when=1d"

        try:
            resp = requests.get(url, headers={"User-Agent": _USER_AGENT}, timeout=10)
            resp.raise_for_status()
            parsed = feedparser.parse(resp.content)
            articles = []
            for entry in parsed.entries[:limit_per_ticker]:
                title = entry.get("title", "")
                source = "google_news"
                if " - " in title:
                    parts = title.rsplit(" - ", 1)
                    title = parts[0]
                    source = parts[1].strip().lower()

                articles.append({
                    "title": title,
                    "description": entry.get("summary", ""),
                    "url": entry.get("link", ""),
                    "source": source,
                    "published_at": entry.get("published", ""),
                    "sentiment": None,
                })

            if articles:
                result[ticker] = articles
                print(f"[google-news] {ticker}: {len(articles)} articles")

        except Exception as e:
            print(f"[google-news] Error for {ticker}: {e}")

        time.sleep(0.3)

    return result


# ── Unified interface ──────────────────────────────────────────

def get_news_for_movers(movers: dict, limit_per_ticker: int = 3) -> dict[str, list[dict]]:
    """
    Get news for all movers. 2-tier waterfall:
    1. Marketaux (optional, if API key set — provides sentiment scores)
    2. Google News RSS (primary, per-ticker search, free)
    """
    all_tickers = []
    ticker_names = {}
    for key in ["gainers", "losers", "blue_chips", "watchlist"]:
        for m in movers.get(key, []):
            all_tickers.append(m["ticker"])
            if m.get("name"):
                ticker_names[m["ticker"]] = m["name"]

    # Tier 1: Marketaux (optional)
    news = fetch_news_marketaux(all_tickers, limit_per_ticker)

    # Tier 2: Google News RSS (primary)
    missing = [t for t in all_tickers if not news.get(t)]
    if missing:
        print(f"[news] Searching Google News for {len(missing)} tickers...")
        google_news = fetch_news_google(missing, ticker_names, limit_per_ticker)
        for t, articles in google_news.items():
            if not news.get(t):
                news[t] = articles

    return news


# ---- Quick test ----
if __name__ == "__main__":
    import json

    test_movers = {
        "gainers": [
            {"ticker": "NVDA", "name": "NVIDIA Corp"},
            {"ticker": "AAPL", "name": "Apple Inc"},
            {"ticker": "TSLA", "name": "Tesla Inc"},
        ],
        "losers": [
            {"ticker": "META", "name": "Meta Platforms"},
            {"ticker": "AMZN", "name": "Amazon.com Inc"},
        ],
    }

    news = get_news_for_movers(test_movers)
    for ticker, articles in news.items():
        print(f"\n{'='*50}")
        print(f"  {ticker}: {len(articles)} articles")
        for a in articles:
            print(f"    - {a['title'][:80]}")
            if a["sentiment"] is not None:
                print(f"      sentiment: {a['sentiment']}")
    print(f"\nTotal tickers with news: {len(news)}")

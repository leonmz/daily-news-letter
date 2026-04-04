"""
Fetch news for given tickers / sectors.

Primary: Marketaux API (free tier: 100 req/day, sentiment included)
Fallback: RSS feeds from major financial news sites
"""

import time
from datetime import datetime, timedelta
from typing import Optional

import feedparser
import requests

from config import MARKETAUX_API_KEY, MARKETAUX_BASE


# ── Marketaux API ──────────────────────────────────────────────

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
        datetime.utcnow() - timedelta(hours=hours_back)
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
                # Map article to relevant tickers
                article_tickers = {
                    e["symbol"]
                    for e in article.get("entities", [])
                    if e.get("symbol") in batch
                }
                if not article_tickers:
                    # If entity mapping failed, assign to all batch tickers
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

            # Rate limiting: be nice to free tier
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


# ── RSS Feeds (fallback / custom sources) ──────────────────────

# Popular financial RSS feeds
RSS_FEEDS = {
    "reuters_markets": "https://www.rss.app/feeds/v1.1/tDBgmBJKNaJd3VvV.json",
    "cnbc_top": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114",
    "yahoo_finance": "https://finance.yahoo.com/news/rssindex",
    "marketwatch": "https://feeds.marketwatch.com/marketwatch/topstories/",
    "seeking_alpha": "https://seekingalpha.com/market_currents.xml",
}


def fetch_news_rss(
    tickers: list[str],
    feeds: Optional[dict[str, str]] = None,
    limit_per_ticker: int = 3,
) -> dict[str, list[dict]]:
    """
    Fetch news from RSS feeds, filter by ticker mentions.
    Less precise than Marketaux but free and unlimited.
    """
    if feeds is None:
        feeds = RSS_FEEDS

    all_articles = []
    for feed_name, feed_url in feeds.items():
        try:
            parsed = feedparser.parse(feed_url)
            for entry in parsed.entries[:30]:  # cap per feed
                all_articles.append(
                    {
                        "title": entry.get("title", ""),
                        "description": entry.get("summary", ""),
                        "url": entry.get("link", ""),
                        "source": feed_name,
                        "published_at": entry.get("published", ""),
                        "sentiment": None,
                    }
                )
        except Exception as e:
            print(f"[rss] Error fetching {feed_name}: {e}")

    # Simple ticker matching in title/description
    result = {}
    for ticker in tickers:
        ticker_upper = ticker.upper()
        matches = []
        for article in all_articles:
            text = f"{article['title']} {article['description']}".upper()
            # Match $TICKER, (TICKER), or standalone TICKER
            if (
                f"${ticker_upper}" in text
                or f"({ticker_upper})" in text
                or f" {ticker_upper} " in text
            ):
                matches.append(article)
                if len(matches) >= limit_per_ticker:
                    break
        if matches:
            result[ticker] = matches

    return result


# ── Unified interface ──────────────────────────────────────────

def get_news_for_movers(movers: dict, limit_per_ticker: int = 3) -> dict[str, list[dict]]:
    """
    Get news for all movers. Try Marketaux first, fill gaps with RSS.
    Returns {ticker: [article, ...]}
    """
    all_tickers = []
    for direction in ["gainers", "losers"]:
        for m in movers.get(direction, []):
            all_tickers.append(m["ticker"])

    # Primary: Marketaux
    news = fetch_news_marketaux(all_tickers, limit_per_ticker)

    # Fill gaps with RSS
    missing = [t for t in all_tickers if t not in news or not news[t]]
    if missing:
        print(f"[news] Filling {len(missing)} tickers via RSS...")
        rss_news = fetch_news_rss(missing, limit_per_ticker=limit_per_ticker)
        for t, articles in rss_news.items():
            if t not in news:
                news[t] = articles

    return news


# ---- Quick test ----
if __name__ == "__main__":
    import json

    # Test with some known tickers
    test_movers = {
        "gainers": [
            {"ticker": "NVDA"},
            {"ticker": "AAPL"},
            {"ticker": "TSLA"},
        ],
        "losers": [
            {"ticker": "META"},
            {"ticker": "AMZN"},
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

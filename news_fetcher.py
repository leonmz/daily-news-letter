"""
Fetch news for given tickers / sectors.

Primary: Marketaux API (free tier: 100 req/day, sentiment included)
Fallback: RSS feeds from major financial news sites
Last resort: Google News RSS (per-ticker search, free, no API key)
"""

import re
import time
import urllib.parse
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


# ── Company name matching helpers ─────────────────────────────

_NAME_SUFFIXES = re.compile(
    r"\b(Inc\.?|Corp\.?|Ltd\.?|Co\.?|Holdings?|Group|Plc|LLC|LP|N\.?V\.?"
    r"|Class [A-Z]|Cl [A-Z]|Common Stock|Ordinary Shares)\b",
    re.IGNORECASE,
)


def _clean_company_name(name: str) -> str:
    """Strip corporate suffixes to get a matchable company name."""
    cleaned = _NAME_SUFFIXES.sub("", name).strip()
    # Remove trailing punctuation/whitespace
    cleaned = re.sub(r"[,.\s]+$", "", cleaned).strip()
    return cleaned


def _build_search_terms(ticker: str, company_name: str | None) -> list[str]:
    """Build uppercase search patterns for a ticker."""
    t = ticker.upper()
    terms = [f"${t}", f"({t})", f" {t} "]
    if company_name:
        cleaned = _clean_company_name(company_name)
        # Only use name matching if name is meaningful (>= 6 chars or >= 2 words)
        if len(cleaned) >= 6 or len(cleaned.split()) >= 2:
            terms.append(cleaned.upper())
    return terms


# ── RSS Feeds (fallback / custom sources) ──────────────────────

# Popular financial RSS feeds
RSS_FEEDS = {
    "reuters_biz": "https://www.reutersagency.com/feed/?taxonomy=best-sectors&post_type=best",
    "cnbc_top": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114",
    "yahoo_finance": "https://finance.yahoo.com/news/rssindex",
    "marketwatch": "https://feeds.marketwatch.com/marketwatch/topstories/",
    "seeking_alpha": "https://seekingalpha.com/market_currents.xml",
    "benzinga": "https://www.benzinga.com/feed",
    "investorplace": "https://investorplace.com/feed/",
    "thestreet": "https://www.thestreet.com/feed",
    "pr_newswire_biz": "https://www.prnewswire.com/rss/financial-services-latest-news/financial-services-latest-news-list.rss",
}


def fetch_news_rss(
    tickers: list[str],
    ticker_names: dict[str, str] | None = None,
    feeds: Optional[dict[str, str]] = None,
    limit_per_ticker: int = 3,
) -> dict[str, list[dict]]:
    """
    Fetch news from RSS feeds, filter by ticker and company name mentions.
    """
    if feeds is None:
        feeds = RSS_FEEDS
    if ticker_names is None:
        ticker_names = {}

    all_articles = []
    for feed_name, feed_url in feeds.items():
        try:
            resp = requests.get(feed_url, timeout=10)
            resp.raise_for_status()
            parsed = feedparser.parse(resp.content)
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

    # Match articles to tickers using ticker symbols + company names
    result = {}
    for ticker in tickers:
        search_terms = _build_search_terms(ticker, ticker_names.get(ticker))
        matches = []
        for article in all_articles:
            text = f" {article['title']} {article['description']} ".upper()
            for pattern in search_terms:
                if pattern in text:
                    matches.append(article)
                    break
            if len(matches) >= limit_per_ticker:
                break
        if matches:
            result[ticker] = matches

    return result


# ── Google News RSS (per-ticker search) ───────────────────────

_GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"
_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


def fetch_news_google_rss(
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
        if cleaned and (len(cleaned) >= 6 or len(cleaned.split()) >= 2):
            query = f'"{cleaned}" OR "{ticker}" stock'
        else:
            query = f'"{ticker}" stock'

        url = f"{_GOOGLE_NEWS_RSS}?q={urllib.parse.quote(query)}&hl=en-US&gl=US&ceid=US:en&when=1d"

        try:
            resp = requests.get(url, headers={"User-Agent": _USER_AGENT}, timeout=10)
            resp.raise_for_status()
            parsed = feedparser.parse(resp.content)
            articles = []
            for entry in parsed.entries[:limit_per_ticker]:
                title = entry.get("title", "")
                # Google News titles are "Article Title - Source Name"
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
    Get news for all movers. 3-tier waterfall:
    1. Marketaux (best quality, limited quota)
    2. RSS feeds (broad, free, now with company name matching)
    3. Google News RSS (targeted per-ticker, free)
    """
    # Build ticker list and name mapping
    all_tickers = []
    ticker_names = {}
    for direction in ["gainers", "losers"]:
        for m in movers.get(direction, []):
            all_tickers.append(m["ticker"])
            if m.get("name"):
                ticker_names[m["ticker"]] = m["name"]

    # Tier 1: Marketaux
    news = fetch_news_marketaux(all_tickers, limit_per_ticker)

    # Tier 2: RSS feeds (with company name matching)
    missing = [t for t in all_tickers if not news.get(t)]
    if missing:
        print(f"[news] Filling {len(missing)} tickers via RSS...")
        rss_news = fetch_news_rss(missing, ticker_names, limit_per_ticker=limit_per_ticker)
        for t, articles in rss_news.items():
            if not news.get(t):
                news[t] = articles

    # Tier 3: Google News RSS (per-ticker search)
    still_missing = [t for t in all_tickers if not news.get(t)]
    if still_missing:
        print(f"[news] Searching Google News for {len(still_missing)} tickers...")
        google_news = fetch_news_google_rss(still_missing, ticker_names, limit_per_ticker)
        for t, articles in google_news.items():
            if not news.get(t):
                news[t] = articles

    return news


# ---- Quick test ----
if __name__ == "__main__":
    import json

    # Test with some known tickers
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

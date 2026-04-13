from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class NewsArticle:
    title: str
    summary: str
    url: str
    published_at: datetime
    source: str              # which provider (alpaca, finnhub, etc.)
    ticker: Optional[str] = None   # None for broad market news
    sentiment: Optional[str] = None   # "positive", "negative", "neutral"
    sentiment_score: Optional[float] = None  # -1.0 to 1.0
    author: Optional[str] = None
    image_url: Optional[str] = None

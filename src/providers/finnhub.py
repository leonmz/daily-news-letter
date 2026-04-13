"""Finnhub provider — free tier (fundamentals, earnings, analyst ratings, news)."""

import logging
from datetime import datetime, timezone
from typing import Optional

from src.models.news import NewsArticle
from src.providers.base import AuthError, ProviderError

logger = logging.getLogger(__name__)

_SOURCE = "finnhub"


class FinnhubProvider:
    """
    Wraps the finnhub-python SDK.

    Free tier capabilities:
    - Company profile, market cap, sector, peers
    - Upcoming earnings calendar
    - Analyst recommendations and price targets
    - Company news with sentiment
    Rate limit: 60 calls/min
    """

    def __init__(self, api_key: str):
        if not api_key:
            raise AuthError("FINNHUB_API_KEY is required")
        self._api_key = api_key
        self._client = None

    def _get_client(self):
        if self._client is None:
            import finnhub
            self._client = finnhub.Client(api_key=self._api_key)
        return self._client

    async def get_fundamentals(self, ticker: str) -> Optional[dict]:
        """
        Return company profile data: market_cap (B), sector, name, peers, country.
        """
        try:
            client = self._get_client()
            profile = client.company_profile2(symbol=ticker)
            if not profile:
                logger.warning("Finnhub: no profile for %s", ticker)
                return None

            market_cap_b = None
            if profile.get("marketCapitalization"):
                # Finnhub returns market cap in millions
                market_cap_b = float(profile["marketCapitalization"]) / 1000

            peers = []
            try:
                peers = client.company_peers(ticker) or []
            except Exception:
                pass

            return {
                "ticker": ticker.upper(),
                "name": profile.get("name", ""),
                "sector": profile.get("finnhubIndustry", ""),
                "market_cap_b": market_cap_b,
                "country": profile.get("country", ""),
                "currency": profile.get("currency", "USD"),
                "exchange": profile.get("exchange", ""),
                "ipo": profile.get("ipo", ""),
                "logo": profile.get("logo", ""),
                "weburl": profile.get("weburl", ""),
                "peers": peers,
                "source": _SOURCE,
            }

        except Exception as e:
            logger.error("Finnhub get_fundamentals(%s) failed: %s", ticker, e)
            return None

    async def get_earnings_calendar(self, from_date: str, to_date: str) -> list[dict]:
        """
        Return upcoming earnings events between from_date and to_date (YYYY-MM-DD).
        Each entry: ticker, name, date, eps_estimate, revenue_estimate, hour.
        """
        try:
            client = self._get_client()
            cal = client.earnings_calendar(_from=from_date, to=to_date, symbol="", international=False)
            events = cal.get("earningsCalendar", []) if cal else []

            results = []
            for ev in events:
                results.append({
                    "ticker": ev.get("symbol", ""),
                    "name": ev.get("name", ""),
                    "date": ev.get("date", ""),
                    "hour": ev.get("hour", ""),  # "bmo" = before market, "amc" = after
                    "eps_estimate": ev.get("epsEstimate"),
                    "revenue_estimate": ev.get("revenueEstimate"),
                    "source": _SOURCE,
                })
            return results

        except Exception as e:
            logger.error("Finnhub get_earnings_calendar failed: %s", e)
            return []

    async def get_recommendations(self, ticker: str) -> Optional[dict]:
        """
        Return analyst recommendation trend and latest price target.
        """
        try:
            client = self._get_client()

            # Recommendation trend (strong_buy, buy, hold, sell, strong_sell counts)
            trend = client.recommendation_trends(ticker)
            target = client.price_target(ticker)

            if not trend and not target:
                return None

            latest_trend = trend[0] if trend else {}
            total_analysts = sum([
                latest_trend.get("strongBuy", 0),
                latest_trend.get("buy", 0),
                latest_trend.get("hold", 0),
                latest_trend.get("sell", 0),
                latest_trend.get("strongSell", 0),
            ])

            return {
                "ticker": ticker.upper(),
                "total_analysts": total_analysts,
                "strong_buy": latest_trend.get("strongBuy", 0),
                "buy": latest_trend.get("buy", 0),
                "hold": latest_trend.get("hold", 0),
                "sell": latest_trend.get("sell", 0),
                "strong_sell": latest_trend.get("strongSell", 0),
                "period": latest_trend.get("period", ""),
                "target_high": target.get("targetHigh") if target else None,
                "target_low": target.get("targetLow") if target else None,
                "target_mean": target.get("targetMean") if target else None,
                "target_median": target.get("targetMedian") if target else None,
                "source": _SOURCE,
            }

        except Exception as e:
            if "403" in str(e):
                logger.info("Finnhub get_recommendations(%s): requires paid plan (403)", ticker)
            else:
                logger.error("Finnhub get_recommendations(%s) failed: %s", ticker, e)
            return None

    async def get_news(self, ticker: str, limit: int = 10) -> list[NewsArticle]:
        """
        Company news with sentiment for a specific ticker.
        Sentiment from Finnhub's NLP model (score: -1 to 1).
        """
        try:
            from datetime import timedelta
            client = self._get_client()

            # Fetch last 7 days of news
            today = datetime.now(timezone.utc)
            from_date = (today - timedelta(days=7)).strftime("%Y-%m-%d")
            to_date = today.strftime("%Y-%m-%d")

            news = client.company_news(ticker, _from=from_date, to=to_date)
            if not news:
                return []

            # Get sentiment for recent headlines
            sentiments = {}
            try:
                sent_data = client.news_sentiment(ticker)
                if sent_data and sent_data.get("buzz"):
                    # Aggregate sentiment
                    score = sent_data.get("sentiment", {}).get("bullishPercent", 0.5)
                    sentiments["_overall"] = score
            except Exception:
                pass

            articles = []
            for item in news[:limit]:
                try:
                    ts = item.get("datetime", 0)
                    pub_dt = datetime.fromtimestamp(ts, tz=timezone.utc) if ts else datetime.now(timezone.utc)

                    sentiment_score = sentiments.get("_overall")
                    sentiment_label = None
                    if sentiment_score is not None:
                        if sentiment_score > 0.55:
                            sentiment_label = "positive"
                        elif sentiment_score < 0.45:
                            sentiment_label = "negative"
                        else:
                            sentiment_label = "neutral"

                    articles.append(NewsArticle(
                        title=item.get("headline", ""),
                        summary=item.get("summary", ""),
                        url=item.get("url", ""),
                        published_at=pub_dt,
                        source=_SOURCE,
                        ticker=ticker.upper(),
                        sentiment=sentiment_label,
                        sentiment_score=sentiment_score,
                        author=None,
                        image_url=item.get("image") or None,
                    ))
                except Exception:
                    continue

            return articles[:limit]

        except Exception as e:
            logger.error("Finnhub get_news(%s) failed: %s", ticker, e)
            return []

"""Finnhub provider -- fundamentals, earnings, analyst ratings, news."""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from src.models.news import NewsArticle
from src.providers.base import AuthError

logger = logging.getLogger(__name__)

_SOURCE = "finnhub"


class FinnhubProvider:
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
        try:
            client = self._get_client()
            profile = client.company_profile2(symbol=ticker)
            if not profile:
                logger.warning("Finnhub: no profile for %s", ticker)
                return None

            mc = profile.get("marketCapitalization")
            peers = []
            try:
                peers = client.company_peers(ticker) or []
            except Exception:
                pass

            return {
                "ticker": ticker.upper(),
                "name": profile.get("name", ""),
                "sector": profile.get("finnhubIndustry", ""),
                "market_cap_b": float(mc) / 1000 if mc else None,
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
        try:
            cal = self._get_client().earnings_calendar(
                _from=from_date, to=to_date, symbol="", international=False
            )
            return [
                {
                    "ticker": ev.get("symbol", ""), "name": ev.get("name", ""),
                    "date": ev.get("date", ""), "hour": ev.get("hour", ""),
                    "eps_estimate": ev.get("epsEstimate"),
                    "revenue_estimate": ev.get("revenueEstimate"),
                    "source": _SOURCE,
                }
                for ev in (cal.get("earningsCalendar", []) if cal else [])
            ]
        except Exception as e:
            logger.error("Finnhub get_earnings_calendar failed: %s", e)
            return []

    async def get_recommendations(self, ticker: str) -> Optional[dict]:
        try:
            client = self._get_client()
            trend = client.recommendation_trends(ticker)
            target = client.price_target(ticker)
            if not trend and not target:
                return None

            lt = trend[0] if trend else {}
            return {
                "ticker": ticker.upper(),
                "total_analysts": sum(lt.get(k, 0) for k in ("strongBuy", "buy", "hold", "sell", "strongSell")),
                "strong_buy": lt.get("strongBuy", 0), "buy": lt.get("buy", 0),
                "hold": lt.get("hold", 0), "sell": lt.get("sell", 0),
                "strong_sell": lt.get("strongSell", 0), "period": lt.get("period", ""),
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
        try:
            client = self._get_client()
            today = datetime.now(timezone.utc)
            news = client.company_news(
                ticker, _from=(today - timedelta(days=7)).strftime("%Y-%m-%d"),
                to=today.strftime("%Y-%m-%d"),
            )
            if not news:
                return []

            # Aggregate sentiment
            sentiment_score = None
            try:
                sent_data = client.news_sentiment(ticker)
                if sent_data and sent_data.get("buzz"):
                    sentiment_score = sent_data.get("sentiment", {}).get("bullishPercent", 0.5)
            except Exception:
                pass

            sentiment_label = None
            if sentiment_score is not None:
                sentiment_label = "positive" if sentiment_score > 0.55 else ("negative" if sentiment_score < 0.45 else "neutral")

            articles = []
            for item in news[:limit]:
                try:
                    ts = item.get("datetime", 0)
                    articles.append(NewsArticle(
                        title=item.get("headline", ""), summary=item.get("summary", ""),
                        url=item.get("url", ""),
                        published_at=datetime.fromtimestamp(ts, tz=timezone.utc) if ts else today,
                        source=_SOURCE, ticker=ticker.upper(),
                        sentiment=sentiment_label, sentiment_score=sentiment_score,
                        image_url=item.get("image") or None,
                    ))
                except Exception:
                    continue
            return articles
        except Exception as e:
            logger.error("Finnhub get_news(%s) failed: %s", ticker, e)
            return []

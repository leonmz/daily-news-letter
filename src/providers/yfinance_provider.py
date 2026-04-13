"""yfinance provider — delayed quotes, historical OHLCV, options chains, screener."""

import logging
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

from src.models.market import StockQuote, OptionsSnapshot, OptionContract
from src.providers.base import ProviderError
from src.utils.greeks import implied_vol, bs_greeks

logger = logging.getLogger(__name__)

_SOURCE = "yfinance"

# Market cap filter for top movers (default $10B)
_DEFAULT_MIN_CAP_B = 10.0
_DEFAULT_MIN_VOLUME = 10_000_000


class YFinanceProvider:
    """
    yfinance-based provider.

    Capabilities:
    - Delayed quotes (~15 min)
    - Historical OHLCV going back decades
    - Full options chain with Greeks
    - Screener for gainers/losers (market cap filtered)
    """

    def __init__(
        self,
        min_market_cap_b: float = _DEFAULT_MIN_CAP_B,
        min_volume: int = _DEFAULT_MIN_VOLUME,
    ):
        self.min_market_cap_b = min_market_cap_b
        self.min_volume = min_volume

    async def get_quote(self, ticker: str) -> Optional[StockQuote]:
        """Delayed quote (~15 min lag)."""
        try:
            import yfinance as yf

            t = yf.Ticker(ticker)
            info = t.fast_info

            price = getattr(info, "last_price", None)
            if price is None:
                # fallback to regular info
                full_info = t.info
                price = full_info.get("currentPrice") or full_info.get("regularMarketPrice")

            if price is None:
                logger.warning("yfinance: no price for %s", ticker)
                return None

            price = float(price)
            prev_close = getattr(info, "previous_close", None)
            if prev_close is None:
                full_info = t.info
                prev_close = full_info.get("previousClose")

            change = 0.0
            change_pct = 0.0
            if prev_close and float(prev_close) != 0:
                change = price - float(prev_close)
                change_pct = (change / float(prev_close)) * 100

            volume = getattr(info, "three_month_average_volume", None)
            try:
                # prefer today's volume
                hist = t.history(period="1d")
                if not hist.empty:
                    volume = int(hist["Volume"].iloc[-1])
            except Exception:
                pass
            volume = int(volume) if volume else 0

            market_cap = getattr(info, "market_cap", None)
            market_cap_b = float(market_cap) / 1e9 if market_cap else None

            full = t.info
            return StockQuote(
                ticker=ticker.upper(),
                price=price,
                change=change,
                change_pct=change_pct,
                volume=volume,
                market_cap=market_cap_b,
                timestamp=datetime.now(timezone.utc),
                source=_SOURCE,
                delayed=True,
                currency=getattr(info, "currency", "USD") or "USD",
                company_name=full.get("longName") or full.get("shortName"),
                sector=full.get("sector"),
            )

        except Exception as e:
            logger.error("yfinance get_quote(%s) failed: %s", ticker, e)
            return None

    async def get_historical(
        self, ticker: str, start: str, end: str
    ) -> Optional[pd.DataFrame]:
        """
        Return OHLCV DataFrame with DatetimeIndex.
        start/end: YYYY-MM-DD strings.
        """
        try:
            import yfinance as yf

            t = yf.Ticker(ticker)
            df = t.history(start=start, end=end, auto_adjust=True)
            if df.empty:
                logger.warning("yfinance: no historical data for %s (%s to %s)", ticker, start, end)
                return None
            return df

        except Exception as e:
            logger.error("yfinance get_historical(%s) failed: %s", ticker, e)
            return None

    async def get_expirations(self, ticker: str) -> list[str]:
        """Return available options expiration dates."""
        try:
            import yfinance as yf

            t = yf.Ticker(ticker)
            return list(t.options or [])
        except Exception as e:
            logger.error("yfinance get_expirations(%s) failed: %s", ticker, e)
            return []

    async def get_option_chain(
        self,
        ticker: str,
        expiry: Optional[str] = None,
        spot_price: Optional[float] = None,
        risk_free_rate: float = 0.043,
    ) -> Optional[OptionsSnapshot]:
        """
        Return full options chain for the given (or nearest) expiry.

        Greeks are computed via Black-Scholes using market-implied IV
        (back-calculated from the bid-ask mid price via Brent's method).
        This fixes yfinance's systematic IV error on deep-ITM LEAP options,
        where the raw impliedVolatility field is unreliable.

        Args:
            ticker:           underlying symbol
            expiry:           YYYY-MM-DD expiry date; uses nearest if None
            spot_price:       current underlying price; fetched automatically if None
            risk_free_rate:   annualised continuously-compounded rate (default 4.3%)
                              pass the 1Y Treasury from FRED for best accuracy
        """
        try:
            import yfinance as yf

            t = yf.Ticker(ticker)
            expirations = list(t.options or [])
            if not expirations:
                logger.warning("yfinance: no options for %s", ticker)
                return None

            if expiry is None:
                expiry = expirations[0]
            elif expiry not in expirations:
                logger.warning("yfinance: expiry %s not found for %s, using nearest", expiry, ticker)
                expiry = expirations[0]

            # Fetch spot price if not provided
            S = spot_price
            if S is None:
                quote = await self.get_quote(ticker)
                S = quote.price if quote else None
            if S is None or S <= 0:
                logger.warning("yfinance: could not determine spot price for %s, Greeks unavailable", ticker)

            chain = t.option_chain(expiry)
            exp_dt = datetime.strptime(expiry, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            T = max((exp_dt - datetime.now(timezone.utc)).days / 365.0, 1e-6)
            r = risk_free_rate

            def df_to_contracts(df: pd.DataFrame, option_type: str) -> list[OptionContract]:
                contracts = []
                for _, row in df.iterrows():
                    try:
                        K     = float(row.get("strike", 0))
                        bid   = float(row.get("bid", 0) or 0)
                        ask   = float(row.get("ask", 0) or 0)
                        last  = float(row.get("lastPrice", 0) or 0)
                        mid   = (bid + ask) / 2 if bid > 0 and ask > 0 else last

                        # Back-calculate IV from market price; fall back to yfinance raw IV
                        mkt_iv = None
                        greeks = {}
                        if S and S > 0 and mid > 0:
                            mkt_iv = implied_vol(S, K, T, r, mid, option_type)
                            if mkt_iv:
                                greeks = bs_greeks(S, K, T, r, mkt_iv, option_type)

                        # Use market IV if available, else yfinance's raw value as fallback
                        yf_iv = float(row["impliedVolatility"]) \
                            if "impliedVolatility" in row and pd.notna(row["impliedVolatility"]) \
                            else None
                        final_iv = mkt_iv if mkt_iv is not None else yf_iv

                        contracts.append(OptionContract(
                            strike=K,
                            expiry=expiry,
                            option_type=option_type,
                            last_price=last,
                            bid=bid,
                            ask=ask,
                            volume=int(row.get("volume", 0) or 0),
                            open_interest=int(row.get("openInterest", 0) or 0),
                            implied_volatility=final_iv,
                            delta=greeks.get("delta"),
                            gamma=greeks.get("gamma"),
                            theta=greeks.get("theta"),
                            vega=greeks.get("vega"),
                        ))
                    except Exception:
                        continue
                return contracts

            calls = df_to_contracts(chain.calls, "call")
            puts  = df_to_contracts(chain.puts,  "put")

            snap = OptionsSnapshot(
                ticker=ticker.upper(),
                expirations=expirations,
                calls=calls,
                puts=puts,
                timestamp=datetime.now(timezone.utc),
                source=_SOURCE,
            )
            logger.debug(
                "yfinance %s %s: %d calls, %d puts, Greeks=%s",
                ticker, expiry, len(calls), len(puts), snap.has_greeks,
            )
            return snap

        except Exception as e:
            logger.error("yfinance get_option_chain(%s) failed: %s", ticker, e)
            return None

    async def get_top_movers(self, limit: int = 10) -> dict[str, list[StockQuote]]:
        """
        Use yfinance screener to find top gainers/losers with market cap filter.
        """
        try:
            import yfinance as yf

            # yfinance screener — day gainers and day losers
            gainers_raw = []
            losers_raw = []

            try:
                screener = yf.screen("day_gainers", offset=0, count=50)
                gainers_raw = screener.get("quotes", []) if screener else []
            except Exception as e:
                logger.debug("yfinance day_gainers screener failed: %s", e)

            try:
                screener = yf.screen("day_losers", offset=0, count=50)
                losers_raw = screener.get("quotes", []) if screener else []
            except Exception as e:
                logger.debug("yfinance day_losers screener failed: %s", e)

            def filter_and_convert(items: list[dict]) -> list[StockQuote]:
                results = []
                for item in items:
                    try:
                        mc = item.get("marketCap")
                        mc_b = float(mc) / 1e9 if mc else 0
                        vol = item.get("regularMarketVolume", 0) or 0

                        if mc_b < self.min_market_cap_b:
                            continue
                        if vol < self.min_volume:
                            continue

                        price = float(item.get("regularMarketPrice", 0))
                        change = float(item.get("regularMarketChange", 0))
                        change_pct = float(item.get("regularMarketChangePercent", 0))

                        results.append(StockQuote(
                            ticker=item.get("symbol", "").upper(),
                            price=price,
                            change=change,
                            change_pct=change_pct,
                            volume=int(vol),
                            market_cap=mc_b if mc_b > 0 else None,
                            timestamp=datetime.now(timezone.utc),
                            source=_SOURCE,
                            delayed=True,
                            company_name=item.get("longName") or item.get("shortName"),
                        ))
                    except Exception:
                        continue
                return results

            gainers = filter_and_convert(gainers_raw)[:limit]
            losers = filter_and_convert(losers_raw)[:limit]
            return {"gainers": gainers, "losers": losers}

        except Exception as e:
            logger.error("yfinance get_top_movers failed: %s", e)
            return {"gainers": [], "losers": []}

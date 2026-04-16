"""Databento provider — OPRA historical options + equity OHLCV via databento SDK.

Databento provides raw market data (bid/ask/volume/OI) but NOT pre-computed
Greeks or IV. We reuse greeks.py for BS-based IV back-calculation and Greeks,
same approach as the yfinance fallback path.

Requires: DATABENTO_API_KEY (32-char key starting with 'db-')
Dataset:  OPRA.PILLAR (US equity options, all 17 exchanges, back to 2013-04)
"""

import logging
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

from data.models.market import OptionContract, OptionsSnapshot, StockQuote
from data.providers.base import AuthError, ProviderError
from data.utils.greeks import bs_greeks, implied_vol

logger = logging.getLogger(__name__)

_SOURCE = "databento"


class DatabentoProvider:
    """Historical options (OPRA) and equities via Databento."""

    def __init__(self, api_key: str, timeout: float = 30):
        if not api_key:
            raise AuthError("DATABENTO_API_KEY is required")
        self._api_key = api_key
        self._timeout = timeout
        self._client = None

    def _get_client(self):
        if self._client is None:
            import databento as db
            self._client = db.Historical(self._api_key)
        return self._client

    # ------------------------------------------------------------------
    # OptionsProvider protocol
    # ------------------------------------------------------------------

    async def get_expirations(self, ticker: str) -> list[str]:
        try:
            client = self._get_client()
            data = client.timeseries.get_range(
                dataset="OPRA.PILLAR",
                schema="definition",
                symbols=f"{ticker.upper()}.OPT",
                stype_in="parent",
                start=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                end=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            )
            df = data.to_df()
            if df.empty:
                return []
            expiries = sorted(df["expiration"].dropna().unique())
            return [pd.Timestamp(e).strftime("%Y-%m-%d") for e in expiries]
        except Exception as e:
            logger.error("databento get_expirations(%s): %s", ticker, e)
            return []

    async def get_option_chain(
        self,
        ticker: str,
        expiry: Optional[str] = None,
        spot_price: Optional[float] = None,
        risk_free_rate: float = 0.043,
    ) -> Optional[OptionsSnapshot]:
        """Fetch option chain from Databento OPRA.

        Queries definition + mbp-1 schemas, merges them, and computes
        Greeks via BS (Databento provides raw quotes only).
        """
        try:
            client = self._get_client()
            symbol = f"{ticker.upper()}.OPT"
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

            defs = client.timeseries.get_range(
                dataset="OPRA.PILLAR",
                schema="definition",
                symbols=symbol,
                stype_in="parent",
                start=today,
                end=today,
            )
            def_df = defs.to_df()
            if def_df.empty:
                logger.warning("databento: no definitions for %s", ticker)
                return None

            mbp = client.timeseries.get_range(
                dataset="OPRA.PILLAR",
                schema="mbp-1",
                symbols=symbol,
                stype_in="parent",
                start=today,
                end=today,
            )
            mbp_df = mbp.to_df()

            try:
                stats = client.timeseries.get_range(
                    dataset="OPRA.PILLAR",
                    schema="statistics",
                    symbols=symbol,
                    stype_in="parent",
                    start=today,
                    end=today,
                )
                stats_df = stats.to_df()
            except Exception:
                stats_df = pd.DataFrame()

            contracts = self._build_contracts(
                def_df, mbp_df, stats_df, ticker, expiry,
                spot_price=spot_price, risk_free_rate=risk_free_rate,
            )
            if not contracts:
                return None

            expirations = sorted({c.expiry for c in contracts})
            return OptionsSnapshot(
                ticker=ticker.upper(),
                expirations=expirations,
                calls=[c for c in contracts if c.option_type == "call"],
                puts=[c for c in contracts if c.option_type == "put"],
                timestamp=datetime.now(timezone.utc),
                source=_SOURCE,
            )
        except Exception as e:
            logger.error("databento get_option_chain(%s): %s", ticker, e)
            return None

    async def find_by_delta(
        self,
        ticker: str,
        target_delta: float = 0.85,
        option_type: str = "call",
        min_expiry_days: int = 730,
        max_spread_pct: float = 0.10,
        min_open_interest: int = 0,
        num_expiries: int = 3,
        max_delta_deviation: float = 0.03,
        spot_price_override: Optional[float] = None,
    ) -> Optional[OptionContract]:
        snap = await self.get_option_chain(ticker, spot_price=spot_price_override)
        if snap is None:
            return None

        cutoff = datetime.now() + pd.Timedelta(days=min_expiry_days)
        pool = snap.calls if option_type == "call" else snap.puts
        pool = [
            c for c in pool
            if datetime.strptime(c.expiry, "%Y-%m-%d") >= cutoff
        ]

        expiries = sorted({c.expiry for c in pool})[:num_expiries]
        pool = [c for c in pool if c.expiry in expiries]

        def ok(c: OptionContract) -> bool:
            if c.delta is None or c.bid <= 0 or c.ask <= 0:
                return False
            mid = (c.bid + c.ask) / 2
            if (c.ask - c.bid) / mid > max_spread_pct:
                return False
            if c.open_interest < min_open_interest:
                return False
            return True

        pool = [c for c in pool if ok(c)]
        if not pool:
            return None

        best = min(
            pool,
            key=lambda c: abs(
                (abs(c.delta) if option_type == "put" else c.delta) - target_delta
            ),
        )
        d = abs(best.delta) if option_type == "put" else best.delta
        if abs(d - target_delta) > max_delta_deviation:
            return None
        return best

    # ------------------------------------------------------------------
    # HistoricalProvider protocol
    # ------------------------------------------------------------------

    async def get_historical(
        self, ticker: str, start: str, end: str,
    ) -> Optional[pd.DataFrame]:
        """Fetch daily OHLCV for an equity from Databento."""
        try:
            client = self._get_client()
            data = client.timeseries.get_range(
                dataset="XNAS.ITCH",
                schema="ohlcv-1d",
                symbols=ticker.upper(),
                start=start,
                end=end,
            )
            df = data.to_df()
            if df.empty:
                return None
            df = df.rename(columns={
                "open": "Open", "high": "High", "low": "Low",
                "close": "Close", "volume": "Volume",
            })
            return df[["Open", "High", "Low", "Close", "Volume"]]
        except Exception as e:
            logger.error("databento get_historical(%s): %s", ticker, e)
            return None

    # ------------------------------------------------------------------
    # Historical options chain (for backtesting calibration)
    # ------------------------------------------------------------------

    async def get_historical_option_chain(
        self,
        ticker: str,
        date: str,
        expiry: Optional[str] = None,
        spot_price: Optional[float] = None,
        risk_free_rate: float = 0.043,
    ) -> Optional[OptionsSnapshot]:
        """Fetch historical option chain for a past date.

        This is the key method for backtesting calibration — compare
        BS theoretical prices against actual historical bid/ask.
        """
        try:
            client = self._get_client()
            symbol = f"{ticker.upper()}.OPT"

            defs = client.timeseries.get_range(
                dataset="OPRA.PILLAR",
                schema="definition",
                symbols=symbol,
                stype_in="parent",
                start=date,
                end=date,
            )
            def_df = defs.to_df()
            if def_df.empty:
                return None

            mbp = client.timeseries.get_range(
                dataset="OPRA.PILLAR",
                schema="mbp-1",
                symbols=symbol,
                stype_in="parent",
                start=date,
                end=date,
            )
            mbp_df = mbp.to_df()

            try:
                stats = client.timeseries.get_range(
                    dataset="OPRA.PILLAR",
                    schema="statistics",
                    symbols=symbol,
                    stype_in="parent",
                    start=date,
                    end=date,
                )
                stats_df = stats.to_df()
            except Exception:
                stats_df = pd.DataFrame()

            contracts = self._build_contracts(
                def_df, mbp_df, stats_df, ticker, expiry,
                spot_price=spot_price, risk_free_rate=risk_free_rate,
            )
            if not contracts:
                return None

            expirations = sorted({c.expiry for c in contracts})
            return OptionsSnapshot(
                ticker=ticker.upper(),
                expirations=expirations,
                calls=[c for c in contracts if c.option_type == "call"],
                puts=[c for c in contracts if c.option_type == "put"],
                timestamp=datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc),
                source=_SOURCE,
            )
        except Exception as e:
            logger.error("databento get_historical_option_chain(%s, %s): %s", ticker, date, e)
            return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_contracts(
        self,
        def_df: pd.DataFrame,
        mbp_df: pd.DataFrame,
        stats_df: pd.DataFrame,
        ticker: str,
        expiry_filter: Optional[str],
        spot_price: Optional[float] = None,
        risk_free_rate: float = 0.043,
    ) -> list[OptionContract]:
        """Merge definition + quotes + stats into OptionContract list."""
        if def_df.empty:
            return []

        merged = def_df.copy()

        if not mbp_df.empty and "instrument_id" in mbp_df.columns:
            last_quotes = mbp_df.groupby("instrument_id").last()
            bid_col = "bid_px_00" if "bid_px_00" in last_quotes.columns else "bid_px"
            ask_col = "ask_px_00" if "ask_px_00" in last_quotes.columns else "ask_px"
            quote_cols = {}
            if bid_col in last_quotes.columns:
                quote_cols["_bid"] = last_quotes[bid_col]
            if ask_col in last_quotes.columns:
                quote_cols["_ask"] = last_quotes[ask_col]
            if quote_cols:
                quotes_mini = pd.DataFrame(quote_cols)
                merged = merged.join(quotes_mini, on="instrument_id", how="left")

        if not stats_df.empty and "instrument_id" in stats_df.columns:
            oi_df = stats_df.groupby("instrument_id").last()
            if "quantity" in oi_df.columns:
                merged = merged.join(
                    oi_df[["quantity"]].rename(columns={"quantity": "_oi"}),
                    on="instrument_id", how="left",
                )

        S = spot_price
        r = risk_free_rate
        now = datetime.now(timezone.utc)
        contracts: list[OptionContract] = []

        for _, row in merged.iterrows():
            try:
                strike_raw = row.get("strike_price")
                if strike_raw is None or pd.isna(strike_raw):
                    continue
                K = float(strike_raw) / 1e9 if float(strike_raw) > 1e6 else float(strike_raw)

                exp_raw = row.get("expiration")
                if exp_raw is None or pd.isna(exp_raw):
                    continue
                exp_str = pd.Timestamp(exp_raw).strftime("%Y-%m-%d")

                if expiry_filter and exp_str != expiry_filter:
                    continue

                inst_class = row.get("instrument_class", "")
                if hasattr(inst_class, "name"):
                    inst_class = inst_class.name
                inst_class = str(inst_class).upper()
                if "C" in inst_class:
                    opt_type = "call"
                elif "P" in inst_class:
                    opt_type = "put"
                else:
                    continue

                bid = float(row.get("_bid", 0) or 0)
                ask = float(row.get("_ask", 0) or 0)
                mid = (bid + ask) / 2 if bid > 0 and ask > 0 else 0
                oi = int(row.get("_oi", 0) or 0)
                vol = int(row.get("volume", 0) or 0)

                exp_dt = datetime.strptime(exp_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                T = max((exp_dt - now).days / 365.0, 1e-6)

                mkt_iv, greeks = None, {}
                if S and S > 0 and mid > 0:
                    mkt_iv = implied_vol(S, K, T, r, mid, opt_type)
                    if mkt_iv:
                        greeks = bs_greeks(S, K, T, r, mkt_iv, opt_type)

                contracts.append(OptionContract(
                    strike=K, expiry=exp_str, option_type=opt_type,
                    last_price=mid, bid=bid, ask=ask,
                    volume=vol, open_interest=oi,
                    implied_volatility=mkt_iv,
                    delta=greeks.get("delta"),
                    gamma=greeks.get("gamma"),
                    theta=greeks.get("theta"),
                    vega=greeks.get("vega"),
                ))
            except Exception:
                continue

        return contracts

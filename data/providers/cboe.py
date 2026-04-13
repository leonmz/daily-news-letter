"""CBOE provider — pre-computed Greeks direct from the exchange. No API key."""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

from data.models.market import OptionContract, OptionsSnapshot

logger = logging.getLogger(__name__)

_URL = "https://cdn.cboe.com/api/global/delayed_quotes/options/{}.json"


def _parse(o: dict, ticker: str) -> Optional[OptionContract]:
    """Parse one CBOE JSON object → OptionContract."""
    try:
        sym = o["option"]
        ticker = ticker.upper()
        r = sym[len(ticker):]  # "271217C00560000"
        return OptionContract(
            strike=int(r[7:]) / 1000,
            expiry=f"20{r[:2]}-{r[2:4]}-{r[4:6]}",
            option_type="call" if r[6] == "C" else "put",
            last_price=o.get("last_trade_price") or 0,
            bid=float(o.get("bid") or 0),
            ask=float(o.get("ask") or 0),
            volume=int(o.get("volume") or 0),
            open_interest=int(o.get("open_interest") or 0),
            implied_volatility=o.get("iv"),
            delta=o.get("delta"),
            gamma=o.get("gamma"),
            theta=o.get("theta"),
            vega=o.get("vega"),
        )
    except Exception:
        return None


class CBOEProvider:
    """CBOE delayed quotes (15-min) with exchange-computed Greeks."""

    def __init__(self, timeout: float = 15):
        self._timeout = timeout

    async def _fetch(self, ticker: str) -> list[dict]:
        async with httpx.AsyncClient(timeout=self._timeout) as c:
            r = await c.get(_URL.format(ticker.upper()))
            r.raise_for_status()
            return r.json().get("data", {}).get("options", [])

    async def get_option_chain(
        self, ticker: str, expiry: Optional[str] = None,
    ) -> Optional[OptionsSnapshot]:
        try:
            contracts = [_parse(o, ticker) for o in await self._fetch(ticker)]
            contracts = [c for c in contracts if c and (expiry is None or c.expiry == expiry)]
            if not contracts:
                return None
            return OptionsSnapshot(
                ticker=ticker.upper(),
                expirations=sorted({c.expiry for c in contracts}),
                calls=[c for c in contracts if c.option_type == "call"],
                puts=[c for c in contracts if c.option_type == "put"],
                timestamp=datetime.now(timezone.utc),
                source="cboe",
            )
        except Exception as e:
            logger.error("CBOE chain(%s): %s", ticker, e)
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
    ) -> Optional[OptionContract]:
        """Find the contract closest to target_delta among qualifying LEAPs."""
        try:
            raw = await self._fetch(ticker)
            cutoff = datetime.now() + timedelta(days=min_expiry_days)

            # Parse all, filter by type + expiry
            parsed = [_parse(o, ticker) for o in raw]
            pool = [
                c for c in parsed
                if c
                and c.option_type == option_type
                and datetime.strptime(c.expiry, "%Y-%m-%d") >= cutoff
            ]

            # Keep only nearest N expirations
            expiries = sorted({c.expiry for c in pool})[:num_expiries]
            pool = [c for c in pool if c.expiry in expiries]

            # Liquidity gate + delta available
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

            best = min(pool, key=lambda c: abs((abs(c.delta) if option_type == "put" else c.delta) - target_delta))
            d = abs(best.delta) if option_type == "put" else best.delta
            if abs(d - target_delta) > max_delta_deviation:
                return None
            return best

        except Exception as e:
            logger.error("CBOE find_by_delta(%s): %s", ticker, e)
            return None

    async def get_expirations(self, ticker: str) -> list[str]:
        try:
            parsed = [_parse(o, ticker) for o in await self._fetch(ticker)]
            return sorted({c.expiry for c in parsed if c})
        except Exception:
            return []

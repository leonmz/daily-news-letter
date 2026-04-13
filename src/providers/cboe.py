"""CBOE provider — pre-computed Greeks from the exchange itself.

CBOE publishes delayed quotes (15-min) for all listed options including
full Greeks (delta, gamma, theta, vega, rho) computed by the exchange.
No API key required. One HTTP call returns the entire chain for a symbol.

This replaces the need to self-calculate Greeks via Black-Scholes.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

import httpx

from src.models.market import OptionContract, OptionsSnapshot

logger = logging.getLogger(__name__)

_SOURCE = "cboe"
_BASE_URL = "https://cdn.cboe.com/api/global/delayed_quotes/options"


class CBOEProvider:
    """
    CBOE delayed options data with pre-computed Greeks.

    - No API key required
    - 15-minute delayed data
    - Full Greeks: delta, gamma, theta, vega, rho
    - Covers all US-listed equity options
    """

    def __init__(self, timeout: float = 15):
        self._timeout = timeout

    async def get_option_chain(
        self,
        ticker: str,
        expiry: Optional[str] = None,
    ) -> Optional[OptionsSnapshot]:
        """
        Fetch the full options chain with pre-computed Greeks.

        If expiry is specified (YYYY-MM-DD), only contracts matching that
        expiration are returned. Otherwise, all expirations are included.
        """
        try:
            raw = await self._fetch_raw(ticker)
            if raw is None:
                return None

            options = raw.get("data", {}).get("options", [])
            if not options:
                logger.warning("CBOE: no options for %s", ticker)
                return None

            calls = []
            puts = []
            expirations_set: set[str] = set()

            for o in options:
                contract = self._parse_contract(o, ticker)
                if contract is None:
                    continue
                if expiry and contract.expiry != expiry:
                    continue
                expirations_set.add(contract.expiry)
                if contract.option_type == "call":
                    calls.append(contract)
                else:
                    puts.append(contract)

            expirations = sorted(expirations_set)

            return OptionsSnapshot(
                ticker=ticker.upper(),
                expirations=expirations,
                calls=calls,
                puts=puts,
                timestamp=datetime.now(timezone.utc),
                source=_SOURCE,
            )

        except Exception as e:
            logger.error("CBOE get_option_chain(%s) failed: %s", ticker, e)
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
        """
        Find the contract closest to a target delta.

        Searches across multiple qualifying expirations and applies liquidity
        filters. Returns None if no contract within max_delta_deviation.

        Args:
            ticker:              underlying symbol
            target_delta:        target delta (0–1 for calls, use abs value)
            option_type:         "call" or "put"
            min_expiry_days:     minimum days to expiry (730 = ~2yr LEAP)
            max_spread_pct:      max (ask-bid)/mid to include (liquidity gate)
            min_open_interest:   minimum open interest to include
            num_expiries:        search across top N qualifying expirations
            max_delta_deviation: reject if best |delta - target| exceeds this
        """
        try:
            raw = await self._fetch_raw(ticker)
            if raw is None:
                return None

            options = raw.get("data", {}).get("options", [])
            from datetime import timedelta
            today = datetime.now()
            min_expiry_date = today + timedelta(days=min_expiry_days)

            # Collect all qualifying expirations
            qualifying_expiries: set[str] = set()
            for o in options:
                sym = o.get("option", "")
                exp_str = self._parse_expiry(sym, ticker)
                if exp_str and datetime.strptime(exp_str, "%Y-%m-%d") >= min_expiry_date:
                    qualifying_expiries.add(exp_str)

            # Take the nearest N expirations
            target_expiries = sorted(qualifying_expiries)[:num_expiries]
            if not target_expiries:
                logger.warning("CBOE: no LEAP expirations found for %s", ticker)
                return None

            # Search across all qualifying expirations
            candidates = []
            for o in options:
                sym = o.get("option", "")
                exp_str = self._parse_expiry(sym, ticker)
                if exp_str not in target_expiries:
                    continue

                is_call = f"C" in sym[len(ticker) + 6:]
                is_put = f"P" in sym[len(ticker) + 6:]

                if option_type == "call" and not is_call:
                    continue
                if option_type == "put" and not is_put:
                    continue

                delta = o.get("delta")
                bid = o.get("bid") or 0
                ask = o.get("ask") or 0
                if delta is None or bid <= 0 or ask <= 0:
                    continue

                mid = (bid + ask) / 2

                # Liquidity gate
                spread_pct = (ask - bid) / mid if mid > 0 else 999
                if spread_pct > max_spread_pct:
                    continue

                oi = o.get("open_interest") or 0
                if oi < min_open_interest:
                    continue

                delta_val = abs(delta) if option_type == "put" else delta
                diff = abs(delta_val - target_delta)

                candidates.append((diff, o, exp_str))

            if not candidates:
                logger.warning("CBOE: no contracts passed filters for %s δ=%.2f", ticker, target_delta)
                return None

            candidates.sort(key=lambda x: x[0])
            best_diff, best_o, best_exp = candidates[0]

            if best_diff > max_delta_deviation:
                logger.warning(
                    "CBOE: best delta=%.3f for %s, deviation %.3f > max %.3f",
                    best_o.get("delta"), ticker, best_diff, max_delta_deviation,
                )
                return None

            return self._parse_contract(best_o, ticker)

        except Exception as e:
            logger.error("CBOE find_by_delta(%s) failed: %s", ticker, e)
            return None

    async def get_expirations(self, ticker: str) -> list[str]:
        """Return all available expiration dates."""
        try:
            raw = await self._fetch_raw(ticker)
            if raw is None:
                return []
            options = raw.get("data", {}).get("options", [])
            expiries = set()
            for o in options:
                exp = self._parse_expiry(o.get("option", ""), ticker)
                if exp:
                    expiries.add(exp)
            return sorted(expiries)
        except Exception as e:
            logger.error("CBOE get_expirations(%s) failed: %s", ticker, e)
            return []

    # ── internal helpers ───────────────────────────────────────────────

    async def _fetch_raw(self, ticker: str) -> Optional[dict]:
        url = f"{_BASE_URL}/{ticker.upper()}.json"
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                logger.error("CBOE API %d for %s", resp.status_code, ticker)
                return None
            return resp.json()

    @staticmethod
    def _parse_expiry(occ_symbol: str, ticker: str) -> Optional[str]:
        """Parse expiry from OCC symbol, e.g. SPY271217C00560000 → 2027-12-17."""
        try:
            rest = occ_symbol[len(ticker):]
            yy, mm, dd = rest[:2], rest[2:4], rest[4:6]
            return f"20{yy}-{mm}-{dd}"
        except (IndexError, ValueError):
            return None

    @staticmethod
    def _parse_contract(o: dict, ticker: str) -> Optional[OptionContract]:
        """Convert a CBOE JSON option object to an OptionContract."""
        try:
            sym = o.get("option", "")
            rest = sym[len(ticker):]
            exp_str = f"20{rest[:2]}-{rest[2:4]}-{rest[4:6]}"
            option_type = "call" if "C" in rest[6:] else "put"
            strike = int(rest[7:]) / 1000  # OCC uses 8-digit strike * 1000

            bid = o.get("bid") or 0
            ask = o.get("ask") or 0

            return OptionContract(
                strike=strike,
                expiry=exp_str,
                option_type=option_type,
                last_price=o.get("last_trade_price") or 0,
                bid=float(bid),
                ask=float(ask),
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

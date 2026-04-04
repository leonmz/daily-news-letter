"""
Fetch top market movers (gainers + losers) with sector info.

Primary: Financial Modeling Prep API (free tier)
Fallback: yfinance (no API key needed, less reliable)
"""

import requests
import yfinance as yf
from config import FMP_API_KEY, FMP_BASE, SECTOR_MAP


def fetch_top_movers_fmp(limit: int = 10) -> dict:
    """Fetch top gainers and losers from FMP."""
    result = {"gainers": [], "losers": []}

    for direction in ["gainers", "losers"]:
        url = f"{FMP_BASE}/stock_market/{direction}"
        params = {"apikey": FMP_API_KEY}
        try:
            resp = requests.get(url, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            for item in data[: limit // 2]:
                ticker = item.get("symbol", "")
                sector_raw = item.get("sector", "")
                sector = SECTOR_MAP.get(sector_raw, sector_raw.lower())

                result[direction].append(
                    {
                        "ticker": ticker,
                        "name": item.get("name", ticker),
                        "price": item.get("price", 0),
                        "change_pct": round(item.get("changesPercentage", 0), 2),
                        "change_abs": round(item.get("change", 0), 2),
                        "volume": item.get("volume", 0),
                        "sector": sector,
                        "sector_raw": sector_raw,
                    }
                )
        except Exception as e:
            print(f"[FMP] Error fetching {direction}: {e}")

    return result


def fetch_top_movers_yfinance(limit: int = 10) -> dict:
    """Fallback: fetch top movers via yfinance screen()."""
    result = {"gainers": [], "losers": []}

    for direction, key in [("gainers", "day_gainers"), ("losers", "day_losers")]:
        try:
            data = yf.screen(key, count=limit // 2)
            quotes = data.get("quotes", [])

            for q in quotes[: limit // 2]:
                ticker = q.get("symbol", "")
                # Get sector info via Ticker object
                try:
                    info = yf.Ticker(ticker).info
                    sector_raw = info.get("sector", "Unknown")
                except Exception:
                    sector_raw = "Unknown"

                sector = SECTOR_MAP.get(sector_raw, sector_raw.lower())
                result[direction].append(
                    {
                        "ticker": ticker,
                        "name": q.get("shortName", ticker),
                        "price": q.get("regularMarketPrice", 0),
                        "change_pct": round(
                            q.get("regularMarketChangePercent", 0), 2
                        ),
                        "change_abs": round(
                            q.get("regularMarketChange", 0), 2
                        ),
                        "volume": q.get("regularMarketVolume", 0),
                        "sector": sector,
                        "sector_raw": sector_raw,
                    }
                )
        except Exception as e:
            print(f"[yfinance] Error fetching {direction}: {e}")

    return result


def get_top_movers(limit: int = 10) -> dict:
    """Get top movers, trying FMP first then yfinance fallback."""
    if FMP_API_KEY and FMP_API_KEY != "your_fmp_api_key_here":
        print("[market] Using FMP API...")
        movers = fetch_top_movers_fmp(limit)
        if movers["gainers"] or movers["losers"]:
            return movers
        print("[market] FMP returned empty, falling back to yfinance...")

    print("[market] Using yfinance fallback...")
    return fetch_top_movers_yfinance(limit)


def enrich_sector_info(movers: dict) -> dict:
    """Add sector info for any movers missing it (batch lookup via FMP)."""
    tickers_needing_sector = []
    for direction in ["gainers", "losers"]:
        for m in movers[direction]:
            if not m.get("sector") or m["sector"] == "unknown":
                tickers_needing_sector.append(m["ticker"])

    if not tickers_needing_sector or not FMP_API_KEY:
        return movers

    # Batch profile lookup
    tickers_str = ",".join(tickers_needing_sector[:20])
    try:
        url = f"{FMP_BASE}/profile/{tickers_str}"
        resp = requests.get(url, params={"apikey": FMP_API_KEY}, timeout=15)
        resp.raise_for_status()
        profiles = {p["symbol"]: p for p in resp.json()}

        for direction in ["gainers", "losers"]:
            for m in movers[direction]:
                if m["ticker"] in profiles:
                    sector_raw = profiles[m["ticker"]].get("sector", "")
                    m["sector_raw"] = sector_raw
                    m["sector"] = SECTOR_MAP.get(sector_raw, sector_raw.lower())
    except Exception as e:
        print(f"[market] Sector enrichment failed: {e}")

    return movers


# ---- Quick test ----
if __name__ == "__main__":
    import json

    movers = get_top_movers(10)
    movers = enrich_sector_info(movers)
    print(json.dumps(movers, indent=2))
    print(f"\nGainers: {len(movers['gainers'])}, Losers: {len(movers['losers'])}")

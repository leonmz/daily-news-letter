"""
Fetch top market movers (gainers + losers) with sector info.

Primary: Financial Modeling Prep API (free tier)
Fallback: yfinance (no API key needed, less reliable)

Also fetches blue chip movers and user watchlist via yfinance.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests
import yfinance as yf

from config import FMP_API_KEY, FMP_BASE, SECTOR_MAP, TOP_BLUE_CHIPS, WATCHLIST


# ── Market hours check ────────────────────────────────────────

ET = ZoneInfo("America/New_York")

# NYSE holidays (fixed + observed) by year. Extend each January or use a library.
# Sources: https://www.nyse.com/markets/hours-calendars
NYSE_HOLIDAYS: dict[int, set[str]] = {
    2025: {
        "2025-01-01",  # New Year's Day
        "2025-01-20",  # MLK Jr. Day
        "2025-02-17",  # Presidents' Day
        "2025-04-18",  # Good Friday
        "2025-05-26",  # Memorial Day
        "2025-07-04",  # Independence Day
        "2025-09-01",  # Labor Day
        "2025-11-27",  # Thanksgiving
        "2025-12-25",  # Christmas
    },
    2026: {
        "2026-01-01",  # New Year's Day
        "2026-01-19",  # MLK Jr. Day
        "2026-02-16",  # Presidents' Day
        "2026-04-03",  # Good Friday
        "2026-05-25",  # Memorial Day
        "2026-07-03",  # Independence Day (observed)
        "2026-09-07",  # Labor Day
        "2026-11-26",  # Thanksgiving
        "2026-12-25",  # Christmas
    },
    2027: {
        "2027-01-01",  # New Year's Day
        "2027-01-18",  # MLK Jr. Day
        "2027-02-15",  # Presidents' Day
        "2027-03-26",  # Good Friday
        "2027-05-31",  # Memorial Day
        "2027-07-05",  # Independence Day (observed)
        "2027-09-06",  # Labor Day
        "2027-11-25",  # Thanksgiving
        "2027-12-24",  # Christmas (observed)
    },
}


def _is_trading_day(d: datetime) -> bool:
    """Check if a given date is a NYSE trading day (not weekend or holiday)."""
    if d.weekday() > 4:
        return False
    year_holidays = NYSE_HOLIDAYS.get(d.year)
    if year_holidays is None:
        print(f"[market] ⚠️ NYSE holiday calendar not available for {d.year}, treating all weekdays as trading days")
        return True
    return d.strftime("%Y-%m-%d") not in year_holidays


def is_market_open() -> bool:
    """Check if US stock market is currently in regular trading hours."""
    now = datetime.now(ET)
    if not _is_trading_day(now):
        return False
    market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = now.replace(hour=16, minute=0, second=0, microsecond=0)
    return market_open <= now <= market_close


def get_last_trading_day() -> str:
    """Return the most recent trading day as YYYY-MM-DD."""
    now = datetime.now(ET)
    # If today's session hasn't closed yet, step back to the previous day so we
    # don't claim a day whose data isn't finalised.  Non-trading days are handled
    # by the while loop below, so we only need the AND condition here.
    market_close = now.replace(hour=16, minute=0, second=0, microsecond=0)
    if _is_trading_day(now) and now < market_close:
        now -= timedelta(days=1)
    # Skip weekends and holidays
    while not _is_trading_day(now):
        now -= timedelta(days=1)
    return now.strftime("%Y-%m-%d")


# ── FMP top movers ────────────────────────────────────────────

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


# ── yfinance top movers ───────────────────────────────────────

def fetch_top_movers_yfinance(limit: int = 10) -> dict:
    """Fallback: fetch top movers via yfinance screen()."""
    result = {"gainers": [], "losers": []}

    for direction, key in [("gainers", "day_gainers"), ("losers", "day_losers")]:
        try:
            data = yf.screen(key, count=limit // 2)
            quotes = data.get("quotes", [])

            for q in quotes[: limit // 2]:
                ticker = q.get("symbol", "")
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


# ── Blue chips + watchlist via yf.download ────────────────────

def _fetch_tickers_daily(tickers: list[str], label: str) -> list[dict]:
    """Fetch today's performance for a list of tickers via yf.download."""
    if not tickers:
        return []

    try:
        # Use last trading day to ensure we get data
        trading_day = get_last_trading_day()
        start = trading_day
        # Need next day as end (yfinance end is exclusive)
        end_dt = datetime.strptime(trading_day, "%Y-%m-%d") + timedelta(days=1)
        end = end_dt.strftime("%Y-%m-%d")

        df = yf.download(tickers, start=start, end=end, progress=False)

        if df.empty:
            print(f"[{label}] No data returned for {trading_day}")
            return []

        # Batch fetch ticker info (name + sector) via yf.Tickers
        ticker_info = {}
        try:
            batch = yf.Tickers(" ".join(tickers))
            for ticker in tickers:
                try:
                    info = batch.tickers[ticker].info
                    ticker_info[ticker] = {
                        "name": info.get("shortName", ticker),
                        "sector_raw": info.get("sector", "Unknown"),
                    }
                except Exception:
                    ticker_info[ticker] = {"name": ticker, "sector_raw": "Unknown"}
        except Exception:
            for ticker in tickers:
                ticker_info[ticker] = {"name": ticker, "sector_raw": "Unknown"}

        results = []
        for ticker in tickers:
            try:
                if len(tickers) == 1:
                    close = float(df["Close"].iloc[-1])
                    opn = float(df["Open"].iloc[-1])
                    volume = int(df["Volume"].iloc[-1])
                else:
                    close = float(df["Close"][ticker].iloc[-1])
                    opn = float(df["Open"][ticker].iloc[-1])
                    volume = int(df["Volume"][ticker].iloc[-1])

                change_abs = round(close - opn, 2)
                change_pct = round((change_abs / opn) * 100, 2) if opn > 0 else 0

                info = ticker_info.get(ticker, {"name": ticker, "sector_raw": "Unknown"})
                sector_raw = info["sector_raw"]
                sector = SECTOR_MAP.get(sector_raw, sector_raw.lower())
                results.append({
                    "ticker": ticker,
                    "name": info["name"],
                    "price": close,
                    "change_pct": change_pct,
                    "change_abs": change_abs,
                    "volume": volume,
                    "sector": sector,
                    "sector_raw": sector_raw,
                })
            except Exception as e:
                print(f"[{label}] Error processing {ticker}: {e}")

        return results

    except Exception as e:
        print(f"[{label}] Download failed: {e}")
        return []


def fetch_blue_chips(min_change_pct: float = 1.0) -> list[dict]:
    """Fetch today's data for top blue chips, filtered by minimum change %."""
    print(f"[market] Fetching blue chip data...")
    all_data = _fetch_tickers_daily(TOP_BLUE_CHIPS, "blue-chips")
    # Filter to significant movers only
    significant = [d for d in all_data if abs(d["change_pct"]) >= min_change_pct]
    print(f"      Blue chips: {len(significant)}/{len(all_data)} with >{min_change_pct}% move")
    return significant


def fetch_watchlist() -> list[dict]:
    """Fetch today's data for user's watchlist tickers."""
    if not WATCHLIST:
        return []
    print(f"[market] Fetching watchlist: {', '.join(WATCHLIST)}")
    data = _fetch_tickers_daily(WATCHLIST, "watchlist")
    print(f"      Watchlist: {len(data)} tickers")
    return data


# ── Unified interface ─────────────────────────────────────────

def get_top_movers(limit: int = 10) -> dict:
    """Get top movers, trying FMP first then yfinance fallback."""
    if is_market_open():
        print("[market] Market is OPEN — using live data")
    else:
        trading_day = get_last_trading_day()
        print(f"[market] Market is CLOSED — using data from {trading_day}")

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

    print(f"Market open: {is_market_open()}")
    print(f"Last trading day: {get_last_trading_day()}")

    movers = get_top_movers(10)
    movers = enrich_sector_info(movers)
    print(json.dumps(movers, indent=2))
    print(f"\nGainers: {len(movers['gainers'])}, Losers: {len(movers['losers'])}")

    blue = fetch_blue_chips()
    print(f"\nBlue chips with >1% move: {len(blue)}")
    for b in blue:
        print(f"  {b['ticker']}: {b['change_pct']:+.2f}%")

    watch = fetch_watchlist()
    print(f"\nWatchlist: {len(watch)}")
    for w in watch:
        print(f"  {w['ticker']}: {w['change_pct']:+.2f}%")

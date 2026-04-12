#!/usr/bin/env python3
"""
Data Provider Diagnostic Script
Verifies all provider adapters are working with real API calls.
Run from repo root: python scripts/diagnose.py
"""

import asyncio
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

# Ensure repo root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

# ─── Helpers ────────────────────────────────────────────────────────────────

GREEN  = "\033[32m"
YELLOW = "\033[33m"
RED    = "\033[31m"
RESET  = "\033[0m"
BOLD   = "\033[1m"

PASS_MARK  = f"{GREEN}✅{RESET}"
SKIP_MARK  = f"{YELLOW}⚠️  SKIPPED{RESET}"
FAIL_MARK  = f"{RED}❌{RESET}"

results: list[tuple[str, bool, str]] = []  # (label, passed, detail)


def check(label: str, passed: bool, detail: str = "", skipped: bool = False) -> None:
    pad = max(0, 52 - len(label))
    if skipped:
        mark = SKIP_MARK
        outcome = f"{YELLOW}— no API key{RESET}"
    elif passed:
        mark = PASS_MARK
        outcome = f"{GREEN}{detail}{RESET}"
    else:
        mark = FAIL_MARK
        outcome = f"{RED}{detail}{RESET}"
    print(f"  {label}{'.' * pad} {mark} {outcome}")
    results.append((label, passed if not skipped else None, detail))


async def timed(coro):
    """Run an async coroutine and return (result, elapsed_seconds)."""
    t0 = time.perf_counter()
    try:
        result = await coro
    except Exception as e:
        return None, time.perf_counter() - t0, str(e)
    return result, time.perf_counter() - t0, None


# ─── Alpaca ─────────────────────────────────────────────────────────────────

async def check_alpaca():
    api_key = os.getenv("ALPACA_API_KEY", "")
    secret  = os.getenv("ALPACA_SECRET_KEY", "")

    print(f"\n{BOLD}[Alpaca]{RESET}")

    if not api_key or not secret:
        for lbl in [
            "Stock quote NVDA",
            "Stock quote AAPL",
            "Top movers",
            "News NVDA (Benzinga)",
            "Market news",
        ]:
            check(lbl, False, skipped=True)
        return

    from src.providers.alpaca import AlpacaProvider
    p = AlpacaProvider(api_key, secret)

    # Quote NVDA
    q, elapsed, err = await timed(p.get_quote("NVDA"))
    if q:
        check("Stock quote NVDA", True, f"${q.price:.2f} (IEX real-time, {elapsed:.0f}s)")
    else:
        check("Stock quote NVDA", False, err or "no data")

    # Quote AAPL
    q2, elapsed2, err2 = await timed(p.get_quote("AAPL"))
    if q2:
        check("Stock quote AAPL", True, f"${q2.price:.2f} (IEX real-time, {elapsed2:.0f}s)")
    else:
        check("Stock quote AAPL", False, err2 or "no data")

    # Top movers
    mv, elapsed3, err3 = await timed(p.get_top_movers(10))
    if mv and (mv.get("gainers") or mv.get("losers")):
        ng = len(mv.get("gainers", []))
        nl = len(mv.get("losers", []))
        check("Top movers", True, f"{ng} gainers, {nl} losers ({elapsed3:.0f}s)")
    else:
        check("Top movers", False, err3 or "no data")

    # News NVDA
    news, elapsed4, err4 = await timed(p.get_news("NVDA", 5))
    if news:
        avg_len = sum(len(a.summary) for a in news) // len(news) if news else 0
        check("News NVDA (Benzinga)", True, f"{len(news)} articles, avg {avg_len} chars ({elapsed4:.0f}s)")
    else:
        check("News NVDA (Benzinga)", False, err4 or "no data")

    # Market news
    mnews, elapsed5, err5 = await timed(p.get_market_news(15))
    if mnews:
        check("Market news", True, f"{len(mnews)} articles ({elapsed5:.0f}s)")
    else:
        check("Market news", False, err5 or "no data")

    return q  # return NVDA quote for cross-check


# ─── Finnhub ─────────────────────────────────────────────────────────────────

async def check_finnhub():
    api_key = os.getenv("FINNHUB_API_KEY", "")

    print(f"\n{BOLD}[Finnhub]{RESET}")

    if not api_key:
        for lbl in ["Fundamentals NVDA", "Earnings calendar", "Analyst ratings NVDA", "News NVDA"]:
            check(lbl, False, skipped=True)
        return None

    from src.providers.finnhub import FinnhubProvider
    p = FinnhubProvider(api_key)

    # Fundamentals NVDA
    fund, elapsed, err = await timed(p.get_fundamentals("NVDA"))
    if fund:
        cap = fund.get("market_cap_b")
        cap_str = f"${cap/1000:.1f}T" if cap and cap > 1000 else (f"${cap:.0f}B" if cap else "?")
        sector = fund.get("sector", "?")
        check("Fundamentals NVDA", True, f"cap={cap_str}, sector={sector} ({elapsed:.0f}s)")
    else:
        check("Fundamentals NVDA", False, err or "no data")

    # Earnings calendar
    today = datetime.now(timezone.utc)
    to_dt = today + timedelta(weeks=2)
    cal, elapsed2, err2 = await timed(p.get_earnings_calendar(
        today.strftime("%Y-%m-%d"), to_dt.strftime("%Y-%m-%d")
    ))
    if cal is not None:
        check("Earnings calendar", True, f"{len(cal)} upcoming in 2 weeks ({elapsed2:.0f}s)")
    else:
        check("Earnings calendar", False, err2 or "no data")

    # Analyst ratings NVDA
    rec, elapsed3, err3 = await timed(p.get_recommendations("NVDA"))
    if rec:
        total = rec.get("total_analysts", 0)
        target = rec.get("target_mean")
        target_str = f"avg target ${target:.0f}" if target else "no target"
        check("Analyst ratings NVDA", True, f"{total} analysts, {target_str} ({elapsed3:.0f}s)")
    else:
        check("Analyst ratings NVDA", False, err3 or "no data")

    # News NVDA
    news, elapsed4, err4 = await timed(p.get_news("NVDA", 5))
    has_sentiment = any(a.sentiment is not None for a in (news or []))
    if news:
        check("News NVDA", True, f"{len(news)} articles, sentiment {'available' if has_sentiment else 'unavailable'} ({elapsed4:.0f}s)")
    else:
        check("News NVDA", False, err4 or "no data")

    return fund  # return for cross-check


# ─── yfinance ────────────────────────────────────────────────────────────────

async def check_yfinance():
    print(f"\n{BOLD}[yfinance]{RESET}")

    from src.providers.yfinance_provider import YFinanceProvider
    p = YFinanceProvider()

    # Quote NVDA
    q, elapsed, err = await timed(p.get_quote("NVDA"))
    if q:
        check("Quote NVDA", True, f"${q.price:.2f} (delayed ~15min, {elapsed:.0f}s)")
    else:
        check("Quote NVDA", False, err or "no data")

    # Historical SPY 10yr
    end = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    start = (datetime.now(timezone.utc) - timedelta(days=3650)).strftime("%Y-%m-%d")
    hist, elapsed2, err2 = await timed(p.get_historical("SPY", start, end))
    if hist is not None and not hist.empty:
        check("Historical SPY 10yr", True, f"{len(hist)} trading days ({elapsed2:.0f}s)")
    else:
        check("Historical SPY 10yr", False, err2 or "no data")

    # Options chain SPY
    opts, elapsed3, err3 = await timed(p.get_option_chain("SPY"))
    if opts:
        greek_str = "Greeks ✅" if opts.has_greeks else "Greeks ❌ (IV only)"
        check(
            "Options chain SPY",
            True,
            f"{len(opts.expirations)} expirations, {opts.total_contracts}+ contracts, {greek_str} ({elapsed3:.0f}s)"
        )
    else:
        check("Options chain SPY", False, err3 or "no data")

    # Top movers
    mv, elapsed4, err4 = await timed(p.get_top_movers(10))
    if mv and (mv.get("gainers") or mv.get("losers")):
        ng = len(mv.get("gainers", []))
        check("Top movers (screener)", True, f"{ng} gainers (filtered >${p.min_market_cap_b:.0f}B cap) ({elapsed4:.0f}s)")
    else:
        check("Top movers (screener)", False, err4 or "no data (market may be closed)")

    return q  # return NVDA quote for cross-check


# ─── FRED ────────────────────────────────────────────────────────────────────

async def check_fred():
    api_key = os.getenv("FRED_API_KEY", "")

    print(f"\n{BOLD}[FRED]{RESET}")

    if not api_key:
        for lbl in ["Fed Funds Rate", "10Y Treasury", "CPI YoY"]:
            check(lbl, False, skipped=True)
        return

    from src.providers.fred import FREDProvider
    p = FREDProvider(api_key)

    # Fed Funds Rate
    ffr, elapsed, err = await timed(p.get_indicator("FEDFUNDS"))
    if ffr:
        check("Fed Funds Rate", True, f"{ffr.value:.2f}% ({ffr.observation_date.strftime('%Y-%m-%d')}) ({elapsed:.0f}s)")
    else:
        check("Fed Funds Rate", False, err or "no data")

    # 10Y Treasury
    t10, elapsed2, err2 = await timed(p.get_indicator("DGS10"))
    if t10:
        check("10Y Treasury", True, f"{t10.value:.2f}% ({elapsed2:.0f}s)")
    else:
        check("10Y Treasury", False, err2 or "no data")

    # CPI
    cpi, elapsed3, err3 = await timed(p.get_indicator("CPIAUCSL"))
    if cpi:
        check("CPI YoY", True, f"{cpi.value:.1f} ({cpi.observation_date.strftime('%Y-%m')}) ({elapsed3:.0f}s)")
    else:
        check("CPI YoY", False, err3 or "no data")

    # Yield curve (bonus)
    yc, elapsed4, err4 = await timed(p.get_yield_curve())
    if yc:
        spread = yc.spread_10y_2y()
        spread_str = f", 10Y-2Y spread={spread:.2f}%" if spread is not None else ""
        inverted = " (INVERTED)" if yc.is_inverted else ""
        check("Yield curve", True, f"{len(yc.points)} maturities{spread_str}{inverted} ({elapsed4:.0f}s)")
    else:
        check("Yield curve", False, err4 or "no data")


# ─── Cross-checks ─────────────────────────────────────────────────────────────

def cross_check_price(
    alpaca_quote,
    yfinance_quote,
) -> None:
    print(f"\n{BOLD}[Cross-check]{RESET}")
    if not alpaca_quote or not yfinance_quote:
        check("NVDA price cross-check", False, "one or both providers unavailable")
        return

    a_price = alpaca_quote.price
    y_price = yfinance_quote.price
    diff_pct = abs(a_price - y_price) / max(a_price, y_price) * 100
    ok = diff_pct < 2.0  # allow 2% for delayed vs real-time
    check(
        "NVDA price: Alpaca vs yfinance",
        ok,
        f"Alpaca=${a_price:.2f}, yfinance=${y_price:.2f}, diff={diff_pct:.2f}%{'  ✅' if ok else ' (>2% — check data)'}",
    )


def cross_check_cap(finnhub_fund, yfinance_quote) -> None:
    if not finnhub_fund or not yfinance_quote:
        check("NVDA market cap cross-check", False, "one or both providers unavailable")
        return
    fh_cap = finnhub_fund.get("market_cap_b")
    yf_cap = yfinance_quote.market_cap
    if not fh_cap or not yf_cap:
        check("NVDA market cap cross-check", False, "market cap not returned by one provider")
        return
    diff_pct = abs(fh_cap - yf_cap) / max(fh_cap, yf_cap) * 100
    ok = diff_pct < 5.0
    fh_str = f"${fh_cap/1000:.1f}T" if fh_cap > 1000 else f"${fh_cap:.0f}B"
    yf_str = f"${yf_cap/1000:.1f}T" if yf_cap > 1000 else f"${yf_cap:.0f}B"
    check(
        "NVDA market cap: Finnhub vs yfinance",
        ok,
        f"Finnhub={fh_str}, yfinance={yf_str}{'  ✅' if ok else '  (>5% diff)'}",
    )


# ─── Main ─────────────────────────────────────────────────────────────────────

async def main():
    print(f"\n{BOLD}=== Data Provider Diagnostic ==={RESET}\n")

    alpaca_nvda = await check_alpaca()
    finnhub_fund = await check_finnhub()
    yfinance_nvda = await check_yfinance()
    await check_fred()

    # Cross-checks
    print(f"\n{BOLD}[Cross-checks]{RESET}")
    cross_check_price(alpaca_nvda, yfinance_nvda)
    cross_check_cap(finnhub_fund, yfinance_nvda)

    # Summary
    print()
    passed  = [r for r in results if r[1] is True]
    failed  = [r for r in results if r[1] is False]
    skipped = [r for r in results if r[1] is None]

    total = len(passed) + len(failed)
    if not failed:
        print(f"{BOLD}{GREEN}=== ALL {total} CHECKS PASSED ({len(skipped)} skipped) ==={RESET}\n")
    else:
        print(f"{BOLD}{RED}=== {len(failed)}/{total} CHECKS FAILED ==={RESET}")
        for label, _, detail in failed:
            print(f"  {RED}✗ {label}: {detail}{RESET}")
        print()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

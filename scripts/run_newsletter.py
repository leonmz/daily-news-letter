#!/usr/bin/env python3
"""CLI entry point for the daily market newsletter.

Usage:
    python scripts/run_newsletter.py              # Generate digest and send via Telegram
    python scripts/run_newsletter.py --schedule   # Run on schedule (10AM PT daily)
    python scripts/run_newsletter.py --bot        # Run Telegram bot (commands + schedule)
    python scripts/run_newsletter.py --test       # Dry run with mock data
    python scripts/run_newsletter.py --deep-only TICKER  # Test deep analysis on one ticker
    python scripts/run_newsletter.py --limit 5    # Limit number of movers
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from newsletter.pipeline import generate_digest
from newsletter.formatter import send_telegram


def run_scheduled() -> None:
    """Run on a daily schedule at 10AM Pacific Time."""
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger

    scheduler = BlockingScheduler()

    trigger = CronTrigger(
        hour=10,
        minute=0,
        timezone="America/Los_Angeles",
    )

    def job():
        digest = generate_digest()
        print("\n" + digest)
        send_telegram(digest)

    scheduler.add_job(job, trigger, id="daily_digest")
    print("Scheduler started — next run at 10:00 AM PT")
    print("Press Ctrl+C to stop\n")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        print("\nScheduler stopped")


def run_test() -> None:
    """Dry run with mock data (no API calls)."""
    from newsletter.digest import _fallback_summary

    mock_movers = {
        "gainers": [
            {"ticker": "NVDA", "name": "NVIDIA Corp", "price": 950.50,
             "change_pct": 8.5, "change_abs": 74.5, "volume": 85_000_000,
             "sector": "tech", "sector_raw": "Technology"},
            {"ticker": "AAPL", "name": "Apple Inc", "price": 228.30,
             "change_pct": 3.2, "change_abs": 7.08, "volume": 45_000_000,
             "sector": "tech", "sector_raw": "Technology"},
        ],
        "losers": [
            {"ticker": "XOM", "name": "Exxon Mobil", "price": 105.20,
             "change_pct": -3.2, "change_abs": -3.48, "volume": 22_000_000,
             "sector": "energy", "sector_raw": "Energy"},
        ],
    }
    mock_news: dict = {t: [] for t in ["NVDA", "AAPL", "XOM"]}

    print("\nTEST MODE — using mock data\n")
    digest = _fallback_summary(mock_movers, mock_news)
    header = f"📊 **Daily Market Digest** — {datetime.now().strftime('%B %d, %Y')} (TEST)\n\n"
    print(header + digest)


def run_deep_only(ticker: str) -> None:
    """Run deep analysis on a single ticker (for testing)."""
    from newsletter.config import DEEP_ANALYSIS_TIMEOUT
    from newsletter.deep_analysis import (
        run_deep_analysis,
        format_deep_analysis_section,
        TRADINGAGENTS_AVAILABLE,
    )
    from newsletter.market_data import get_last_trading_day, is_market_open

    if not TRADINGAGENTS_AVAILABLE:
        print("ERROR: TradingAgents is not installed.")
        sys.exit(1)

    trade_date = (
        datetime.now().strftime("%Y-%m-%d") if is_market_open()
        else get_last_trading_day()
    )

    print(f"\nDeep Analysis: {ticker} on {trade_date}")
    print("=" * 50)

    result = run_deep_analysis(ticker, trade_date, timeout=DEEP_ANALYSIS_TIMEOUT)
    if result:
        print(f"\nDecision: {result['decision']}")
        print("\n--- Telegram preview ---")
        print(format_deep_analysis_section([result]))
    else:
        print("Analysis failed. Check logs above for details.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Daily Market Newsletter")
    parser.add_argument("--schedule", action="store_true", help="Run on daily schedule (10AM PT)")
    parser.add_argument("--bot", action="store_true", help="Run Telegram bot (commands + daily schedule)")
    parser.add_argument("--test", action="store_true", help="Dry run with mock data")
    parser.add_argument("--deep-only", metavar="TICKER", help="Run deep analysis on a single ticker")
    parser.add_argument("--limit", type=int, default=10, help="Number of movers (default: 10)")
    args = parser.parse_args()

    if args.deep_only:
        run_deep_only(args.deep_only.upper())
    elif args.test:
        run_test()
    elif args.bot:
        from bot.telegram import run_bot
        run_bot()
    elif args.schedule:
        run_scheduled()
    else:
        digest = generate_digest(args.limit)
        print("\n" + digest)
        send_telegram(digest)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""CLI: Compare BS theoretical LEAP prices vs real historical market data (Databento).

Usage:
    # Sample 12 monthly dates in 2024
    python scripts/calibrate_bs.py --ticker SPY --start 2024-01-01 --end 2024-12-31

    # Specific dates
    python scripts/calibrate_bs.py --ticker SPY --dates 2024-01-15,2024-06-20,2024-12-15

    # Show individual data points
    python scripts/calibrate_bs.py --ticker SPY --start 2024-01-01 --end 2024-06-30 --verbose

    # Export to CSV
    python scripts/calibrate_bs.py --ticker SPY --start 2024-01-01 --end 2024-12-31 --csv calibration.csv

Requires: DATABENTO_API_KEY in .env
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

import pandas as pd


def _generate_monthly_dates(start: str, end: str) -> list[str]:
    """Generate ~monthly sample dates (3rd Wednesday of each month) within range."""
    dates = pd.date_range(start=start, end=end, freq="WOM-3WED")
    return [d.strftime("%Y-%m-%d") for d in dates]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Calibrate BS pricing against real Databento option data"
    )
    parser.add_argument("--ticker", default="SPY", help="Ticker symbol (default: SPY)")
    parser.add_argument("--start", help="Start date (YYYY-MM-DD), generates monthly samples")
    parser.add_argument("--end", help="End date (YYYY-MM-DD)")
    parser.add_argument("--dates", help="Comma-separated specific dates to calibrate")
    parser.add_argument("--delta", type=float, default=0.80, help="Target delta (default: 0.80)")
    parser.add_argument("--min-dte", type=int, default=90, help="Min days to expiry (default: 90)")
    parser.add_argument("--max-dte", type=int, default=270, help="Max days to expiry (default: 270)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Print individual data points")
    parser.add_argument("--csv", help="Export full results to CSV")

    args = parser.parse_args()

    api_key = os.getenv("DATABENTO_API_KEY", "")
    if not api_key:
        print("Error: DATABENTO_API_KEY not set in .env")
        print("Sign up at https://databento.com (free $125 credits)")
        sys.exit(1)

    if args.dates:
        dates = [d.strip() for d in args.dates.split(",")]
    elif args.start and args.end:
        dates = _generate_monthly_dates(args.start, args.end)
        if not dates:
            print(f"No valid dates in range {args.start} to {args.end}")
            sys.exit(1)
        print(f"Sampling {len(dates)} dates: {dates[0]} ... {dates[-1]}")
    else:
        print("Error: provide --start/--end or --dates")
        sys.exit(1)

    from backtest.calibration import BSCalibrator

    calibrator = BSCalibrator(databento_api_key=api_key)

    report = asyncio.run(calibrator.calibrate(
        ticker=args.ticker,
        dates=dates,
        delta_target=args.delta,
        expiry_months_min=args.min_dte // 30,
        expiry_months_max=args.max_dte // 30,
    ))

    report.print_summary()

    if args.verbose and report.points:
        df = report.to_dataframe()
        print(df.to_string(index=False))

    if args.csv and report.points:
        df = report.to_dataframe()
        df.to_csv(args.csv, index=False)
        print(f"Exported {len(df)} rows to {args.csv}")

    if not report.points:
        print("No calibration data — check API key and date range (OPRA data starts 2013-04)")


if __name__ == "__main__":
    main()

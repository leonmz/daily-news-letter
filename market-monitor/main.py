#!/usr/bin/env python3
"""market-monitor — CLI entry point.

Usage:
    python main.py --once       # fetch a snapshot now and email it (one-off)
    python main.py --baseline   # set today's baseline now and email it
    python main.py --schedule   # run the scheduler (6:30 PT baseline + 5-min monitor)
    python main.py --test       # offline: render mock emails and print them (no network/SMTP)
    python main.py --once --no-send   # print only, do not send
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


def _print_email(subject: str, html: str, text: str) -> None:
    print("=" * 64)
    print("SUBJECT:", subject)
    print("=" * 64)
    print(text)


def run_test() -> None:
    """Offline dry run with synthetic data — no network, no SMTP."""
    from monitor.alerts import Alert
    from monitor.formatter import render
    from monitor.moving_averages import MAComparison, MALevel
    from monitor.snapshot import Reading, Snapshot

    spy_ma = MAComparison("SPY", 589.25, [
        MALevel(5, 585.10, 0.71, True),
        MALevel(10, 580.40, 1.52, True),
        MALevel(50, 560.20, 5.19, True),
        MALevel(200, 545.80, 7.96, True),
    ])
    qqq_ma = MAComparison("QQQ", 498.50, [
        MALevel(5, 500.10, -0.32, False),
        MALevel(10, 495.40, 0.63, True),
        MALevel(50, 470.20, 6.02, True),
        MALevel(200, 455.80, 9.37, True),
    ])
    base = Snapshot("2026-06-08T06:30", "2026-06-08", [
        Reading("SPY", 589.25, spy_ma),
        Reading("QQQ", 498.50, qqq_ma),
        Reading("^VIX", 14.20, None),
        Reading("^VXN", 17.85, None),
    ])
    print("\nTEST MODE — baseline email\n")
    _print_email(*render(base, kind="baseline", threshold=1.0))

    alerts = [
        Alert("SPY", 589.25, 589.25, 595.90, 1.13, 1.13),
        Alert("^VIX", 14.20, 14.20, 14.95, 5.28, 5.28),
    ]
    moved = Snapshot("2026-06-08T07:15", "2026-06-08", [
        Reading("SPY", 595.90, spy_ma),
        Reading("QQQ", 498.50, qqq_ma),
        Reading("^VIX", 14.95, None),
        Reading("^VXN", 17.85, None),
    ])
    print("\nTEST MODE — alert email\n")
    _print_email(*render(moved, kind="alert", alerts=alerts, threshold=1.0))


def main() -> None:
    parser = argparse.ArgumentParser(description="market-monitor")
    parser.add_argument("--once", action="store_true", help="Fetch + email a snapshot now")
    parser.add_argument("--baseline", action="store_true", help="Set today's baseline now + email")
    parser.add_argument("--schedule", action="store_true", help="Run the scheduler")
    parser.add_argument("--test", action="store_true", help="Offline mock render (no network/SMTP)")
    parser.add_argument("--no-send", action="store_true", help="Print only; do not send email")
    args = parser.parse_args()

    if args.test:
        run_test()
        return

    if args.schedule:
        from monitor.runner import run_schedule
        run_schedule()
        return

    if args.baseline:
        from monitor.runner import establish_baseline
        establish_baseline(force=True, send=not args.no_send)
        return

    # default + --once: fetch and email a one-off snapshot
    from monitor import config
    from monitor.formatter import render
    from monitor.indicators import fetch_snapshot

    snap = fetch_snapshot()
    subject, html, text = render(snap, kind="refresh", threshold=config.ALERT_THRESHOLD_PCT)
    _print_email(subject, html, text)
    if not args.no_send:
        from monitor.runner import _send
        _send(subject, html, text)


if __name__ == "__main__":
    main()

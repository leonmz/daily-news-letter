"""Orchestration: establish the daily baseline, run the 5-minute monitor tick."""

from __future__ import annotations

from datetime import datetime

from monitor import config
from monitor.alerts import Alert, evaluate
from monitor.calendar_utils import ET, is_market_open, is_trading_day
from monitor.formatter import render
from monitor.indicators import fetch_snapshot
from monitor.snapshot import Snapshot
from monitor.state import load_state, save_state


def _send(subject: str, html: str, text: str) -> bool:
    from monitor.email_send import send_email

    return send_email(
        subject, html, text,
        host=config.EMAIL_HOST, port=config.EMAIL_PORT,
        user=config.EMAIL_USER, password=config.EMAIL_PASSWORD,
        sender=config.EMAIL_FROM, recipient=config.EMAIL_TO,
    )


def establish_baseline(*, force: bool = False, send: bool = True) -> Snapshot | None:
    """Fetch a snapshot, store it as today's baseline, and email it.

    With ``force=False`` (the scheduled path) it no-ops on non-trading days.
    """
    if not force and not is_trading_day(datetime.now(ET)):
        print("[runner] not a trading day — skipping baseline")
        return None

    snap = fetch_snapshot()
    if not snap.readings:
        print("[runner] no data fetched — baseline skipped")
        return None

    save_state(config.STATE_PATH, {"date": snap.date, "baseline": snap.prices(), "refs": snap.prices()})

    subject, html, text = render(snap, kind="baseline", threshold=config.ALERT_THRESHOLD_PCT)
    print(f"[runner] baseline @ {snap.timestamp} — {len(snap.readings)} instruments")
    if send:
        _send(subject, html, text)
    return snap


def check_and_alert(*, send: bool = True) -> list[Alert]:
    """One monitoring tick: alert if any instrument moved > threshold vs baseline."""
    if not is_market_open():
        return []

    state = load_state(config.STATE_PATH)
    snap = fetch_snapshot()
    if not snap.readings:
        return []

    # No baseline yet today (e.g. the monitor started after the open) → set it now.
    if state.get("date") != snap.date or not state.get("baseline"):
        establish_baseline(force=True, send=send)
        return []

    alerts, new_refs = evaluate(
        state.get("refs", {}), snap.prices(),
        config.ALERT_THRESHOLD_PCT, state.get("baseline", {}),
    )
    if alerts:
        state["refs"] = new_refs
        save_state(config.STATE_PATH, state)
        subject, html, text = render(
            snap, kind="alert", alerts=alerts, threshold=config.ALERT_THRESHOLD_PCT
        )
        moved = ", ".join(f"{a.symbol} {a.pct_from_baseline:+.2f}%" for a in alerts)
        print(f"[runner] ALERT: {moved}")
        if send:
            _send(subject, html, text)
    else:
        print(f"[runner] tick @ {snap.timestamp} — no >{config.ALERT_THRESHOLD_PCT}% moves")
    return alerts


def run_schedule() -> None:
    """Blocking scheduler: baseline at BASELINE_HOUR:MINUTE PT + every REFRESH_MINUTES."""
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger

    sched = BlockingScheduler(timezone=config.TIMEZONE)
    sched.add_job(
        lambda: establish_baseline(force=False, send=True),
        CronTrigger(
            hour=config.BASELINE_HOUR, minute=config.BASELINE_MINUTE,
            day_of_week="mon-fri", timezone=config.TIMEZONE,
        ),
        id="baseline",
    )
    sched.add_job(
        lambda: check_and_alert(send=True),
        IntervalTrigger(minutes=config.REFRESH_MINUTES),
        id="monitor",
    )
    print(
        f"[runner] scheduler started — baseline {config.BASELINE_HOUR:02d}:{config.BASELINE_MINUTE:02d} "
        f"{config.TIMEZONE}, monitor every {config.REFRESH_MINUTES}m (market hours only)"
    )
    print("Press Ctrl+C to stop")
    try:
        sched.start()
    except (KeyboardInterrupt, SystemExit):
        print("\n[runner] stopped")

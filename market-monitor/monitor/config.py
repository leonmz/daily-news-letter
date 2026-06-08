"""Configuration loaded from environment / ``.env``."""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


def _csv(name: str, default: str) -> list[str]:
    return [x.strip() for x in os.getenv(name, default).split(",") if x.strip()]


def _threshold_map(name: str, default: str) -> dict[str, float]:
    """Parse 'SYM:pct,SYM:pct' into {SYM: pct}. Empty/invalid items are skipped."""
    out: dict[str, float] = {}
    for item in os.getenv(name, default).split(","):
        if ":" not in item:
            continue
        sym, _, val = item.partition(":")
        sym, val = sym.strip(), val.strip()
        if sym and val:
            out[sym] = float(val)
    return out


# ── Email (Gmail SMTP) ────────────────────────────────────────
# Gmail needs an App Password (Account → Security → App passwords, 2FA on);
# a normal account password will be rejected by smtp.gmail.com.
EMAIL_HOST = os.getenv("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_USER = os.getenv("EMAIL_USER", "")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "")
EMAIL_FROM = os.getenv("EMAIL_FROM", "") or EMAIL_USER
EMAIL_TO = os.getenv("EMAIL_TO", "")

# ── Instruments ───────────────────────────────────────────────
EQUITY_TICKERS = [t.upper() for t in _csv("EQUITY_TICKERS", "SPY,QQQ")]
VOL_TICKERS = _csv("VOL_TICKERS", "^VIX,^VXN")
SMA_PERIODS = [int(p) for p in _csv("SMA_PERIODS", "5,10,50,200")]

# ── Schedule / monitoring (Pacific) ───────────────────────────
TIMEZONE = os.getenv("MONITOR_TZ", "America/Los_Angeles")
BASELINE_HOUR = int(os.getenv("BASELINE_HOUR", "6"))      # 6:30 AM PT = ET 9:30 open
BASELINE_MINUTE = int(os.getenv("BASELINE_MINUTE", "30"))
REFRESH_MINUTES = int(os.getenv("REFRESH_MINUTES", "5"))
ALERT_THRESHOLD_PCT = float(os.getenv("ALERT_THRESHOLD_PCT", "1.0"))
# Per-symbol overrides. Volatility indices swing several percent a day, so a 1%
# threshold there is pure noise; default VIX/VXN to 10% ("balanced" sensitivity).
ALERT_THRESHOLDS = _threshold_map("ALERT_THRESHOLDS", "^VIX:10,^VXN:10")

# ── Data / state ──────────────────────────────────────────────
HISTORY_PERIOD = os.getenv("HISTORY_PERIOD", "2y")
STATE_PATH = os.getenv("STATE_PATH", "monitor_state.json")

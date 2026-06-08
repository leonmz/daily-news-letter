# market-monitor

Intraday market monitor that emails you SPY/QQQ moving-average structure plus
volatility (VIX/VXN), once at the open and then only when something moves.

- **Baseline email** at market open (ET 9:30 = **PT 6:30 AM**) every trading day.
- **Every 5 minutes** during market hours, re-check; email an **alert** only when
  SPY, QQQ, VIX, or VXN moves **more than 1%** versus that morning's baseline.
- References **ratchet** after each alert, so you get one email per ~1% leg —
  not one every five minutes while a level hovers past the threshold.

Built in the style of the [daily-news-letter](https://github.com/leonmz/daily-news-letter)
digest (emoji sections, per-ticker SMA lines with 🟢/🔴 and signed %).

## What it tracks

| Group | Symbols | Shown |
|-------|---------|-------|
| Equity | `SPY`, `QQQ` | price vs **SMA 5 / 10 / 50 / 200** (% deviation, above/below) |
| Volatility | `^VIX`, `^VXN` | index level (VIX↔S&P 500, VXN↔Nasdaq-100) |

## Quick start

```bash
# 1. Install
pip install -r requirements.txt

# 2. Configure (copy + edit — never commit .env)
cp .env.example .env
#   set EMAIL_PASSWORD to a Gmail App Password (see note below)

# 3. Offline sanity check — renders mock baseline + alert emails, no network/SMTP
python main.py --test

# 4. Send a one-off snapshot now
python main.py --once

# 5. Run the scheduler (baseline 6:30 AM PT + 5-min monitor, market hours only)
python main.py --schedule
```

### ⚠️ Gmail App Password required

`smtp.gmail.com` rejects normal account passwords. Turn on **2-Step
Verification**, then create a 16-character **App Password** at
<https://myaccount.google.com/apppasswords> and put it in `.env` as
`EMAIL_PASSWORD`. Prefer port `587` (STARTTLS, default) or `465` (SSL).

## CLI

| Command | What it does |
|---------|--------------|
| `python main.py --test` | Offline: render mock baseline + alert emails and print them |
| `python main.py --once` | Fetch a live snapshot now and email it |
| `python main.py --baseline` | Set today's baseline now and email it |
| `python main.py --schedule` | Run the scheduler (baseline + 5-min monitor) |
| `--no-send` | With `--once`/`--baseline`: print only, don't send |

## Architecture

```
market-monitor/
├── monitor/
│   ├── config.py          # env / .env loading
│   ├── calendar_utils.py  # NYSE trading-day + market-open (ET) checks
│   ├── moving_averages.py # compute price vs N SMAs (pure)
│   ├── indicators.py      # yfinance → Snapshot (SPY/QQQ SMAs + VIX/VXN)
│   ├── snapshot.py        # Snapshot / Reading dataclasses
│   ├── state.py           # JSON baseline + ratcheting references
│   ├── alerts.py          # >threshold detection + ratchet (pure)
│   ├── formatter.py       # Snapshot/alerts → (subject, html, text)
│   ├── email_send.py      # SMTP (Gmail) multipart send
│   └── runner.py          # establish_baseline / check_and_alert / run_schedule
├── main.py                # CLI
└── tests/                 # offline unit tests (no live API / SMTP)
```

### How a day flows

```
6:30 AM PT  establish_baseline()  → fetch snapshot → save baseline+refs → email
every 5 min check_and_alert()     → if market open:
                                      fetch snapshot
                                      evaluate(refs, current, 1%) vs baseline
                                      if any move > 1%: ratchet refs, email alert
```

State lives in `monitor_state.json` (gitignored): `{date, baseline{}, refs{}}`.
On a new day (or first tick after a restart) the monitor re-establishes the
baseline automatically.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest -v
```

All unit tests are offline — synthetic OHLCV and dataclasses, no yfinance or
SMTP calls.

## Configuration

Every knob is an env var (see `.env.example`): instruments (`EQUITY_TICKERS`,
`VOL_TICKERS`), `SMA_PERIODS`, schedule (`BASELINE_HOUR/MINUTE`,
`REFRESH_MINUTES`, `MONITOR_TZ`), `ALERT_THRESHOLD_PCT`, and `HISTORY_PERIOD`.

> Note: VIX/VXN are themselves volatile, so a 1% threshold will alert on them
> fairly often. Raise `ALERT_THRESHOLD_PCT` if that's too chatty.

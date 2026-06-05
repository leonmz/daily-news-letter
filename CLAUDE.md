# Market Backtest + Data Provider — Claude Guidelines

> The daily-newsletter / Telegram-bot application (and its email delivery) was
> removed. What remains is a **backtesting library** (`backtest/`) and a
> **market-data provider adapter layer** (`data/`). Keep this file in sync as the
> project evolves.

## Workflow Rules

- For any new feature / product change, update the relevant design doc
  (`README.md` or the package `README.md`) first and ask the user to review
  before starting implementation.
- Before submitting a PR:
  1. Propose a minimal set of local test cases (unit-level, no live API calls) to the user. Keep tests focused and token-efficient — mock data, direct function calls, assert expected output.
  2. Ask the user to sign off on the test cases before running them.
  3. After sign-off, run a sub agent to iterate until all test cases pass. No user input needed during iteration.
  4. Then open a sub agent to review the PR diff and iterate two times automatically. No user input needed during review cycles. Each review cycle must raise at most 2 major concerns.
  5. Run `codex review --base main` from the worktree directory. Fix any P1/P2 issues it finds before merging.
  6. Before merging the PR, always run a smoke test.
- Always update the design docs (`README.md`, `*/README.md`) once coding is implemented to keep docs in sync with the actual architecture.

## Data Provider Layer (`data/`)

Phase 0: Provider adapter layer — rock-solid data foundation.

**Architecture:**
```
data/
├── providers/
│   ├── base.py          # Protocol definitions (MarketData, News, Options, Macro, Fundamentals, Historical)
│   ├── alpaca.py        # IEX real-time quotes, Benzinga news, screener movers (free tier)
│   ├── finnhub.py       # Fundamentals, earnings calendar, analyst ratings, company news
│   ├── yfinance_provider.py  # Delayed quotes, historical OHLCV, options chain (BS Greeks)
│   ├── fred.py          # FRED macro indicators, 9-maturity yield curve
│   ├── cboe.py          # ★ CBOE pre-computed Greeks — delta/gamma/theta/vega direct from exchange
│   ├── orchestrator.py  # Fallback routing + SQLite caching + find_by_delta()
│   └── config.py        # Loads API keys from .env
├── models/              # StockQuote, OptionsSnapshot, NewsArticle, MacroIndicator, YieldCurve, AlertEvent
├── storage/cache.py     # SQLite cache with TTL, type-safe dataclass round-tripping
└── utils/greeks.py      # Black-Scholes (backup for yfinance chain; CBOE is primary for Greeks)
```

**Key design decisions:**
- **CBOE for Greeks** — exchange pre-computes delta/gamma/theta/vega for every listed option. One HTTP call, zero math. No API key. This replaced a 200-line BS/Brent/BAW self-calculation approach.
- **find_by_delta(ticker, 0.85)** — orchestrator delegates to CBOEProvider, searches across top N expirations with liquidity gating (spread + OI).
- **Fallback pattern** — orchestrator tries providers in registration order; first success wins, result cached.
- **Cache TTLs** — quotes 5min, news 15min, options 30min, fundamentals 24hr, macro 1hr.

**API keys required:** `ALPACA_API_KEY/SECRET`, `FINNHUB_API_KEY`, `FRED_API_KEY` (yfinance + CBOE need none).

**Diagnostic:** `python scripts/diagnose.py` — 20 checks across all providers + cross-validation.

## Backtesting (`backtest/`)

SMA-timing backtest engine + strategies. CLI entry point: `python scripts/run_backtest.py`.
Ad-hoc studies live in `scripts/backtest_*.py`. See `backtest/README.md` for full docs.

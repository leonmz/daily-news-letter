# Market Backtest + Data Provider

Two standalone libraries:

- **`backtest/`** — SMA-timing backtesting engine + strategies.
- **`data/`** — market-data provider adapter layer (Alpaca, Finnhub, FRED, yfinance, CBOE) with fallback routing + SQLite caching.

> Note: the former daily-newsletter / Telegram-bot application was removed; this
> repo is now just the backtesting and data-provider libraries.

## Quick start

```bash
pip install -r requirements.txt
cp .env.example .env   # add provider API keys (all optional; yfinance + CBOE need none)
```

## Architecture

```
daily-news-letter/
├── backtest/   # SMA timing backtest engine + strategies
├── data/       # Provider adapter layer (quotes, news, options, macro, fundamentals)
├── scripts/
│   ├── run_backtest.py    # Backtesting CLI entry point
│   ├── diagnose.py        # Provider-layer diagnostics (20 checks)
│   └── backtest_*.py      # Ad-hoc backtest studies
└── tests/
    ├── test_backtest/
    └── test_providers/
```

## Backtesting

```bash
python scripts/run_backtest.py --underlying SPY --signal basic_ma --sma 250
python scripts/run_backtest.py --compare-sma QQQ
python scripts/run_backtest.py --underlying TSLA --plot
```

See [`backtest/README.md`](backtest/README.md) for full docs.

## Data providers

```bash
python scripts/diagnose.py   # validate provider connectivity + cross-check
```

| Provider | API key | What it does |
|----------|---------|--------------|
| **Alpaca** | `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` | IEX real-time quotes, Benzinga news, movers |
| **Finnhub** | `FINNHUB_API_KEY` | Fundamentals, earnings, analyst ratings |
| **FRED** | `FRED_API_KEY` | Macro indicators, yield curve |
| **yfinance** | none | Delayed quotes, historical OHLCV, options |
| **CBOE** | none | Exchange pre-computed option Greeks |

See [`data/README.md`](data/README.md) for the provider layer design.

# data/

Provider adapter layer — rock-solid data foundation (Phase 0).

## Architecture

```
data/
├── providers/
│   ├── base.py              # Protocol definitions (MarketData, News, Options, Macro)
│   ├── alpaca.py            # IEX real-time quotes, Benzinga news, screener movers
│   ├── finnhub.py           # Fundamentals, earnings calendar, analyst ratings
│   ├── yfinance_provider.py # Delayed quotes, historical OHLCV, options chain
│   ├── fred.py              # FRED macro indicators, 9-maturity yield curve
│   ├── cboe.py              # CBOE pre-computed Greeks (delta/gamma/theta/vega)
│   └── orchestrator.py      # Fallback routing + SQLite caching + find_by_delta()
├── models/                  # StockQuote, OptionsSnapshot, NewsArticle, MacroIndicator
├── storage/cache.py         # SQLite cache with TTL, type-safe dataclass round-tripping
└── utils/greeks.py          # Black-Scholes (backup; CBOE is primary for Greeks)
```

## Key design decisions

- **CBOE for Greeks** — exchange pre-computes delta/gamma/theta/vega. No API key, one HTTP call.
- **`find_by_delta(ticker, 0.85)`** — orchestrator searches across expirations with liquidity gating
- **Fallback pattern** — orchestrator tries providers in registration order; first success wins, result cached
- **Cache TTLs** — quotes 5min, news 15min, options 30min, fundamentals 24hr, macro 1hr

## Diagnostics

```bash
python scripts/diagnose.py
```

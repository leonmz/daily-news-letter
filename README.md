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

## Robinhood MCP (read-only)

[`robinhood-mcp`](https://github.com/verygoodplugins/robinhood-mcp) is a **read-only** MCP server for Robinhood portfolio research (positions, history, quotes via the unofficial `robin_stocks` API). It **cannot place trades**.

**Setup (run locally — not in a shared/cloud container):**

1. Install [`uv`](https://docs.astral.sh/uv/) (provides `uvx`).
2. Create `.mcp.json` in the repo root — no secrets, credentials come from env vars:
   ```json
   {
     "mcpServers": {
       "robinhood": {
         "command": "uvx",
         "args": ["robinhood-mcp"],
         "env": {
           "ROBINHOOD_USERNAME": "${ROBINHOOD_USERNAME}",
           "ROBINHOOD_PASSWORD": "${ROBINHOOD_PASSWORD}"
         }
       }
     }
   }
   ```
   (Equivalent CLI: `claude mcp add robinhood -- uvx robinhood-mcp`, then set the env vars.)
3. Export your Robinhood credentials in your shell — **never commit them**:
   ```bash
   export ROBINHOOD_USERNAME="you@example.com"
   export ROBINHOOD_PASSWORD="your_password"
   ```
4. Run Claude Code in this repo and **approve** the `robinhood` server when prompted. On first login (no TOTP), approve the push notification in the Robinhood app once; the session caches for days/weeks.

For non-interactive MFA, add `"ROBINHOOD_TOTP_SECRET": "${ROBINHOOD_TOTP_SECRET}"` to the `env` block and export that base32 secret too.

> ⚠️ Unofficial API — small account-flagging risk; read-only only. For **real trade execution**, use Robinhood's official [Agentic Trading](https://robinhood.com/us/en/support/articles/agentic-trading-overview/) MCP instead (separate in-app setup with a dedicated funded account) — not this config.

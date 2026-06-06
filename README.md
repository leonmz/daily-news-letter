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

## Robinhood MCP

Two options — very different in capability and risk.

### Official Agentic Trading MCP — places real trades ⚠️

Robinhood's official remote MCP lets an agent **execute real equity trades**. It's an
interactive OAuth you set up yourself on a **desktop** browser (not a repo file, and
not inside a shared/cloud container):

```bash
claude mcp add robinhood-trading --transport http https://agent.robinhood.com/mcp/trading
```

Then run `/mcp` in Claude Code → select `robinhood-trading` → **authenticate**. The first
connection auto-opens onboarding for a **dedicated Agentic account** (separate from your
main portfolio; requires a primary individual account in good standing). Claude Desktop:
Settings → Connectors → Add custom connector → same URL.

- **Verify the URL inside the Robinhood app/newsroom before authenticating** — you are granting trade access.
- The agent can only touch the Agentic account's funds; fund only what you're willing to risk.
- Safety: per-trade push notifications, live activity/P&L, one-tap disconnect.

### Read-only research MCP — no trading

[`robinhood-mcp`](https://github.com/verygoodplugins/robinhood-mcp) (community, `uvx`)
exposes **read-only** portfolio data (positions/history/quotes via the unofficial
`robin_stocks` API). Create `.mcp.json` in the repo root:

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

Export `ROBINHOOD_USERNAME` / `ROBINHOOD_PASSWORD` in your shell (**never commit**);
unofficial API, small account-flagging risk.

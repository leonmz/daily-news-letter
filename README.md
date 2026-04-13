# Daily Market News Bot

Automated daily digest of top 10 market movers, grouped by sector with AI-analyzed drivers.

## Quick start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Set up API keys
cp .env.example .env
# Edit .env with your keys

# 3. Test with mock data (no API keys needed)
python main.py --test

# 4. Run once (needs at least FMP key)
python main.py

# 5. Run Telegram bot (commands + daily 10AM PT schedule)
python main.py --bot
```

## Architecture

```
daily-news-letter/
├── newsletter/     # Core pipeline (config, market data, news, LLM, formatter)
├── bot/            # Telegram bot command handlers + scheduler
├── backtest/       # SMA timing backtesting engine
├── data/           # Provider adapter layer (Phase 0, not yet wired to pipeline)
├── scripts/
│   ├── run_newsletter.py  # Newsletter CLI entry point
│   └── run_backtest.py    # Backtesting CLI entry point
├── tests/
│   ├── test_newsletter/
│   ├── test_backtest/
│   ├── test_bot/
│   └── test_providers/
└── main.py         # Thin shim → scripts/run_newsletter.py (backwards compat)
```

### Data flow

```
Market Data (FMP/yfinance)        ─┐
News (Marketaux/yfinance/Google)  ─┤→ newsletter/pipeline.py → LLM → formatter → Telegram
User watchlist (config.py)        ─┘
```

## API keys

| API | Free tier | What it does |
|-----|-----------|--------------|
| **FMP** | 250 req/day | Top movers + sector data |
| **Marketaux** | 100 req/day | News by ticker + sentiment (optional) |
| **Gemini** | Free tier | LLM analysis of catalysts |
| **Telegram** | Free | Message delivery |

Minimum to run: **no keys required** (yfinance fallback for data, Google News for news, template for analysis).

## Bot commands

| Command | Description |
|---------|-------------|
| `/digest` | Generate full market digest on-demand |
| `/movers` | Quick top movers summary (no LLM) |
| `/watchlist` | Show / add / remove watchlist tickers |
| `/help` | List available commands |

## Backtesting

```bash
python scripts/run_backtest.py --underlying SPY --signal basic_ma --sma 250
python scripts/run_backtest.py --compare-sma QQQ
python scripts/run_backtest.py --underlying TSLA --plot
```

See [`backtest/README.md`](backtest/README.md) for full docs.

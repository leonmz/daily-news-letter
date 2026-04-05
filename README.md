# Daily Market News Bot 📊

Automated daily digest of top 10 market movers, grouped by sector with AI-analyzed drivers.

## Quick start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Set up API keys
cp .env.example .env
# Edit .env with your keys (see below)

# 3. Test with mock data (no API keys needed)
python main.py --test

# 4. Run once (needs at least FMP key)
python main.py

# 5. Run on schedule (10AM PT daily)
python main.py --schedule
```

## API keys you need

| API | Free tier | What it does | Get key |
|-----|-----------|--------------|---------|
| **FMP** | 250 req/day | Top movers + sector data | [financialmodelingprep.com](https://site.financialmodelingprep.com/developer/docs) |
| **Marketaux** | 100 req/day | News by ticker + sentiment (optional) | [marketaux.com](https://www.marketaux.com/) |
| **Gemini** | Free tier | LLM analysis of catalysts | [aistudio.google.com](https://aistudio.google.com/apikey) |
| **Telegram** | Free | Message delivery | [@BotFather](https://t.me/BotFather) |

Minimum to run: **No keys required** (uses yfinance fallback for market data, Google News RSS for news, template for analysis). Add keys for better quality.

## Architecture

```
Market Data (FMP/yfinance)           →  ┐
News (Marketaux/Google News RSS)     →  ├→ Aggregator → Gemini API → Formatter → Telegram
User Config (V2)                     →  ┘
```

## Files

- `config.py` — API keys, sector mappings
- `market_data.py` — Top movers fetcher (FMP + yfinance)
- `news_fetcher.py` — News fetcher (Marketaux + Google News RSS)
- `llm_analyzer.py` — Gemini API integration for digest generation
- `main.py` — Pipeline runner + scheduler

## Roadmap

- [x] MVP: daily 10AM digest
- [ ] V2: sector watchlist + breaking news alerts
- [ ] V2: individual stock follow + related news

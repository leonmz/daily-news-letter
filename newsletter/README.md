# newsletter/

Core newsletter pipeline — config, data fetching, LLM analysis, formatting.

## Key files

| File | Purpose |
|------|---------|
| `config.py` | All config/env vars (API keys, thresholds, watchlist) |
| `market_data.py` | Top movers, blue chips, watchlist via FMP + yfinance |
| `news.py` | News fetching: Marketaux → yfinance → Google RSS |
| `digest.py` | LLM analysis (Gemini/Claude) → structured digest |
| `deep_analysis.py` | Optional TradingAgents deep analysis per ticker |
| `formatter.py` | Telegram HTML formatting + `send_telegram()` |
| `pipeline.py` | Full pipeline: `generate_digest()` wires everything together |

## Usage

```python
from newsletter.pipeline import generate_digest
from newsletter.formatter import send_telegram

digest = generate_digest(limit=10)
send_telegram(digest)
```

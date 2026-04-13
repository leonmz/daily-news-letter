# bot/

Telegram bot — command handlers, inline buttons, daily schedule.

## Key files

| File | Purpose |
|------|---------|
| `telegram.py` | All command handlers (`/digest`, `/movers`, `/watchlist`), scheduled job, `run_bot()` |

## Usage

```python
from bot.telegram import run_bot
run_bot()
```

Or via CLI:

```bash
python scripts/run_newsletter.py --bot
```

## Commands

| Command | Description |
|---------|-------------|
| `/digest` | Generate full market digest on demand |
| `/movers` | Quick top movers summary (no LLM) |
| `/watchlist` | Show / add / remove watchlist tickers |
| `/help` | Show available commands |

# Daily Market Newsletter — Claude Guidelines

## Workflow Rules

- For all product requirements, update `PLAN.md` before implementing.

## Active Features (New Branch per Feature)

### Branch: `feature/improve-news-coverage`
Improve news coverage:
- Expand news sources beyond Marketaux and RSS
- Better ticker-to-article matching
- Increase coverage for tickers with no news found

### Branch: `feature/telegram-receive-messages`
Receive messages from Telegram bot:
- Handle incoming user commands via Telegram webhook or polling
- Support on-demand digest requests (e.g., `/digest`, `/movers`)
- Respond to user queries through the bot

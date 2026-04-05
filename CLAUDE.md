# Daily Market Newsletter — Claude Guidelines

## Workflow Rules

- For all product requirements, update `PLAN.md` before implementing.
- Before submitting a PR:
  1. Propose a minimal set of local test cases (unit-level, no live API calls) to the user. Keep tests focused and token-efficient — mock data, direct function calls, assert expected output.
  2. Ask the user to sign off on the test cases before running them.
  3. After sign-off, run a sub agent to iterate until all test cases pass. No user input needed during iteration.
  4. Then open a sub agent to review the PR diff and iterate two times automatically. No user input needed during review cycles.
- Always update the plan/design doc (e.g. `daily-news-bot-plan.md`, `README.md`) once coding is implemented to keep docs in sync with the actual architecture.
- For any new feature request, update the plan doc first and ask the user to review before starting implementation.

## Active Features (New Branch per Feature)

### ~~Branch: `feature/improve-news-coverage`~~ (DONE — merged in PR #2)
Simplified to 2-tier: Marketaux (optional) + Google News RSS (primary).
Dropped RSS — Google News per-ticker search achieves 10/10 coverage.

### Branch: `feature/telegram-receive-messages`
Receive messages from Telegram bot:
- Handle incoming user commands via Telegram webhook or polling
- Support on-demand digest requests (e.g., `/digest`, `/movers`)
- Respond to user queries through the bot

# Daily Market Newsletter — Claude Guidelines

## Workflow Rules

- For all product requirements, update `PLAN.md` before implementing.
- Before submitting a PR:
  1. Propose a minimal set of local test cases (unit-level, no live API calls) to the user. Keep tests focused and token-efficient — mock data, direct function calls, assert expected output.
  2. Ask the user to sign off on the test cases before running them.
  3. After sign-off, run a sub agent to iterate until all test cases pass. No user input needed during iteration.
  4. Then open a sub agent to review the PR diff and iterate two times automatically. No user input needed during review cycles. Each review cycle must raise at most 2 major concerns.
  5. Before merging the PR, always run a smoke test.
- Always update the plan/design doc (e.g. `daily-news-bot-plan.md`, `README.md`) once coding is implemented to keep docs in sync with the actual architecture.
- For any new feature request, update the plan doc first and ask the user to review before starting implementation.

## TradingAgents Integration Notes

- TradingAgents 的 `DEFAULT_CONFIG` 包含 `"backend_url": "https://api.openai.com/v1"`，这个 OpenAI 地址会被传给**所有** LLM provider（包括 Google/Anthropic），导致 404 错误。使用非 OpenAI provider 时，必须设置 `config["backend_url"] = None`。
- gemini-2.5-flash 跑完一次完整多 Agent 分析（4 分析师 + 辩论 + 风控）约需 10-15 分钟，超时设置建议 >= 900s。
- Deep analysis 默认关闭（`DEEP_ANALYSIS_ENABLED=false`），通过 `.env` 开启。
- `--deep-only TICKER` 可单独测试某只股票的深度分析，不触发完整 pipeline。

## Active Features (New Branch per Feature)

### ~~Branch: `feature/improve-news-coverage`~~ (DONE — merged in PR #2)
Simplified to 2-tier: Marketaux (optional) + Google News RSS (primary).
Dropped RSS — Google News per-ticker search achieves 10/10 coverage.

### Branch: `feature/telegram-receive-messages`
Receive messages from Telegram bot:
- Handle incoming user commands via Telegram webhook or polling
- Support on-demand digest requests (e.g., `/digest`, `/movers`)
- Respond to user queries through the bot

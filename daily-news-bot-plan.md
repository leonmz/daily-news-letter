# Daily Market News Bot — Project Plan

## 一句话描述

每天加州时间 10AM 自动推送 Top 10 Market Movers，按板块分组，附带驱动力分析和相关新闻。后续支持自定义 watchlist 和 breaking news 实时推送。

---

## 项目结构

```
/Users/leon/Documents/Projects/daily-news-letter/
├── config.py           # API keys + 板块映射 (GICS → 简称)
├── market_data.py      # 拉取 Top movers（FMP 主 / yfinance 备）
├── news_fetcher.py     # 拉取新闻（Marketaux 主 / RSS 备）
├── llm_analyzer.py     # Claude API 分析 + fallback 模板
├── main.py             # Pipeline 入口 + Scheduler + Telegram 推送
├── delivery.py         # 独立 Telegram 投递模块（可选）
├── requirements.txt
├── .env.example
└── .gitignore
```

---

## 技术栈

| 层 | 选型 | 备注 |
|---|---|---|
| 语言 | Python 3.11+ | |
| 市场数据 | Financial Modeling Prep (FMP) API | 免费 250 req/day，含 top gainers/losers + 板块 |
| 市场数据备选 | yfinance | 无需 key，但 Screener 不够稳定 |
| 新闻 | Google News RSS | 免费，按 ticker 搜索，无需 key |
| 新闻补充 | Marketaux API（可选） | 免费 100 req/day，自带 sentiment |
| LLM 分析 | Google Gemini API (gemini-2.5-flash) | 免费额度充裕，每天一次调用成本极低 |
| 定时调度 | APScheduler (CronTrigger) | 10AM PT, Mon-Fri |
| 推送 | Telegram Bot API | 免费，支持 Markdown 格式 |
| 配置 | python-dotenv + .env | |

---

## MVP：Daily Digest（Phase 1）

### 数据流

```
[FMP API] ──→ Top 5 Gainers + Top 5 Losers
                    │
                    ▼
[Marketaux API] ──→ 每个 ticker 拉新闻（可选，含 sentiment）
  + [Google News]   缺失的用 Google News RSS 按 ticker 搜索补全
                    │
                    ▼
[Gemini API] ──→ 按板块分组，识别每只股票的核心催化剂
                 (earnings / macro / product / analyst / M&A / regulatory)
                 输出 1-2 句 WHY 解释
                    │
                    ▼
[Telegram Bot] ──→ 推送格式化 digest 到你的 chat
```

### 输出示例

```
📊 Daily Market Digest — April 04, 2026

## Market summary
Tech led gains on strong earnings while energy lagged amid inventory builds...

## 🖥️ Tech
### ▲ NVDA (+8.50%) — Product launch
NVIDIA announced Blackwell Ultra GPU architecture targeting AI workloads.

### ▲ AAPL (+3.20%) — Product demand
Vision Pro 2 pre-orders exceeded analyst expectations.

## ⚡ Energy
### ▼ XOM (-3.20%) — Macro
Oil prices declined on higher-than-expected EIA inventory builds.

## 🏥 Healthcare
### ▼ PFE (-4.10%) — Clinical trial
Phase 3 danuglipron trial missed primary endpoint.
```

### API 用量估算（每日）

| API | 调用次数 | 免费额度 | 余量 |
|---|---|---|---|
| FMP: gainers | 1 | 250/day | 充裕 |
| FMP: losers | 1 | (同上) | |
| FMP: profile (补板块) | 1 | (同上) | |
| Marketaux: news | 2 (每次5 tickers) | 100/day | 充裕 |
| Claude: analysis | 1 (~2K tokens) | Pay-as-you-go | ~$0.01/天 |
| Telegram | 1-2 messages | 无限 | ∞ |

---

## V1.5：Improve Top Movers Accuracy

### 问题
当前 top movers 只抓 yfinance screener 的 day_gainers/day_losers，经常返回小盘股（如 AAOI、YSS），缺少大盘股的涨跌信息。用户也无法追踪自己持仓的表现��

### 新增功能

**1. 市场开盘时间校验**
- 运行时检查当前���间是否在 US 市场交易时段（ET 9:30-16:00，周一到周五）
- 如果盘前/盘后/周末运行，使用上一个交易日的数据而非实时数据
- 用 `zoneinfo` 或 `pytz` 做时区转换（ET），避免拉到空数据或盘前异常数据

**2. Top 10 大盘股涨跌**
- 额外拉取 Top 10 市值公司的当日涨跌（AAPL, MSFT, NVDA, AMZN, GOOG, META, TSLA, BRK-B, JPM, V）
- 通过 `yf.download(tickers, period="1d")` 批量获取，无需额外 API
- 在 digest 中新增 "Blue Chip Movers" 板块，展示大盘股当日表现
- 只展示涨跌幅 > 1% 的大盘股（过滤掉无聊的小波动）

**3. 用户自定义持仓 Watchlist**
- `.env` 中新增 `WATCHLIST=NVDA,TSLA,AAPL`（逗号分隔，最多 10 个）
- 通过 `yf.download()` 批量获取持仓的当日涨跌
- 在 digest 中新增 "Your Holdings" 板块
- 如果 watchlist ticker 已在 top movers 中，避免重复展示

### 数据流变更

```
[yfinance screen] ──→ Top 5 Gainers + Top 5 Losers (现有)
[yfinance download] ──→ Top 10 大盘股当日涨跌 (新增)
[yfinance download] ��─→ 用户 Watchlist 涨跌 (新增)
[市场时间校验] ──→ 决定用实时数据还是上一交易日数据
                    │
                    ▼
              合并所有 movers → News → LLM → Telegram
```

### 修改文件
- `config.py` — 新增 `WATCHLIST`、`TOP_BLUE_CHIPS` 配置
- `market_data.py` — 新增 `fetch_blue_chips()`、`fetch_watchlist()`、`is_market_open()`
- `main.py` — 合并三个来源的 movers

### API 用量影响
- yfinance `download()` 无 API 限制，不影响配额
- 新闻会多查几个 ticker（大盘股 + watchlist），Google News RSS 免费无限制

---

## V2：Watchlist + Breaking News（Phase 2）

### 新增功能

**1. 板块订阅**
- 用户通过 Telegram 命令配置：`/watch tech energy`、`/unwatch energy`
- 后台每 10-15 分钟 poll Marketaux + RSS
- 匹配到关注板块的突发新闻立即推送

**2. 个股关注**
- 命令：`/follow NVDA TSLA`、`/unfollow TSLA`
- 不仅精确匹配 ticker，还用 LLM 判断新闻是否"可能相关"
  - 供应链上下游（如 TSMC 新闻 → 影响 NVDA）
  - 竞对动态（如 AMD 发布新卡 → 影响 NVDA）
  - 监管政策（如 AI 出口管制 → 影响整个半导体板块）
- 这是 LLM 最大的增值点

### 新增组件

```
[User Config DB]     SQLite: 用户关注的板块 + 个股
        │
        ▼
[Streaming Monitor]  APScheduler interval job, 每 10-15 min
        │
        ├──→ [Marketaux] 按 watchlist tickers 拉新闻
        ├──→ [RSS feeds] 全量抓取 + 关键词过滤
        │
        ▼
[Relevance Filter]   LLM 判断新闻是否与关注的股票相关
        │
        ▼
[Alert Engine]       去重（已推送的不重复推）→ Telegram push
```

### API 用量注意

- Marketaux 免费 100 req/day，10 min 一次 × 9 小时 = ~54 次，够用但紧
- 如果 watchlist 很长，需要考虑：
  - 升级 Marketaux plan（$19/mo 起，1000 req/day）
  - 或者重度依赖 RSS + LLM 过滤
  - 或者切换到 Finnhub（免费 60 req/min，但新闻质量稍差）

---

## V3：可选增强（Phase 3）

| 功能 | 描述 | 复杂度 |
|---|---|---|
| 自定义新闻源 | `/addsource https://xyz.com/rss` 添加 RSS feed | 低 |
| 历史趋势 | 存每日 digest，周末生成 weekly recap | 中 |
| Email 投递 | 除 Telegram 外同时发邮件（SendGrid / SES） | 低 |
| Web dashboard | 简单 Streamlit 页面查看历史 digest | 中 |
| Multi-user | 从单用户扩展到多用户，迁移到 Postgres | 高 |

---

## GitHub 可参考的项目

| 项目 | 价值 | 链接 |
|---|---|---|
| rs-lin/Stock-News-Alert | Telegram + 股票新闻订阅，架构最接近 | github.com/rs-lin/Stock-News-Alert |
| Awaisali36/stock-analysis-telegram-bot | 完整 Telegram + 技术分析 + sentiment | github.com/Awaisali36/stock-analysis-telegram-bot |
| bauer-jan/stock-analysis-with-llm | Claude + AWS 做周度分析，prompt 可参考 | github.com/bauer-jan/stock-analysis-with-llm |
| TauricResearch/TradingAgents | LangGraph 多 agent 框架，over-kill 但设计值得看 | github.com/TauricResearch/TradingAgents |

---

## 当前进度

- [x] 项目结构搭建
- [x] `config.py` — API key 管理 + 板块映射
- [x] `market_data.py` — FMP top movers + yfinance fallback + 板块补全
- [x] `news_fetcher.py` — Marketaux + Google News RSS（已简化，移除 RSS）
- [x] `llm_analyzer.py` — Gemini ��析 + Claude fallback
- [x] `main.py` — 完整 pipeline + scheduler + Telegram + test mode
- [x] `.env.example` + `.gitignore` + `requirements.txt`
- [x] 注册 API keys + 创建 Telegram Bot
- [x] 端到端测试（10/10 tickers with news）
- [x] Docker 部署支持
- [x] V1.5: 改进 top movers（市场时间校验 + 大盘股 + watchlist）
- [x] Telegram bot: 接收命令 (/digest, /movers, /watchlist add/remove)
- [ ] V2 watchlist + breaking news

---

## 下一步

1. 注册三个 API key（FMP / Marketaux / Anthropic），5 分钟
2. 创建 Telegram Bot，拿到 token 和 chat_id，5 分钟
3. 填 `.env`，跑 `python main.py --test`，验证 mock 流程
4. 跑 `python main.py`，验证真实 API 数据
5. 确认一切正常后，启动 `python main.py --schedule`

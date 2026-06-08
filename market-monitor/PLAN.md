# market-monitor — Project Plan

## 一句话描述

每个交易日 **太平洋时间 6:30AM（美股开盘 = ET 9:30）** 发送一次基准快照邮件；之后
**每 5 分钟**在交易时段刷新一次，当 SPY / QQQ / VIX / VXN 相对**当日基准**变动
**超过 1%** 时发送告警邮件。监控 SPY/QQQ 相对 **SMA 5/10/50/200** 的偏离，以及
VIX、VXN 两个波动率指数。仿照 daily-news-letter digest 的格式，但通过 **邮件**
（Gmail SMTP）而非 Telegram 投递。

---

## 需求来源

- 监控：①SPY/QQQ 对 SMA 5/10/50/200 的百分比 ②VIX ③VXN（VNX → VXN，纳指波动率）
- 每个交易日：PT 6:30AM 开盘推送一次基准；其他时间每 5 分钟刷新，监控超过基准 1% 的变化
- 投递：用 `angli.claude@gmail.com` 发给 `angli1937@gmail.com`
- 形态：仿照 daily news letter 格式，先出 plan，再做 MVP，独立新 repo

---

## 技术栈

| 层 | 选型 | 备注 |
|---|---|---|
| 语言 | Python 3.11+ | `zoneinfo` 标准库做时区 |
| 行情 / 指数 | yfinance | SPY/QQQ OHLCV + `^VIX`/`^VXN`，无需 API key |
| 均线 | pandas rolling | 纯函数计算，可单测 |
| 定时 | APScheduler | Cron(6:30 PT) + Interval(5min) |
| 投递 | smtplib (Gmail SMTP) | 标准库；需 App Password |
| 配置 | python-dotenv + `.env` | 密钥不入库 |

无需任何付费/注册 API：yfinance + CBOE 指数行情 + Gmail SMTP。

---

## 监控对象

| 组 | Symbol | 展示 |
|---|---|---|
| Equity | SPY, QQQ | price vs **SMA 5 / 10 / 50 / 200**（偏离% + above/below） |
| Volatility | ^VIX, ^VXN | 指数点位（VIX↔标普500，VXN↔纳指100） |

> 注：daily-news-letter 的均线库用的是 50/100/200/250；本项目按需求改为
> **5/10/50/200**（`compute_ma_comparison` 已参数化 periods）。

---

## 告警语义（关键设计）

- **基准（baseline）** = 当日 6:30 AM PT 推送时各标的的价格/点位。
- **每 5 分钟**取当前值，对每个标的计算相对 **reference** 的百分比变化；
  `abs(pct) > 1%`（严格大于）即触发，邮件展示完整最新快照 + Triggered 区块。
- **Ratchet（棘轮）**：某标的触发后，它的 reference 抬升到当前值；下一次需再走
  满 1% 才会再次告警 —— 避免某标的卡在阈值附近时每 5 分钟刷屏。
- baseline 始终保留，邮件里同时显示「相对基准」的累计变化。
- 仅交易日、仅交易时段（ET 9:30–16:00，含 NYSE 节假日表）运行 5 分钟轮询。

---

## 数据流

```
6:30 AM PT  establish_baseline()
   yfinance → Snapshot(SPY/QQQ SMAs + VIX/VXN)
            → state{date, baseline, refs} 落盘
            → render(baseline) → SMTP 邮件

每 5 分钟    check_and_alert()   (先判断 is_market_open)
   load state → yfinance → Snapshot
   若 state 非今日 → 当场补建 baseline（重启/迟启动兜底）
   evaluate(refs, current, 1%, baseline) → (alerts, new_refs)
   若有 alerts: refs 落盘 + render(alert) → SMTP 邮件
```

状态文件 `monitor_state.json`（gitignore）：`{date, baseline{sym:px}, refs{sym:px}}`。

---

## 输出格式示例（邮件正文，text/plain + 同内容 `<pre>` HTML）

基准邮件：
```
📊 Market Monitor — Baseline — June 08, 2026 06:30 PT

## 📈 SMA Comparison
SPY  $589.25
  🟢 SMA5    $585.10  +0.7%
  🟢 SMA10   $580.40  +1.5%
  🟢 SMA50   $560.20  +5.2%
  🟢 SMA200  $545.80  +8.0%
QQQ  $498.50
  🔴 SMA5    $500.10  -0.3%
  🟢 SMA200  $455.80  +9.4%

## 🌡️ Volatility
  VIX   14.20
  VXN   17.85
```

告警邮件：
```
⚠️ Market Monitor Alert — June 08, 2026 07:15 PT

⚠️ Triggered (>1.0% vs baseline)
  ▲ SPY   +1.13% vs base   589.25 → 595.90
  ▲ VIX   +5.28% vs base   14.20 → 14.95

## 📈 SMA Comparison
... (完整最新快照) ...
```

---

## 项目结构

```
market-monitor/
├── monitor/
│   ├── config.py          # env / .env
│   ├── calendar_utils.py  # NYSE 交易日 + 开盘时段（ET）
│   ├── moving_averages.py # price vs N SMAs（纯函数）
│   ├── indicators.py      # yfinance → Snapshot（网络）
│   ├── snapshot.py        # Snapshot / Reading dataclasses
│   ├── state.py           # JSON baseline + ratchet refs
│   ├── alerts.py          # >阈值检测 + 棘轮（纯函数）
│   ├── formatter.py       # Snapshot/alerts → (subject, html, text)
│   ├── email_send.py      # SMTP (Gmail) 多部分发送
│   └── runner.py          # establish_baseline / check_and_alert / run_schedule
├── main.py                # CLI：--once / --baseline / --schedule / --test [/ --no-send]
├── tests/                 # 离线单测（无 live API / SMTP）
├── .env.example  requirements.txt  requirements-dev.txt  ruff.toml
└── .github/workflows/ci.yml
```

---

## 测试用例（全部离线，mock 数据 / 直接调用 / 断言输出）

1. **moving_averages**：5/10/50/200 强势上行 → 4 档全 above 且偏离>0；历史不足
   （<201 行）→ None，恰好 201 行 → 有结果；自定义 periods；上行后回调 → above/below 混合；
   无 Close / 空表 → None。
2. **alerts**：+1.5% 触发并 ratchet；+0.5% 不触发；恰好 +1.0% **不**触发（严格 >）；
   负向 -1.x% 触发；棘轮（触发后需再走满 1%）；多标的 + 首次 seeding 不告警。
3. **formatter**：baseline 渲染含 SPY/QQQ/VIX/VXN、SMA5/SMA200、🟢🔴、📈🌡️、`<pre>`，
   且不含 Triggered；alert 渲染 subject 含 Alert+标的、正文含 Triggered 与 +x.xx%。
4. **state**：JSON 往返一致；文件缺失 → {}；损坏 JSON → {}。

冒烟（需网络/凭据，非 CI）：`python main.py --test`（纯离线渲染），其次
`python main.py --once --no-send`（live yfinance，不发信），最后配好 App Password 后
`python main.py --once` 真发一封。

---

## V1.1：Per-symbol 告警阈值（财务顾问建议）

1% 对不同标的含义不同。SPY/QQQ 日内波动 ~0.5–1%，>1% 是真信号；VIX/VXN 日均波动
~5%，1% 纯噪声。默认阈值：

| 标的 | 阈值 | 理由 |
|---|---|---|
| SPY, QQQ | 1% | 有意义的指数日 |
| VIX, VXN | 10% | 平衡：滤掉日常噪声，抓住情绪切换（每月几次） |

档位：5=灵敏(吵) · 10=平衡(推荐) · 15=只报大波动。

实现：`evaluate(..., thresholds={sym: pct})` 每标的阈值，缺省回退到
`ALERT_THRESHOLD_PCT`；`Alert.threshold` 记录触发阈值，邮件按行显示 `(>X%)`。
配置：`ALERT_THRESHOLDS=^VIX:10,^VXN:10`（缺省）+ `ALERT_THRESHOLD_PCT=1.0`。

## V1.2：CI + 自动部署到 GCP（serverless）

- **CI** `.github/workflows/ci.yml`：ruff + import check + pytest。
- **CD** `.github/workflows/deploy.yml`：push 到 main → 跑测试 → Cloud Build 构建镜像
  → Artifact Registry → `gcloud run jobs update` 滚动 Cloud Run Job。
- **运行形态**：Cloud Scheduler（cron，太平洋时区，DST 自动）每 5 分钟触发 Cloud Run
  Job 跑 `main.py --tick`（开盘首跑建基准并发邮件，其后仅超阈值发告警）；app 用
  `is_market_open()` 把非交易时段触发变成空操作。
- **状态**：`STATE_PATH=gs://bucket/state.json`（Cloud Run 文件系统易失；state.py 增
  GCS 后端，lazy import google-cloud-storage）。
- **密钥**：Gmail App Password 存 Secret Manager，注入 `EMAIL_PASSWORD`。
- **鉴权**：GitHub Actions 用 Workload Identity Federation（无长期密钥）。
- **一次性引导** `deploy/gcp_setup.sh`：建 AR / GCS 桶 / 密钥 / SA / IAM / Job /
  Scheduler / WIF。详见 `deploy/README.md`。替代方案：GCE e2-micro 跑 `--schedule`。

## 进度

- [x] plan（本文件）
- [x] 纯计算层：moving_averages / alerts / snapshot / state
- [x] 时段层：calendar_utils（NYSE 2025–2027 节假日）
- [x] 取数层：indicators（yfinance，lazy import）
- [x] 渲染层：formatter（markdown 风格 + `<pre>` HTML）
- [x] 投递层：email_send（Gmail SMTP 587/465）
- [x] 编排层：runner + main CLI
- [x] 离线单测 + CI（ruff + import check + pytest）
- [x] V1.1: per-symbol 阈值（VIX/VXN 默认 10%）
- [x] V1.2: Dockerfile + GCS state + CD(deploy.yml) + gcp_setup.sh（pipeline-as-code）
- [ ] 用户填入 Gmail App Password 后端到端真发一封
- [ ] 在 GCP 项目跑 deploy/gcp_setup.sh + 配置 GitHub vars/secrets 完成首次部署

---

## 后续可选增强

| 功能 | 描述 | 复杂度 |
|---|---|---|
| 每标的独立阈值 | VIX/VXN 波动大，单独设更高阈值 | 低 |
| 盘中高/低水位 | 记录当日极值，邮件附 intraday range | 低 |
| 更多标的 | IWM/DIA、板块 ETF、自选股 | 低 |
| 收盘小结 | 16:00 ET 发当日收盘 + 偏离汇总 | 低 |
| Telegram 双通道 | 复用 formatter，加一个 Telegram sender | 中 |
| 真正的盘历日历 | 接 pandas-market-calendars 替代硬编码节假日 | 中 |
```

# backtest/

SMA timing backtesting engine — signals, metrics, reporting.

## Key files

| File | Purpose |
|------|---------|
| `engine.py` | `BacktestEngine.run()` — applies signal to prices, tracks trades, equity curve |
| `signals.py` | `basic_ma_signal`, `vix_optimized_signal`, `dual_ma_signal` |
| `metrics.py` | CAGR, Sharpe, max drawdown calculations + `BacktestMetrics` dataclass |
| `data.py` | `load_ticker_data(ticker)` — any yfinance symbol, `load_vix_data()` |
| `report.py` | `generate_sma_comparison()`, `generate_signal_comparison()` |

## Usage

```bash
python scripts/run_backtest.py --underlying SPY --signal basic_ma --sma 250
python scripts/run_backtest.py --compare-sma QQQ
python scripts/run_backtest.py --compare-signals AAPL
python scripts/run_backtest.py --underlying TSLA --plot
```

## Signal semantics

`signal[i] = 1` means "hold position from close[i] to close[i+1]". The engine shifts by 1 before applying returns so there's no look-ahead bias.

Entry band: `close > SMA × 1.04`, exit band: `close < SMA × 0.95` (hysteresis prevents whipsawing).

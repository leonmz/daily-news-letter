"""One-shot preview: pull SPY/QQQ daily OHLCV, compute MA snapshot, print Telegram-style output.

Run: python scripts/preview_moving_averages.py
Not wired into pipeline yet — this is a design-time preview.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

try:
    import yfinance as yf
    HAS_YF = True
except ImportError:
    HAS_YF = False


@dataclass
class MALine:
    name: str
    value: float
    deviation_pct: float
    slope: str | None = None


@dataclass
class MASnapshot:
    ticker: str
    price: float
    lines: list[MALine]
    stack: str
    cross_event: str | None
    sma200_deviation: float


def _slope(series: pd.Series, lookback: int = 5, flat_threshold: float = 0.001) -> str:
    if len(series.dropna()) < lookback + 1:
        return "n/a"
    recent = series.dropna().iloc[-lookback - 1:]
    delta = (recent.iloc[-1] - recent.iloc[0]) / recent.iloc[0]
    if delta > flat_threshold:
        return "rising"
    if delta < -flat_threshold:
        return "falling"
    return "flat"


def _detect_cross(sma50: pd.Series, sma200: pd.Series, window: int = 5) -> str | None:
    s50 = sma50.dropna()
    s200 = sma200.dropna()
    if len(s50) < window + 1 or len(s200) < window + 1:
        return None
    aligned = pd.concat([s50, s200], axis=1, join="inner").dropna()
    aligned.columns = ["s50", "s200"]
    if len(aligned) < window + 1:
        return None
    diff = aligned["s50"] - aligned["s200"]
    sign = (diff > 0).astype(int)
    recent = sign.iloc[-window - 1:]
    for i in range(1, len(recent)):
        if recent.iloc[i - 1] == 0 and recent.iloc[i] == 1:
            days_ago = len(recent) - 1 - i
            return f"Golden Cross {days_ago}d ago" if days_ago > 0 else "Golden Cross today"
        if recent.iloc[i - 1] == 1 and recent.iloc[i] == 0:
            days_ago = len(recent) - 1 - i
            return f"Death Cross {days_ago}d ago" if days_ago > 0 else "Death Cross today"
    return None


def compute_ma_snapshot(ticker: str, df: pd.DataFrame) -> MASnapshot | None:
    if df is None or df.empty or "Close" not in df.columns:
        return None
    close = df["Close"]
    if len(close) < 200:
        return None

    ema21 = close.ewm(span=21, adjust=False).mean()
    sma50 = close.rolling(50).mean()
    sma150 = close.rolling(150).mean()
    sma200 = close.rolling(200).mean()

    price = float(close.iloc[-1])
    e21 = float(ema21.iloc[-1])
    s50 = float(sma50.iloc[-1])
    s150 = float(sma150.iloc[-1])
    s200 = float(sma200.iloc[-1])

    lines = [
        MALine("EMA21", e21, (price - e21) / e21 * 100),
        MALine("SMA50", s50, (price - s50) / s50 * 100, slope=_slope(sma50)),
        MALine("SMA150", s150, (price - s150) / s150 * 100),
        MALine("SMA200", s200, (price - s200) / s200 * 100),
    ]

    if price > e21 > s50 > s150 > s200:
        stack = "Bull Stack"
    elif price < e21 < s50 < s150 < s200:
        stack = "Bear Stack"
    else:
        stack = "Mixed"

    cross_event = _detect_cross(sma50, sma200, window=5)
    sma200_dev = (price - s200) / s200 * 100

    return MASnapshot(ticker, price, lines, stack, cross_event, sma200_dev)


def _stack_marker(stack: str) -> str:
    return {"Bull Stack": "Bull Stack ✓", "Bear Stack": "Bear Stack ✗", "Mixed": "Mixed"}[stack]


def _dev_str(pct: float) -> str:
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.1f}%"


def _health_tag(sma200_dev: float) -> str:
    if sma200_dev > 10:
        return "  (overheated)"
    if sma200_dev < -10:
        return "  (oversold)"
    return ""


def format_ma_section(snapshots: list[MASnapshot]) -> str:
    out = ["📈 *SPY/QQQ Trend Snapshot*", ""]
    for snap in snapshots:
        out.append(f"{snap.ticker}  ${snap.price:.2f}  {_stack_marker(snap.stack)}")
        for ln in snap.lines:
            slope_tag = f" ({ln.slope})" if ln.slope else ""
            health = _health_tag(ln.deviation_pct) if ln.name == "SMA200" else ""
            out.append(f"  {ln.name:<6} ${ln.value:>7.2f}  {_dev_str(ln.deviation_pct)}{slope_tag}{health}")
        if snap.cross_event:
            marker = "⚠" if "Death" in snap.cross_event else "✨"
            out.append(f"  {marker} SMA50 × SMA200 {snap.cross_event}")
        else:
            out.append("  No recent cross.")
        out.append("")
    return "\n".join(out).rstrip()


def _synthetic_series(n: int, start_price: float, segments: list[tuple[int, float, float]], seed: int) -> pd.DataFrame:
    """Generate n trading days with multiple regime segments (length, drift, vol)."""
    rng = np.random.default_rng(seed)
    rets = []
    for length, drift, vol in segments:
        rets.extend(rng.normal(drift, vol, length))
    rets = np.array(rets[:n])
    prices = start_price * np.exp(np.cumsum(rets))
    idx = pd.date_range(end=datetime.now().date(), periods=len(prices), freq="B")
    return pd.DataFrame({"Close": prices}, index=idx)


def _try_live(ticker: str) -> pd.DataFrame | None:
    if not HAS_YF:
        return None
    try:
        end = datetime.now().date()
        start = end - timedelta(days=400)
        df = yf.Ticker(ticker).history(start=start.isoformat(), end=end.isoformat(), auto_adjust=True)
        if df is None or df.empty:
            return None
        return df
    except Exception:
        return None


def main():
    snapshots: list[MASnapshot] = []
    used_synthetic = False

    scenarios = {
        # SPY: clean uptrend → bull stack
        "SPY": dict(
            n=280, start_price=460.0, seed=42,
            segments=[(280, 0.0007, 0.009)],
        ),
        # QQQ: long dip then strong recovery → recent golden cross
        "QQQ": dict(
            n=280, start_price=420.0, seed=11,
            segments=[(225, -0.0010, 0.013), (55, 0.0035, 0.010)],
        ),
    }

    for ticker, params in scenarios.items():
        df = _try_live(ticker)
        if df is None:
            df = _synthetic_series(**params)
            used_synthetic = True
        snap = compute_ma_snapshot(ticker, df)
        if snap is None:
            print(f"!! insufficient history for {ticker} (got {len(df)} rows)")
            continue
        snapshots.append(snap)

    if used_synthetic:
        print("(NOTE: live yfinance blocked in this env — using synthetic OHLCV for preview)\n")
    print(format_ma_section(snapshots))

    print("\n--- cross-event text variants (would replace 'No recent cross.' line) ---")
    print("  ✨ SMA50 × SMA200 Golden Cross today")
    print("  ✨ SMA50 × SMA200 Golden Cross 3d ago")
    print("  ⚠ SMA50 × SMA200 Death Cross 1d ago")


if __name__ == "__main__":
    main()

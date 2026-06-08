"""Render a Snapshot (and optional alerts) into an email: (subject, html, text).

Style mirrors the daily-news-letter digest: emoji section headers, per-ticker
SMA lines with 🟢/🔴 and signed % deviation, plus a volatility block. The HTML
body wraps the same plain-text content in ``<pre>`` so column alignment survives
across email clients; a text/plain alternative is included too.
"""

from __future__ import annotations

from datetime import datetime
from html import escape

from monitor.alerts import Alert
from monitor.snapshot import Reading, Snapshot


def display_symbol(symbol: str) -> str:
    """'^VIX' -> 'VIX'; equity tickers are returned unchanged."""
    return symbol.lstrip("^")


def _fmt_pct(pct: float) -> str:
    return f"+{pct:.1f}%" if pct >= 0 else f"{pct:.1f}%"


def _fmt_signed(pct: float) -> str:
    return f"+{pct:.2f}%" if pct >= 0 else f"{pct:.2f}%"


def _arrow(pct: float) -> str:
    return "▲" if pct >= 0 else "▼"


def _pretty_time(iso_ts: str) -> str:
    try:
        return datetime.fromisoformat(iso_ts).strftime("%B %d, %Y %H:%M PT")
    except ValueError:
        return iso_ts


def _equity_lines(r: Reading) -> list[str]:
    lines = [f"{display_symbol(r.symbol)}  ${r.price:.2f}"]
    if r.ma is not None:
        for lv in r.ma.levels:
            dot = "🟢" if lv.above else "🔴"
            label = f"SMA{lv.period}".ljust(7)
            lines.append(f"  {dot} {label} ${lv.value:.2f}  {_fmt_pct(lv.deviation_pct)}")
    else:
        lines.append("  (insufficient history for SMAs)")
    return lines


def build_body(snapshot: Snapshot, alerts: list[Alert] | None) -> list[str]:
    """Build the shared plain-text body lines (used for both text and <pre> html)."""
    alerts = alerts or []
    equities = [r for r in snapshot.readings if not r.symbol.startswith("^")]
    vol = [r for r in snapshot.readings if r.symbol.startswith("^")]
    lines: list[str] = []

    if alerts:
        lines.append("⚠️ Triggered (move vs baseline cleared its threshold)")
        for a in alerts:
            sym = display_symbol(a.symbol)
            limit = f" (>{a.threshold:g}%)" if a.threshold else ""
            lines.append(
                f"  {_arrow(a.pct_from_baseline)} {sym:<5} {_fmt_signed(a.pct_from_baseline)} vs base"
                f"{limit}   {a.baseline:.2f} → {a.current:.2f}"
            )
        lines.append("")

    if equities:
        lines.append("## 📈 SMA Comparison")
        for r in equities:
            lines.extend(_equity_lines(r))
        lines.append("")

    if vol:
        lines.append("## 🌡️ Volatility")
        for r in vol:
            lines.append(f"  {display_symbol(r.symbol):<5} {r.price:.2f}")
        lines.append("")

    return lines


def render(
    snapshot: Snapshot,
    *,
    kind: str = "baseline",
    alerts: list[Alert] | None = None,
    threshold: float = 1.0,
) -> tuple[str, str, str]:
    """Return ``(subject, html_body, text_body)``.

    ``kind`` is one of 'baseline' | 'refresh' | 'alert'. A non-empty ``alerts``
    list is rendered as an alert email regardless of ``kind``.
    """
    alerts = alerts or []
    when = _pretty_time(snapshot.timestamp)

    if alerts:
        moved = ", ".join(
            f"{display_symbol(a.symbol)} {_fmt_signed(a.pct_from_baseline)}" for a in alerts
        )
        subject = f"⚠️ Market Monitor Alert — {moved}"
        title = f"⚠️ Market Monitor Alert — {when}"
    elif kind == "baseline":
        subject = f"📊 Market Monitor — Baseline {when}"
        title = f"📊 Market Monitor — Baseline — {when}"
    else:
        subject = f"📊 Market Monitor — {when}"
        title = subject

    body = [title, ""] + build_body(snapshot, alerts)
    text = "\n".join(body).rstrip() + "\n"

    html = (
        '<html><body style="margin:0;padding:16px;background:#ffffff;color:#111111;">'
        '<pre style="font:14px/1.45 ui-monospace,Menlo,Consolas,monospace;white-space:pre-wrap;">'
        f"{escape(text)}</pre></body></html>"
    )
    return subject, html, text

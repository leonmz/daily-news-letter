"""Unit tests for monitor.formatter — email rendering."""

from monitor.alerts import Alert
from monitor.formatter import display_symbol, render
from monitor.moving_averages import MAComparison, MALevel
from monitor.snapshot import Reading, Snapshot


def _snap(ts: str = "2026-06-08T06:30") -> Snapshot:
    spy = MAComparison("SPY", 589.25, [
        MALevel(5, 585.10, 0.71, True),
        MALevel(200, 600.00, -1.79, False),
    ])
    qqq = MAComparison("QQQ", 498.50, [MALevel(5, 495.00, 0.71, True)])
    return Snapshot(ts, "2026-06-08", [
        Reading("SPY", 589.25, spy),
        Reading("QQQ", 498.50, qqq),
        Reading("^VIX", 14.20, None),
        Reading("^VXN", 17.85, None),
    ])


def test_display_symbol():
    assert display_symbol("^VIX") == "VIX"
    assert display_symbol("SPY") == "SPY"


def test_baseline_render():
    subject, html, text = render(_snap(), kind="baseline", threshold=1.0)
    assert "Baseline" in subject
    for token in ("SPY", "QQQ", "VIX", "VXN", "SMA5", "SMA200", "📈", "🌡️"):
        assert token in text, f"missing {token!r}"
    assert "🟢" in text and "🔴" in text
    assert "<pre" in html and "</pre>" in html
    assert "Triggered" not in text


def test_alert_render():
    alerts = [
        Alert("^VIX", 14.20, 14.20, 15.95, 12.32, 12.32, 10.0),
        Alert("SPY", 589.25, 589.25, 595.90, 1.13, 1.13, 1.0),
    ]
    subject, html, text = render(_snap("2026-06-08T07:15"), kind="alert", alerts=alerts, threshold=1.0)
    assert "Alert" in subject
    assert "VIX" in subject and "SPY" in subject
    assert "Triggered" in text
    assert "+1.13%" in text
    assert "+12.32%" in text
    assert "(>10%)" in text  # per-symbol threshold shown
    assert "<pre" in html

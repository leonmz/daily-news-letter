"""Unit tests for monitor.alerts — threshold + ratchet logic."""

from monitor.alerts import evaluate


def test_triggers_above_threshold():
    alerts, refs = evaluate({"SPY": 100.0}, {"SPY": 101.5}, 1.0, {"SPY": 100.0})
    assert len(alerts) == 1
    assert alerts[0].symbol == "SPY"
    assert round(alerts[0].pct_change, 2) == 1.5
    assert round(alerts[0].pct_from_baseline, 2) == 1.5
    assert refs["SPY"] == 101.5  # ratcheted to current


def test_no_trigger_below_threshold():
    alerts, refs = evaluate({"SPY": 100.0}, {"SPY": 100.5}, 1.0, {"SPY": 100.0})
    assert alerts == []
    assert refs["SPY"] == 100.0  # unchanged


def test_exactly_threshold_does_not_trigger():
    # Strict greater-than: exactly +1.0% must not fire.
    alerts, _ = evaluate({"SPY": 100.0}, {"SPY": 101.0}, 1.0, {"SPY": 100.0})
    assert alerts == []


def test_negative_move_triggers():
    alerts, refs = evaluate({"VIX": 14.0}, {"VIX": 13.7}, 1.0, {"VIX": 14.0})
    assert len(alerts) == 1
    assert alerts[0].pct_change < 0
    assert refs["VIX"] == 13.7


def test_ratchet_requires_further_move():
    base = {"SPY": 100.0}
    refs = {"SPY": 100.0}

    a1, refs = evaluate(refs, {"SPY": 101.5}, 1.0, base)
    assert len(a1) == 1 and refs["SPY"] == 101.5

    a2, refs = evaluate(refs, {"SPY": 102.3}, 1.0, base)  # +0.79% vs 101.5 ref
    assert a2 == [] and refs["SPY"] == 101.5

    a3, refs = evaluate(refs, {"SPY": 102.7}, 1.0, base)  # +1.18% vs 101.5 ref
    assert len(a3) == 1
    assert round(a3[0].pct_from_baseline, 2) == 2.70  # vs the 100.0 baseline
    assert refs["SPY"] == 102.7


def test_multi_instrument_and_seeding():
    # VIX has no reference yet → seeded this call, no alert.
    alerts, refs = evaluate({"SPY": 100.0}, {"SPY": 100.2, "VIX": 14.0}, 1.0, {"SPY": 100.0})
    assert alerts == []
    assert refs["VIX"] == 14.0

    alerts2, _ = evaluate(refs, {"SPY": 100.2, "VIX": 14.3}, 1.0, {"SPY": 100.0, "VIX": 14.0})
    assert [a.symbol for a in alerts2] == ["VIX"]  # +2.14%


def test_per_symbol_threshold_overrides():
    thr = {"^VIX": 10.0}
    # VIX +5% is below its 10% override → no alert (would have fired at the 1% default).
    a1, _ = evaluate({"^VIX": 14.0}, {"^VIX": 14.7}, 1.0, {"^VIX": 14.0}, thresholds=thr)
    assert a1 == []
    # VIX +12.1% clears the 10% override and records that threshold on the alert.
    a2, _ = evaluate({"^VIX": 14.0}, {"^VIX": 15.7}, 1.0, {"^VIX": 14.0}, thresholds=thr)
    assert len(a2) == 1 and a2[0].threshold == 10.0
    # An equity with no override still uses the 1.0 scalar default.
    a3, _ = evaluate({"SPY": 100.0}, {"SPY": 101.5}, 1.0, {"SPY": 100.0}, thresholds=thr)
    assert len(a3) == 1 and a3[0].threshold == 1.0

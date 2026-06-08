"""Threshold + ratchet alerting logic (pure).

Each monitored instrument carries a *reference* value. When the latest value
moves more than ``threshold`` percent away from its reference, an Alert fires and
the reference ratchets to the new value — so the next alert needs a further full
move, instead of re-firing every 5 minutes while a level sits just past the line.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Alert:
    symbol: str
    baseline: float            # the day's 6:30 baseline value
    reference: float           # value the move is measured from (ratchets)
    current: float
    pct_change: float          # current vs reference
    pct_from_baseline: float   # current vs baseline
    threshold: float = 0.0     # the % threshold this move cleared


def evaluate(
    references: dict[str, float],
    current: dict[str, float],
    threshold: float,
    baseline: dict[str, float] | None = None,
    thresholds: dict[str, float] | None = None,
) -> tuple[list[Alert], dict[str, float]]:
    """Return ``(alerts, updated_references)``.

    For every symbol in ``current`` with a positive reference, fire an Alert when
    the percentage move vs reference strictly exceeds that symbol's threshold in
    absolute value. The threshold is ``thresholds[symbol]`` if present, else the
    scalar ``threshold`` default — so equities can use 1% while VIX/VXN use 10%.
    Triggered symbols ratchet their reference to the current value. Symbols with
    no/zero reference are seeded (reference set to current) and never alert on
    this call.
    """
    baseline = baseline or {}
    thresholds = thresholds or {}
    alerts: list[Alert] = []
    new_refs = dict(references)

    for symbol, cur in current.items():
        ref = references.get(symbol)
        if ref is None or ref == 0:
            new_refs[symbol] = cur
            continue
        limit = thresholds.get(symbol, threshold)
        pct = (cur - ref) / ref * 100.0
        if abs(pct) > limit:
            base = baseline.get(symbol, ref)
            pct_base = ((cur - base) / base * 100.0) if base else pct
            alerts.append(
                Alert(
                    symbol=symbol,
                    baseline=base,
                    reference=ref,
                    current=cur,
                    pct_change=pct,
                    pct_from_baseline=pct_base,
                    threshold=limit,
                )
            )
            new_refs[symbol] = cur  # ratchet

    return alerts, new_refs

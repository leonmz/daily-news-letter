"""Unit tests for CBOEProvider — all HTTP calls mocked."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from data.providers.cboe import CBOEProvider


# ─── mock data ────────────────────────────────────────────────────────────────

MOCK_OPTIONS = [
    {
        "option": "SPY271217C00560000",
        "bid": 170.0, "ask": 175.0, "iv": 0.224, "open_interest": 50, "volume": 5,
        "delta": 0.848, "gamma": 0.0012, "theta": -0.08, "vega": 2.07,
        "last_trade_price": 172.0,
    },
    {
        "option": "SPY271217C00600000",
        "bid": 130.0, "ask": 135.0, "iv": 0.230, "open_interest": 100, "volume": 12,
        "delta": 0.750, "gamma": 0.0015, "theta": -0.09, "vega": 2.50,
        "last_trade_price": 132.0,
    },
    {
        "option": "SPY271217P00560000",
        "bid": 55.0, "ask": 58.0, "iv": 0.224, "open_interest": 30, "volume": 3,
        "delta": -0.152, "gamma": 0.0012, "theta": -0.05, "vega": 2.07,
        "last_trade_price": 56.0,
    },
    {  # Near-term — should be excluded by min_expiry_days
        "option": "SPY260618C00680000",
        "bid": 15.0, "ask": 16.0, "iv": 0.18, "open_interest": 5000, "volume": 500,
        "delta": 0.52, "gamma": 0.008, "theta": -0.20, "vega": 0.80,
        "last_trade_price": 15.5,
    },
]


def _mock_fetch():
    """Patch _fetch to return mock options list."""
    return patch.object(CBOEProvider, "_fetch", new_callable=AsyncMock, return_value=MOCK_OPTIONS)


# ─── get_option_chain ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_option_chain_returns_calls_and_puts():
    p = CBOEProvider()
    with _mock_fetch():
        snap = await p.get_option_chain("SPY", "2027-12-17")

    assert snap is not None
    assert snap.ticker == "SPY"
    assert len(snap.calls) == 2   # 2 LEAP calls
    assert len(snap.puts) == 1
    assert snap.source == "cboe"


@pytest.mark.asyncio
async def test_get_option_chain_has_greeks():
    p = CBOEProvider()
    with _mock_fetch():
        snap = await p.get_option_chain("SPY", "2027-12-17")

    assert snap.has_greeks
    c = snap.calls[0]
    assert c.delta == pytest.approx(0.848)
    assert c.gamma == pytest.approx(0.0012)
    assert c.theta == pytest.approx(-0.08)
    assert c.vega == pytest.approx(2.07)
    assert c.implied_volatility == pytest.approx(0.224)


@pytest.mark.asyncio
async def test_get_option_chain_filters_by_expiry():
    p = CBOEProvider()
    with _mock_fetch():
        snap = await p.get_option_chain("SPY", "2026-06-18")  # near-term

    assert snap is not None
    assert len(snap.calls) == 1  # only the June 2026 call
    assert snap.calls[0].strike == 680.0


@pytest.mark.asyncio
async def test_get_option_chain_all_expiries():
    p = CBOEProvider()
    with _mock_fetch():
        snap = await p.get_option_chain("SPY")  # no expiry filter

    assert snap is not None
    assert snap.total_contracts == 4  # all 4 contracts


@pytest.mark.asyncio
async def test_get_option_chain_failure_returns_none():
    p = CBOEProvider()
    with patch.object(p, "_fetch", new_callable=AsyncMock, side_effect=RuntimeError("network")):
        snap = await p.get_option_chain("SPY")

    assert snap is None


# ─── find_by_delta ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_find_by_delta_selects_closest():
    p = CBOEProvider()
    with _mock_fetch():
        # Target 0.85 — should pick the 0.848 delta contract (K=560), not 0.750 (K=600)
        c = await p.find_by_delta("SPY", target_delta=0.85, min_expiry_days=365, max_spread_pct=0.10)

    assert c is not None
    assert c.strike == 560.0
    assert c.delta == pytest.approx(0.848)
    assert c.option_type == "call"
    assert c.expiry == "2027-12-17"


@pytest.mark.asyncio
async def test_find_by_delta_filters_near_term():
    """Near-term options (< min_expiry_days) should be excluded."""
    p = CBOEProvider()
    with _mock_fetch():
        # min_expiry_days=365 → Dec 2027 qualifies, June 2026 is excluded
        # Target 0.52 → nearest is June 2026 (delta=0.52) but it's filtered out
        # so we get Dec 2027 K=600 (delta=0.750) instead
        c = await p.find_by_delta("SPY", target_delta=0.52, min_expiry_days=365, max_spread_pct=0.10, max_delta_deviation=0.50)

    assert c is not None
    assert c.expiry == "2027-12-17"  # June 2026 was excluded


@pytest.mark.asyncio
async def test_find_by_delta_respects_max_deviation():
    p = CBOEProvider()
    with _mock_fetch():
        # Target 0.95 — closest is 0.848, deviation=0.102 > max 0.03
        c = await p.find_by_delta(
            "SPY", target_delta=0.95, min_expiry_days=365,
            max_spread_pct=0.10, max_delta_deviation=0.03,
        )

    assert c is None  # no contract within deviation


@pytest.mark.asyncio
async def test_find_by_delta_liquidity_gate():
    """Contracts with wide spread should be excluded."""
    p = CBOEProvider()
    with _mock_fetch():
        # max_spread_pct=0.01 → spread must be <1%
        # K=560 spread=(175-170)/172.5 = 2.9%, should be excluded
        # K=600 spread=(135-130)/132.5 = 3.8%, should be excluded
        c = await p.find_by_delta(
            "SPY", target_delta=0.85, min_expiry_days=365, max_spread_pct=0.01,
        )

    assert c is None  # all filtered by spread gate


# ─── get_expirations ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_expirations_returns_sorted():
    p = CBOEProvider()
    with _mock_fetch():
        exps = await p.get_expirations("SPY")

    assert len(exps) == 2
    assert exps == ["2026-06-18", "2027-12-17"]  # sorted ascending

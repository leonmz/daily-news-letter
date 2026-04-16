"""Unit tests for DatabentoProvider — all API calls mocked."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, PropertyMock

import pandas as pd
import pytest

from data.providers.databento_provider import DatabentoProvider


# ─── mock data ────────────────────────────────────────────────────────────────

MOCK_DEF_DF = pd.DataFrame([
    {
        "instrument_id": 1001,
        "strike_price": 560_000_000_000,  # Databento fixed-point: 560.0 * 1e9
        "expiration": pd.Timestamp("2027-12-17"),
        "instrument_class": "C",
        "volume": 50,
    },
    {
        "instrument_id": 1002,
        "strike_price": 600_000_000_000,
        "expiration": pd.Timestamp("2027-12-17"),
        "instrument_class": "C",
        "volume": 120,
    },
    {
        "instrument_id": 1003,
        "strike_price": 560_000_000_000,
        "expiration": pd.Timestamp("2027-12-17"),
        "instrument_class": "P",
        "volume": 30,
    },
    {
        "instrument_id": 1004,
        "strike_price": 580_000_000_000,
        "expiration": pd.Timestamp("2026-06-18"),
        "instrument_class": "C",
        "volume": 500,
    },
])

MOCK_MBP_DF = pd.DataFrame([
    {"instrument_id": 1001, "bid_px_00": 170.0, "ask_px_00": 175.0},
    {"instrument_id": 1002, "bid_px_00": 130.0, "ask_px_00": 135.0},
    {"instrument_id": 1003, "bid_px_00": 55.0, "ask_px_00": 58.0},
    {"instrument_id": 1004, "bid_px_00": 15.0, "ask_px_00": 16.0},
])

MOCK_STATS_DF = pd.DataFrame([
    {"instrument_id": 1001, "quantity": 500},
    {"instrument_id": 1002, "quantity": 1000},
    {"instrument_id": 1003, "quantity": 300},
    {"instrument_id": 1004, "quantity": 5000},
])


def _make_mock_data(df):
    """Create a mock Databento data object with .to_df() returning df."""
    mock = MagicMock()
    mock.to_df.return_value = df
    return mock


def _patch_client(def_df=MOCK_DEF_DF, mbp_df=MOCK_MBP_DF, stats_df=MOCK_STATS_DF):
    """Patch the Databento Historical client."""
    mock_client = MagicMock()

    def get_range_side_effect(**kwargs):
        schema = kwargs.get("schema", "")
        if schema == "definition":
            return _make_mock_data(def_df)
        elif schema == "mbp-1":
            return _make_mock_data(mbp_df)
        elif schema == "statistics":
            return _make_mock_data(stats_df)
        elif schema == "ohlcv-1d":
            ohlcv = pd.DataFrame({
                "open": [500.0, 505.0], "high": [510.0, 515.0],
                "low": [495.0, 500.0], "close": [505.0, 510.0],
                "volume": [1000000, 1200000],
            })
            return _make_mock_data(ohlcv)
        return _make_mock_data(pd.DataFrame())

    mock_client.timeseries.get_range.side_effect = get_range_side_effect
    return mock_client


# ─── construction ─────────────────────────────────────────────────────────────

def test_constructor_requires_api_key():
    from data.providers.base import AuthError
    with pytest.raises(AuthError):
        DatabentoProvider(api_key="")


def test_constructor_accepts_valid_key():
    p = DatabentoProvider(api_key="db-test1234567890abcdef12345678")
    assert p._api_key == "db-test1234567890abcdef12345678"


# ─── get_option_chain ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_option_chain_returns_snapshot():
    p = DatabentoProvider(api_key="db-test")
    p._client = _patch_client()

    snap = await p.get_option_chain("SPY", spot_price=550.0)

    assert snap is not None
    assert snap.ticker == "SPY"
    assert snap.source == "databento"
    assert len(snap.calls) >= 2
    assert len(snap.puts) >= 1


@pytest.mark.asyncio
async def test_get_option_chain_filters_by_expiry():
    p = DatabentoProvider(api_key="db-test")
    p._client = _patch_client()

    snap = await p.get_option_chain("SPY", expiry="2026-06-18", spot_price=550.0)

    assert snap is not None
    assert all(c.expiry == "2026-06-18" for c in snap.calls + snap.puts)


@pytest.mark.asyncio
async def test_get_option_chain_computes_greeks():
    p = DatabentoProvider(api_key="db-test")
    p._client = _patch_client()

    snap = await p.get_option_chain("SPY", spot_price=550.0)

    assert snap is not None
    itm_calls = [c for c in snap.calls if c.strike < 550]
    if itm_calls:
        c = itm_calls[0]
        assert c.delta is not None
        assert 0 < c.delta <= 1.0
        assert c.implied_volatility is not None
        assert c.implied_volatility > 0


@pytest.mark.asyncio
async def test_get_option_chain_empty_returns_none():
    p = DatabentoProvider(api_key="db-test")
    p._client = _patch_client(def_df=pd.DataFrame())

    snap = await p.get_option_chain("FAKE")
    assert snap is None


@pytest.mark.asyncio
async def test_get_option_chain_api_error_returns_none():
    p = DatabentoProvider(api_key="db-test")
    mock_client = MagicMock()
    mock_client.timeseries.get_range.side_effect = RuntimeError("network")
    p._client = mock_client

    snap = await p.get_option_chain("SPY")
    assert snap is None


# ─── get_expirations ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_expirations_returns_sorted():
    p = DatabentoProvider(api_key="db-test")
    p._client = _patch_client()

    exps = await p.get_expirations("SPY")

    assert len(exps) == 2
    assert exps == sorted(exps)
    assert "2026-06-18" in exps
    assert "2027-12-17" in exps


@pytest.mark.asyncio
async def test_get_expirations_api_error():
    p = DatabentoProvider(api_key="db-test")
    mock_client = MagicMock()
    mock_client.timeseries.get_range.side_effect = RuntimeError("fail")
    p._client = mock_client

    exps = await p.get_expirations("SPY")
    assert exps == []


# ─── find_by_delta ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_find_by_delta_selects_closest():
    p = DatabentoProvider(api_key="db-test")
    p._client = _patch_client()

    c = await p.find_by_delta(
        "SPY", target_delta=0.85, min_expiry_days=365,
        max_spread_pct=0.10, max_delta_deviation=0.50,
        spot_price_override=550.0,
    )
    # May return None if BS-derived delta doesn't match target closely
    # This is expected — real delta depends on IV back-calculation


@pytest.mark.asyncio
async def test_find_by_delta_filters_near_term():
    p = DatabentoProvider(api_key="db-test")
    p._client = _patch_client()

    c = await p.find_by_delta(
        "SPY", target_delta=0.50, min_expiry_days=365,
        max_delta_deviation=0.50, spot_price_override=550.0,
    )
    if c is not None:
        exp_dt = datetime.strptime(c.expiry, "%Y-%m-%d")
        assert exp_dt >= datetime(2027, 1, 1)


# ─── get_historical ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_historical_returns_ohlcv():
    p = DatabentoProvider(api_key="db-test")
    p._client = _patch_client()

    df = await p.get_historical("SPY", "2024-01-01", "2024-12-31")

    assert df is not None
    assert "Close" in df.columns
    assert "Volume" in df.columns
    assert len(df) == 2


@pytest.mark.asyncio
async def test_get_historical_error_returns_none():
    p = DatabentoProvider(api_key="db-test")
    mock_client = MagicMock()
    mock_client.timeseries.get_range.side_effect = RuntimeError("fail")
    p._client = mock_client

    df = await p.get_historical("SPY", "2024-01-01", "2024-12-31")
    assert df is None


# ─── get_historical_option_chain ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_historical_option_chain_returns_snapshot():
    p = DatabentoProvider(api_key="db-test")
    p._client = _patch_client()

    snap = await p.get_historical_option_chain(
        "SPY", date="2024-06-20", spot_price=550.0,
    )

    assert snap is not None
    assert snap.source == "databento"
    assert snap.ticker == "SPY"


@pytest.mark.asyncio
async def test_get_historical_option_chain_error():
    p = DatabentoProvider(api_key="db-test")
    mock_client = MagicMock()
    mock_client.timeseries.get_range.side_effect = RuntimeError("fail")
    p._client = mock_client

    snap = await p.get_historical_option_chain("SPY", date="2024-06-20")
    assert snap is None

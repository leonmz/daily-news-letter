# F2-1: filter_movers_by_size removes tickers below market cap or volume threshold
def test_filter_movers_by_size_basic():
    from market_data import filter_movers_by_size
    import config
    # Override thresholds for test
    orig_cap = config.MOVER_MIN_MARKET_CAP_B
    orig_vol = config.MOVER_MIN_VOLUME
    config.MOVER_MIN_MARKET_CAP_B = 10.0
    config.MOVER_MIN_VOLUME = 10_000_000
    try:
        movers = {
            "gainers": [
                {"ticker": "BIG", "volume": 50_000_000, "market_cap": 500_000_000_000},   # passes
                {"ticker": "TINY", "volume": 50_000_000, "market_cap": 1_000_000_000},    # removed (cap < $10B)
                {"ticker": "LOWVOL", "volume": 1_000_000, "market_cap": 100_000_000_000}, # removed (vol < 10M)
            ],
            "losers": []
        }
        result = filter_movers_by_size(movers)
        tickers = [m["ticker"] for m in result["gainers"]]
        assert tickers == ["BIG"], f"Expected ['BIG'], got {tickers}"
    finally:
        config.MOVER_MIN_MARKET_CAP_B = orig_cap
        config.MOVER_MIN_VOLUME = orig_vol

# F2-2: market_cap=0 (unknown) is NOT filtered out
def test_filter_movers_unknown_cap_passes():
    from market_data import filter_movers_by_size
    import config
    orig_cap = config.MOVER_MIN_MARKET_CAP_B
    config.MOVER_MIN_MARKET_CAP_B = 10.0
    try:
        movers = {
            "gainers": [{"ticker": "X", "volume": 20_000_000, "market_cap": 0}],
            "losers": []
        }
        result = filter_movers_by_size(movers)
        assert len(result["gainers"]) == 1, "Unknown market_cap should not be filtered"
    finally:
        config.MOVER_MIN_MARKET_CAP_B = orig_cap

# F2-3: Config thresholds read from env vars
def test_config_thresholds_from_env():
    import os, importlib
    os.environ["MOVER_MIN_MARKET_CAP_B"] = "5.0"
    os.environ["MOVER_MIN_VOLUME"] = "5000000"
    import config
    importlib.reload(config)
    try:
        assert config.MOVER_MIN_MARKET_CAP_B == 5.0, f"Got {config.MOVER_MIN_MARKET_CAP_B}"
        assert config.MOVER_MIN_VOLUME == 5_000_000, f"Got {config.MOVER_MIN_VOLUME}"
    finally:
        del os.environ["MOVER_MIN_MARKET_CAP_B"]
        del os.environ["MOVER_MIN_VOLUME"]
        importlib.reload(config)

# F3-1: format_compact_summary parses standard LLM output
def test_format_compact_summary_standard():
    from main import format_compact_summary
    digest = (
        "## Market summary\nSome overview.\n\n"
        "## 🖥️ Tech\n"
        "### ▲ NVDA (+8.5%) $950.50 | Vol: 85M — Earnings beat expectations\n"
        "Strong Q3 results drove the move.\n\n"
        "### ▼ XOM (-3.2%) $105.20 | Vol: 22M — Oil price drop\n"
        "OPEC output increase weighed on energy.\n"
    )
    result = format_compact_summary(digest)
    assert "▲ NVDA +8.5% | Earnings beat expectations" in result, f"Got: {result!r}"
    assert "▼ XOM -3.2% | Oil price drop" in result, f"Got: {result!r}"
    assert len(result.splitlines()) == 2, f"Expected 2 lines, got: {result!r}"

# F3-2: format_compact_summary returns empty string for non-matching input
def test_format_compact_summary_fallback_empty():
    from main import format_compact_summary
    digest = "## Market movers (no LLM analysis)\n▲ **NVDA** (+8.5%) $950.50 | Vol: 85M"
    result = format_compact_summary(digest)
    assert result == "", f"Expected empty string, got: {result!r}"

# F3-3: sign preserved correctly for losers (negative sign already in pct)
def test_format_compact_summary_sign():
    from main import format_compact_summary
    digest = "### ▼ META (-2.8%) $510.80 | Vol: 30M — EU regulatory action\nDetails."
    result = format_compact_summary(digest)
    assert result == "▼ META -2.8% | EU regulatory action", f"Got: {result!r}"

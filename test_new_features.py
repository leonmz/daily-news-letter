"""
Tests for new features: yfinance news tier, waterfall, Google HTML strip,
compact summary with company name, fallback summary company name.
All API calls are mocked — no live network traffic.
"""

# N1: fetch_news_yfinance maps yfinance fields to standard format
def test_fetch_news_yfinance_maps_fields():
    from unittest.mock import patch, MagicMock
    from news_fetcher import fetch_news_yfinance
    mock_news = [
        {
            "title": "NVIDIA beats earnings",
            "publisher": "Reuters",
            "link": "https://example.com/1",
            "providerPublishTime": 1712000000,
            "type": "STORY",
        }
    ]
    mock_ticker = MagicMock()
    mock_ticker.news = mock_news
    with patch("news_fetcher.yf.Ticker", return_value=mock_ticker):
        result = fetch_news_yfinance(["NVDA"], limit_per_ticker=3)
    assert "NVDA" in result
    art = result["NVDA"][0]
    assert art["title"] == "NVIDIA beats earnings"
    assert art["source"] == "reuters"
    assert art["url"] == "https://example.com/1"
    assert art["sentiment"] is None
    assert art["description"] == ""
    assert "2024" in art["published_at"]  # timestamp 1712000000 is in 2024


# N2: fetch_news_yfinance skips items with empty title
def test_fetch_news_yfinance_skips_empty_title():
    from unittest.mock import patch, MagicMock
    from news_fetcher import fetch_news_yfinance
    mock_ticker = MagicMock()
    mock_ticker.news = [
        {"title": "", "publisher": "X", "link": "http://x.com", "providerPublishTime": 1712000000},
        {"title": "Real news", "publisher": "Y", "link": "http://y.com", "providerPublishTime": 1712000000},
    ]
    with patch("news_fetcher.yf.Ticker", return_value=mock_ticker):
        result = fetch_news_yfinance(["AAPL"])
    assert len(result.get("AAPL", [])) == 1
    assert result["AAPL"][0]["title"] == "Real news"


# N3: fetch_news_yfinance handles missing providerPublishTime
def test_fetch_news_yfinance_missing_timestamp():
    from unittest.mock import patch, MagicMock
    from news_fetcher import fetch_news_yfinance
    mock_ticker = MagicMock()
    mock_ticker.news = [{"title": "Some news", "publisher": "Z", "link": "http://z.com"}]
    with patch("news_fetcher.yf.Ticker", return_value=mock_ticker):
        result = fetch_news_yfinance(["TSLA"])
    assert result["TSLA"][0]["published_at"] == ""


# N4: waterfall uses yfinance before Google News (Google not called when yfinance has results)
def test_waterfall_yfinance_before_google():
    from unittest.mock import patch, MagicMock
    from news_fetcher import get_news_for_movers
    movers = {"gainers": [{"ticker": "NVDA", "name": "NVIDIA"}], "losers": []}

    yf_result = {"NVDA": [{"title": "YF News", "url": "", "source": "reuters", "description": "", "published_at": "", "sentiment": None}]}
    with patch("news_fetcher.fetch_news_marketaux", return_value={}), \
         patch("news_fetcher.fetch_news_yfinance", return_value=yf_result) as mock_yf, \
         patch("news_fetcher.fetch_news_google", return_value={}) as mock_google:
        result = get_news_for_movers(movers)
    mock_yf.assert_called_once()
    mock_google.assert_not_called()  # yfinance had results, Google skipped
    assert result["NVDA"][0]["title"] == "YF News"


# N5: Google News strips HTML tags from summary/description
def test_google_news_strips_html():
    from unittest.mock import patch, MagicMock
    import feedparser
    from news_fetcher import fetch_news_google

    mock_entry = MagicMock()
    mock_entry.get.side_effect = lambda key, default="": {
        "title": "Stock rises - Reuters",
        "summary": "<ol><li>First item</li><li>Second item</li></ol>",
        "link": "https://example.com",
        "published": "Fri, 04 Apr 2025 10:00:00 GMT",
    }.get(key, default)

    mock_parsed = MagicMock()
    mock_parsed.entries = [mock_entry]

    with patch("news_fetcher.requests.get") as mock_get, \
         patch("news_fetcher.feedparser.parse", return_value=mock_parsed):
        mock_resp = MagicMock()
        mock_resp.content = b""
        mock_get.return_value = mock_resp
        result = fetch_news_google(["AAPL"])

    assert "AAPL" in result
    desc = result["AAPL"][0]["description"]
    assert "<" not in desc, f"HTML tags not stripped: {desc!r}"
    assert "First item" in desc or "Second item" in desc


# N6: format_compact_summary with company name in new format
def test_format_compact_summary_with_company_name():
    from main import format_compact_summary
    digest = (
        "## 🖥️ Tech\n"
        "### ▲ NVDA (NVIDIA Corp) (+8.5%) $950.50 | Vol: 85M — Earnings beat\n"
        "Strong results.\n\n"
        "### ▼ META (Meta Platforms) (-2.8%) $510.80 | Vol: 30M — Regulatory fine\n"
        "EU action.\n"
    )
    result = format_compact_summary(digest)
    assert "▲ NVDA (NVIDIA Corp) +8.5% | Earnings beat" in result
    assert "▼ META (Meta Platforms) -2.8% | Regulatory fine" in result
    assert len(result.splitlines()) == 2


# N7: old format (no company name) still produces output without parens
def test_format_compact_summary_old_format_backward_compat():
    from main import format_compact_summary
    digest = "### ▲ NVDA (+8.5%) $950.50 | Vol: 85M — Earnings beat\nDetails."
    result = format_compact_summary(digest)
    assert result == "▲ NVDA +8.5% | Earnings beat", f"Got: {result!r}"


# N8: _fallback_summary includes company name in mover lines
def test_fallback_summary_includes_company_name():
    from llm_analyzer import _fallback_summary
    movers = {
        "gainers": [{"ticker": "NVDA", "name": "NVIDIA Corp", "price": 950.0, "change_pct": 8.5, "volume": 85_000_000, "sector": "tech"}],
        "losers": [],
    }
    result = _fallback_summary(movers, {})
    assert "NVIDIA Corp" in result, f"Company name missing from: {result!r}"

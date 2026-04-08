"""
Deep Analysis Module — TradingAgents Integration

Runs multi-agent deep analysis on selected top movers using TradingAgents.
Gracefully degrades if TradingAgents is not installed.
"""

import os
import sys
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

# Import guard
try:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "TradingAgent"))
    from tradingagents.graph.trading_graph import TradingAgentsGraph
    from tradingagents.default_config import DEFAULT_CONFIG
    TRADINGAGENTS_AVAILABLE = True
except ImportError:
    TRADINGAGENTS_AVAILABLE = False


def select_tickers(movers: dict, news: dict, max_tickers: int = 3) -> list[str]:
    """Score and select the most interesting tickers for deep analysis.

    Scoring:
    - |change_pct| >= 5%: 3 points
    - |change_pct| >= 3%: 2 points
    - |change_pct| >= 1.5%: 1 point
    - Watchlist ticker: +2
    - Blue chip with big move: +2
    - 3+ news articles: +1
    - Volume > 50M: +1
    """
    from config import WATCHLIST

    scores = {}  # ticker -> (score, data)

    # Score top movers
    for direction in ["gainers", "losers"]:
        for m in movers.get(direction, []):
            ticker = m["ticker"]
            score = 0
            pct = abs(m.get("change_pct", 0))

            if pct >= 5.0:
                score += 3
            elif pct >= 3.0:
                score += 2
            elif pct >= 1.5:
                score += 1

            if ticker in WATCHLIST:
                score += 2

            vol = m.get("volume", 0) or 0
            if vol > 50_000_000:
                score += 1

            article_count = len(news.get(ticker, []))
            if article_count >= 3:
                score += 1

            scores[ticker] = max(scores.get(ticker, (0,))[0], score), m

    # Score blue chips (extra weight for unusual moves)
    for m in movers.get("blue_chips", []):
        ticker = m["ticker"]
        score = 2  # blue chip bonus
        pct = abs(m.get("change_pct", 0))
        if pct >= 5.0:
            score += 3
        elif pct >= 3.0:
            score += 2
        elif pct >= 1.5:
            score += 1

        if ticker in WATCHLIST:
            score += 2

        article_count = len(news.get(ticker, []))
        if article_count >= 3:
            score += 1

        if ticker in scores:
            scores[ticker] = (max(scores[ticker][0], score), scores[ticker][1])
        else:
            scores[ticker] = (score, m)

    # Score watchlist
    for m in movers.get("watchlist", []):
        ticker = m["ticker"]
        score = 2  # watchlist bonus
        pct = abs(m.get("change_pct", 0))
        if pct >= 5.0:
            score += 3
        elif pct >= 3.0:
            score += 2
        elif pct >= 1.5:
            score += 1

        article_count = len(news.get(ticker, []))
        if article_count >= 3:
            score += 1

        if ticker in scores:
            scores[ticker] = (max(scores[ticker][0], score), scores[ticker][1])
        else:
            scores[ticker] = (score, m)

    # Sort by score descending, take top N
    ranked = sorted(scores.items(), key=lambda x: x[1][0], reverse=True)
    selected = [ticker for ticker, (score, _) in ranked[:max_tickers] if score > 0]

    return selected


def _build_ta_config() -> dict:
    """Build TradingAgents config from environment variables."""
    from config import ANTHROPIC_API_KEY, GEMINI_API_KEY

    provider = os.getenv("DEEP_ANALYSIS_LLM_PROVIDER", "anthropic")

    config = DEFAULT_CONFIG.copy()
    config["llm_provider"] = provider
    config["deep_think_llm"] = os.getenv("DEEP_ANALYSIS_DEEP_MODEL", "claude-sonnet-4-20250514")
    config["quick_think_llm"] = os.getenv("DEEP_ANALYSIS_QUICK_MODEL", "claude-haiku-4-5-20251001")
    # Clear OpenAI backend_url — each provider uses its own default endpoint
    config["backend_url"] = None
    config["max_debate_rounds"] = 1
    config["max_risk_discuss_rounds"] = 1
    config["output_language"] = "English"
    config["data_vendors"] = {
        "core_stock_apis": "yfinance",
        "technical_indicators": "yfinance",
        "fundamental_data": "yfinance",
        "news_data": "yfinance",
    }

    # Set API keys in environment for langchain providers
    if provider == "anthropic" and ANTHROPIC_API_KEY:
        os.environ["ANTHROPIC_API_KEY"] = ANTHROPIC_API_KEY
    elif provider == "google" and GEMINI_API_KEY:
        os.environ["GOOGLE_API_KEY"] = GEMINI_API_KEY

    return config


def run_deep_analysis(
    ticker: str, trade_date: str, timeout: int = 300
) -> dict | None:
    """Run TradingAgents deep analysis on a single ticker.

    Returns dict with analysis results, or None on failure/timeout.
    """
    if not TRADINGAGENTS_AVAILABLE:
        return None

    config = _build_ta_config()

    def _run():
        ta = TradingAgentsGraph(debug=False, config=config)
        final_state, decision = ta.propagate(ticker, trade_date)
        return extract_insights(final_state, decision, ticker)

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_run)
            return future.result(timeout=timeout)
    except FuturesTimeoutError:
        print(f"[deep] {ticker}: timed out after {timeout}s")
        return None
    except Exception as e:
        print(f"[deep] {ticker}: error — {e}")
        return None


def extract_insights(final_state: dict, decision: str, ticker: str) -> dict:
    """Extract key insights from TradingAgents final state.

    Returns a structured dict with the decision and key findings per dimension.
    """
    return {
        "ticker": ticker,
        "decision": decision.strip().upper(),
        "market_report": _summarize_report(final_state.get("market_report", "")),
        "sentiment_report": _summarize_report(
            final_state.get("sentiment_report", "")
        ),
        "news_report": _summarize_report(final_state.get("news_report", "")),
        "fundamentals_report": _summarize_report(
            final_state.get("fundamentals_report", "")
        ),
        "risk_assessment": _extract_risk(final_state),
        "full_decision": final_state.get("final_trade_decision", ""),
    }


def _summarize_report(report: str, max_len: int = 150) -> str:
    """Extract the most informative sentence from a report for Telegram."""
    if not report:
        return "N/A"
    # Take first meaningful non-header line
    lines = [l.strip() for l in report.strip().split("\n") if l.strip()]
    summary = ""
    for line in lines:
        # Skip headers, dividers, labels
        if line.startswith("#") or line.startswith("---") or line.startswith("**") and line.endswith("**"):
            continue
        # Skip short labels like "Rating: BUY"
        if len(line) < 20:
            continue
        summary = line
        break
    if not summary:
        summary = lines[0] if lines else "N/A"
    # Strip markdown formatting
    summary = summary.replace("**", "").replace("*", "").strip()
    if len(summary) > max_len:
        summary = summary[:max_len].rsplit(" ", 1)[0] + "..."
    return summary


def _extract_risk(final_state: dict) -> str:
    """Extract risk assessment from risk debate state."""
    risk_state = final_state.get("risk_debate_state", {})
    judge = risk_state.get("judge_decision", "")
    if judge:
        # First sentence of judge's decision
        first_sentence = judge.split(".")[0].strip()
        if len(first_sentence) > 150:
            first_sentence = first_sentence[:150] + "..."
        return first_sentence
    return "N/A"


def format_deep_analysis_section(results: list[dict]) -> str:
    """Format deep analysis results as Telegram-ready markdown.

    Returns empty string if no results.
    """
    if not results:
        return ""

    lines = ["\n---\n\n## Deep Analysis (AI Multi-Agent)\n"]

    decision_emoji = {
        "BUY": "BUY",
        "OVERWEIGHT": "OVERWEIGHT",
        "HOLD": "HOLD",
        "UNDERWEIGHT": "UNDERWEIGHT",
        "SELL": "SELL",
    }

    for r in results:
        decision = r.get("decision", "HOLD")
        label = decision_emoji.get(decision, decision)
        lines.append(f"### {r['ticker']} — {label}")

        if r.get("fundamentals_report") and r["fundamentals_report"] != "N/A":
            lines.append(f"Fundamentals: {r['fundamentals_report']}")
        if r.get("sentiment_report") and r["sentiment_report"] != "N/A":
            lines.append(f"Sentiment: {r['sentiment_report']}")
        if r.get("news_report") and r["news_report"] != "N/A":
            lines.append(f"News: {r['news_report']}")
        if r.get("market_report") and r["market_report"] != "N/A":
            lines.append(f"Technical: {r['market_report']}")
        if r.get("risk_assessment") and r["risk_assessment"] != "N/A":
            lines.append(f"Risk: {r['risk_assessment']}")

        lines.append("")  # blank line between tickers

    lines.append("_Powered by TradingAgents multi-agent framework_")

    return "\n".join(lines)


def run_all_deep_analyses(
    movers: dict, news: dict, max_tickers: int = 3, timeout: int = 300
) -> str:
    """Full deep analysis pipeline: select tickers, analyze, format.

    Returns formatted section string (empty if disabled/unavailable).
    """
    if not TRADINGAGENTS_AVAILABLE:
        print("[deep] TradingAgents not available, skipping")
        return ""

    # Select tickers
    selected = select_tickers(movers, news, max_tickers)
    if not selected:
        print("[deep] No tickers selected for deep analysis")
        return ""

    print(f"[deep] Selected: {', '.join(selected)}")

    # Determine trade date
    from market_data import get_last_trading_day, is_market_open

    if is_market_open():
        trade_date = datetime.now().strftime("%Y-%m-%d")
    else:
        trade_date = get_last_trading_day()

    # Run analysis for each ticker
    results = []
    for ticker in selected:
        print(f"[deep] {ticker}: running...", end=" ", flush=True)
        import time

        start = time.time()
        result = run_deep_analysis(ticker, trade_date, timeout=timeout)
        elapsed = time.time() - start

        if result:
            print(f"done in {elapsed:.0f}s ({result['decision']})")
            results.append(result)
        else:
            print(f"failed after {elapsed:.0f}s")

    print(f"[deep] {len(results)}/{len(selected)} analyses completed")

    return format_deep_analysis_section(results)

import os
from dotenv import load_dotenv

load_dotenv()

# API Keys
FMP_API_KEY = os.getenv("FMP_API_KEY", "")
MARKETAUX_API_KEY = os.getenv("MARKETAUX_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Email delivery (SMTP) — optional, independent of Telegram
EMAIL_ENABLED = os.getenv("EMAIL_ENABLED", "false").lower() == "true"
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT") or "587")  # 465 → implicit SSL, else STARTTLS
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
EMAIL_FROM = os.getenv("EMAIL_FROM", "")  # defaults to SMTP_USERNAME if empty
EMAIL_TO = os.getenv("EMAIL_TO", "")  # comma-separated recipients

# User watchlist (comma-separated tickers, max 10)
WATCHLIST = [t.strip().upper() for t in os.getenv("WATCHLIST", "").split(",") if t.strip()][:10]

# Top movers filtering (exclude small caps)
MOVER_MIN_MARKET_CAP_B = float(os.getenv("MOVER_MIN_MARKET_CAP_B", "10.0"))  # $10B minimum market cap
MOVER_MIN_VOLUME = int(os.getenv("MOVER_MIN_VOLUME", "10000000"))  # 10M minimum daily volume

# Deep Analysis (TradingAgents)
DEEP_ANALYSIS_ENABLED = os.getenv("DEEP_ANALYSIS_ENABLED", "false").lower() == "true"
DEEP_ANALYSIS_MAX_TICKERS = int(os.getenv("DEEP_ANALYSIS_MAX_TICKERS", "3"))
DEEP_ANALYSIS_TIMEOUT = int(os.getenv("DEEP_ANALYSIS_TIMEOUT", "300"))

# Top blue chip tickers by market cap
TOP_BLUE_CHIPS = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOG",
    "META", "TSLA", "BRK-B", "JPM", "V",
]

# FMP base URL
FMP_BASE = "https://financialmodelingprep.com/api/v3"

# Marketaux base URL
MARKETAUX_BASE = "https://api.marketaux.com/v1"

# Sector mapping (GICS)
SECTOR_MAP = {
    "Technology": "tech",
    "Information Technology": "tech",
    "Communication Services": "tech",
    "Healthcare": "healthcare",
    "Health Care": "healthcare",
    "Financial Services": "financials",
    "Financials": "financials",
    "Consumer Cyclical": "consumer",
    "Consumer Defensive": "consumer",
    "Consumer Discretionary": "consumer",
    "Consumer Staples": "consumer",
    "Industrials": "industrials",
    "Energy": "energy",
    "Real Estate": "real_estate",
    "Utilities": "utilities",
    "Basic Materials": "materials",
    "Materials": "materials",
}

SECTOR_DISPLAY = {
    "tech": "🖥️ Tech",
    "healthcare": "🏥 Healthcare",
    "financials": "🏦 Financials",
    "consumer": "🛒 Consumer",
    "industrials": "🏭 Industrials",
    "energy": "⚡ Energy",
    "real_estate": "🏠 Real Estate",
    "utilities": "💡 Utilities",
    "materials": "🧱 Materials",
}

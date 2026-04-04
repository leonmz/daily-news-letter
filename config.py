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

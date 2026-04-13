"""Provider configuration — loads API keys from environment."""

import os
from dotenv import load_dotenv

load_dotenv()

# Alpaca Markets
ALPACA_API_KEY = os.getenv("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "")

# Finnhub
FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY", "")

# FRED
FRED_API_KEY = os.getenv("FRED_API_KEY", "")

# yfinance needs no key

# Market cap / volume filters for top movers
MOVER_MIN_MARKET_CAP_B = float(os.getenv("MOVER_MIN_MARKET_CAP_B", "10.0"))
MOVER_MIN_VOLUME = int(os.getenv("MOVER_MIN_VOLUME", "10000000"))

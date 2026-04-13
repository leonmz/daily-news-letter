from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class StockQuote:
    ticker: str
    price: float
    change: float          # absolute price change
    change_pct: float      # percentage change
    volume: int
    market_cap: Optional[float]  # in billions
    timestamp: datetime
    source: str            # which provider served this data
    delayed: bool = False  # True if quote is delayed (e.g. yfinance)
    currency: str = "USD"
    company_name: Optional[str] = None
    sector: Optional[str] = None


@dataclass
class OptionContract:
    strike: float
    expiry: str            # YYYY-MM-DD
    option_type: str       # "call" or "put"
    last_price: float
    bid: float
    ask: float
    volume: int
    open_interest: int
    implied_volatility: Optional[float] = None
    delta: Optional[float] = None
    gamma: Optional[float] = None
    theta: Optional[float] = None
    vega: Optional[float] = None


@dataclass
class OptionsSnapshot:
    ticker: str
    expirations: list[str]
    calls: list[OptionContract] = field(default_factory=list)
    puts: list[OptionContract] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.utcnow)
    source: str = "yfinance"

    @property
    def has_greeks(self) -> bool:
        all_contracts = self.calls + self.puts
        return any(c.delta is not None for c in all_contracts)

    @property
    def total_contracts(self) -> int:
        return len(self.calls) + len(self.puts)

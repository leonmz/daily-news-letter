from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class AlertEvent:
    alert_type: str        # "price_move", "volume_spike", "earnings", "news_sentiment"
    ticker: Optional[str]
    message: str
    severity: str          # "info", "warning", "critical"
    triggered_at: datetime
    source: str            # which provider detected it
    value: Optional[float] = None    # the triggering value (e.g. % move)
    threshold: Optional[float] = None  # the configured threshold
    metadata: Optional[dict] = None

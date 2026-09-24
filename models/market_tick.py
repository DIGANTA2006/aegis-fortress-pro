from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class MarketTick:
    symbol: str
    exchange: str
    bid: float
    ask: float
    last: float
    volume: float = 0.0
    timestamp: datetime = field(default_factory=datetime.utcnow)
    raw: Any = None

    @property
    def mid_price(self) -> float:
        if self.bid > 0 and self.ask > 0:
            return (self.bid + self.ask) / 2.0

        if self.last > 0:
            return self.last

        return 0.0

    @property
    def spread(self) -> float:
        if self.bid > 0 and self.ask > 0:
            return self.ask - self.bid

        return 0.0

    @property
    def spread_bps(self) -> float:
        mid = self.mid_price

        if mid <= 0:
            return 0.0

        return (self.spread / mid) * 10000.0

    def is_valid(self) -> bool:
        return (
            bool(self.symbol)
            and bool(self.exchange)
            and self.last > 0
            and self.bid >= 0
            and self.ask >= 0
        )

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "exchange": self.exchange,
            "bid": self.bid,
            "ask": self.ask,
            "last": self.last,
            "volume": self.volume,
            "mid_price": self.mid_price,
            "spread": self.spread,
            "spread_bps": self.spread_bps,
            "timestamp": self.timestamp.isoformat(),
        }

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class OrderBookLevel:
    price: float
    quantity: float

    def to_dict(self) -> dict:
        return {
            "price": self.price,
            "quantity": self.quantity,
        }


@dataclass
class OrderBookSnapshot:
    symbol: str
    exchange: str
    bids: list[OrderBookLevel]
    asks: list[OrderBookLevel]
    sequence: int | None = None
    timestamp: datetime = field(default_factory=datetime.utcnow)
    raw: Any = None

    @property
    def best_bid(self) -> float:
        if not self.bids:
            return 0.0

        return self.bids[0].price

    @property
    def best_ask(self) -> float:
        if not self.asks:
            return 0.0

        return self.asks[0].price

    @property
    def spread(self) -> float:
        if self.best_bid <= 0 or self.best_ask <= 0:
            return 0.0

        return self.best_ask - self.best_bid

    @property
    def mid_price(self) -> float:
        if self.best_bid <= 0 or self.best_ask <= 0:
            return 0.0

        return (self.best_bid + self.best_ask) / 2.0

    @property
    def bid_depth(self) -> float:
        return sum(level.quantity for level in self.bids)

    @property
    def ask_depth(self) -> float:
        return sum(level.quantity for level in self.asks)

    @property
    def imbalance(self) -> float:
        total_depth = self.bid_depth + self.ask_depth

        if total_depth <= 0:
            return 0.0

        return (self.bid_depth - self.ask_depth) / total_depth

    def is_valid(self) -> bool:
        return (
            bool(self.symbol)
            and bool(self.exchange)
            and len(self.bids) > 0
            and len(self.asks) > 0
            and self.best_bid > 0
            and self.best_ask > 0
        )

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "exchange": self.exchange,
            "bids": [level.to_dict() for level in self.bids],
            "asks": [level.to_dict() for level in self.asks],
            "sequence": self.sequence,
            "best_bid": self.best_bid,
            "best_ask": self.best_ask,
            "spread": self.spread,
            "mid_price": self.mid_price,
            "bid_depth": self.bid_depth,
            "ask_depth": self.ask_depth,
            "imbalance": self.imbalance,
            "timestamp": self.timestamp.isoformat(),
        }

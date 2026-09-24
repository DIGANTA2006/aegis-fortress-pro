from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import uuid

from models.order import Order, OrderSide, OrderType


@dataclass
class TradeSignal:
    symbol: str
    side: OrderSide
    quantity: float
    order_type: OrderType = OrderType.MARKET
    price: Optional[float] = None
    strategy_id: Optional[str] = None
    reason: Optional[str] = None
    confidence: Optional[float] = None
    signal_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def validate(self) -> None:
        if not self.symbol:
            raise ValueError("Signal symbol is required")

        if self.quantity <= 0:
            raise ValueError("Signal quantity must be positive")

        if self.order_type == OrderType.LIMIT:
            if self.price is None or self.price <= 0:
                raise ValueError("Limit signal requires a positive price")

        if self.confidence is not None:
            if not 0.0 <= self.confidence <= 1.0:
                raise ValueError("Signal confidence must be in [0, 1]")

    def to_order(self) -> Order:
        self.validate()

        return Order(
            symbol=self.symbol,
            side=self.side,
            quantity=self.quantity,
            order_type=self.order_type,
            price=self.price,
            strategy_id=self.strategy_id,
        )

    def to_dict(self) -> dict:
        return {
            "signal_id": self.signal_id,
            "symbol": self.symbol,
            "side": self.side.value,
            "quantity": self.quantity,
            "order_type": self.order_type.value,
            "price": self.price,
            "strategy_id": self.strategy_id,
            "reason": self.reason,
            "confidence": self.confidence,
            "timestamp": self.timestamp.isoformat(),
        }

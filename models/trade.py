from dataclasses import dataclass, field
from datetime import datetime
import uuid


@dataclass
class Trade:
    symbol: str
    side: str
    quantity: float
    price: float
    exchange: str

    pnl: float = 0.0
    fee: float = 0.0

    strategy_id: str | None = None
    order_id: str | None = None

    trade_id: str = field(
        default_factory=lambda: str(uuid.uuid4())
    )

    timestamp: datetime = field(
        default_factory=datetime.utcnow
    )

    def notional(self) -> float:
        return self.quantity * self.price

    def to_dict(self) -> dict:
        return {
            "trade_id": self.trade_id,
            "order_id": self.order_id,
            "symbol": self.symbol,
            "side": self.side,
            "quantity": self.quantity,
            "price": self.price,
            "exchange": self.exchange,
            "pnl": self.pnl,
            "fee": self.fee,
            "strategy_id": self.strategy_id,
            "timestamp": self.timestamp.isoformat(),
        }
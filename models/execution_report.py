from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional
import uuid

from models.order import OrderStatus


@dataclass
class ExecutionReport:
    symbol: str
    side: str
    requested_quantity: float
    filled_quantity: float
    average_fill_price: float
    status: OrderStatus
    exchange: str

    exchange_order_id: Optional[str] = None
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    fee: float = 0.0
    raw_response: Optional[Any] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def has_fill(self) -> bool:
        return self.filled_quantity > 0

    def is_terminal(self) -> bool:
        return self.status in {
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.FAILED,
            OrderStatus.REJECTED,
        }

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "side": self.side,
            "requested_quantity": self.requested_quantity,
            "filled_quantity": self.filled_quantity,
            "average_fill_price": self.average_fill_price,
            "status": self.status.value,
            "exchange": self.exchange,
            "exchange_order_id": self.exchange_order_id,
            "correlation_id": self.correlation_id,
            "fee": self.fee,
            "timestamp": self.timestamp.isoformat(),
        }

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from datetime import datetime
import uuid


class OrderSide(str, Enum):

    BUY = 'BUY'
    SELL = 'SELL'


class OrderType(str, Enum):

    MARKET = 'MARKET'
    LIMIT = 'LIMIT'


class OrderStatus(str, Enum):

    CREATED = 'CREATED'
    VALIDATED = 'VALIDATED'
    ROUTED = 'ROUTED'
    SUBMITTED = 'SUBMITTED'
    PARTIALLY_FILLED = 'PARTIALLY_FILLED'
    FILLED = 'FILLED'
    CANCELLED = 'CANCELLED'
    FAILED = 'FAILED'
    REJECTED = 'REJECTED'


@dataclass
class Order:

    symbol: str
    side: OrderSide
    quantity: float
    order_type: OrderType

    price: Optional[float] = None

    exchange: Optional[str] = None

    status: OrderStatus = (
        OrderStatus.CREATED
    )

    filled_quantity: float = 0.0

    average_fill_price: float = 0.0

    exchange_order_id: Optional[str] = None

    strategy_id: Optional[str] = None

    correlation_id: str = field(
        default_factory=lambda: str(uuid.uuid4())
    )

    created_at: datetime = field(
        default_factory=datetime.utcnow
    )

    updated_at: datetime = field(
        default_factory=datetime.utcnow
    )

    def is_complete(self):

        return self.status in [

            OrderStatus.FILLED,

            OrderStatus.CANCELLED,

            OrderStatus.REJECTED,

            OrderStatus.FAILED
        ]

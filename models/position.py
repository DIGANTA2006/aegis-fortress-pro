from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Position:
    symbol: str
    quantity: float = 0.0
    average_entry: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    updated_at: datetime = field(default_factory=datetime.utcnow)

    @property
    def side(self) -> str:
        if self.quantity > 0:
            return "LONG"
        if self.quantity < 0:
            return "SHORT"
        return "FLAT"

    def exposure(self, mark_price: Optional[float] = None) -> float:
        price = self.average_entry if mark_price is None else mark_price
        return abs(self.quantity * price)

    def signed_notional(self, mark_price: Optional[float] = None) -> float:
        price = self.average_entry if mark_price is None else mark_price
        return self.quantity * price

    def mark_to_market(self, mark_price: float) -> float:
        if self.quantity > 0:
            self.unrealized_pnl = (mark_price - self.average_entry) * self.quantity
        elif self.quantity < 0:
            self.unrealized_pnl = (self.average_entry - mark_price) * abs(self.quantity)
        else:
            self.unrealized_pnl = 0.0

        self.updated_at = datetime.utcnow()
        return self.unrealized_pnl

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "quantity": self.quantity,
            "average_entry": self.average_entry,
            "realized_pnl": self.realized_pnl,
            "unrealized_pnl": self.unrealized_pnl,
            "side": self.side,
            "updated_at": self.updated_at.isoformat(),
        }

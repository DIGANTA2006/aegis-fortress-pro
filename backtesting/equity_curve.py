from dataclasses import dataclass
from datetime import datetime


@dataclass
class EquityPoint:
    timestamp: datetime
    equity: float
    realized_pnl: float
    unrealized_pnl: float
    gross_exposure: float
    net_exposure: float

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "equity": self.equity,
            "realized_pnl": self.realized_pnl,
            "unrealized_pnl": self.unrealized_pnl,
            "gross_exposure": self.gross_exposure,
            "net_exposure": self.net_exposure,
        }


class EquityCurveTracker:
    def __init__(
        self,
        initial_equity: float,
    ) -> None:
        if initial_equity <= 0:
            raise ValueError("initial_equity must be positive")

        self.initial_equity = initial_equity
        self.points: list[EquityPoint] = []

    def record(
        self,
        timestamp: datetime,
        realized_pnl: float,
        unrealized_pnl: float,
        gross_exposure: float,
        net_exposure: float,
    ) -> EquityPoint:
        equity = (
            self.initial_equity
            + realized_pnl
            + unrealized_pnl
        )

        point = EquityPoint(
            timestamp=timestamp,
            equity=equity,
            realized_pnl=realized_pnl,
            unrealized_pnl=unrealized_pnl,
            gross_exposure=gross_exposure,
            net_exposure=net_exposure,
        )

        self.points.append(point)
        return point

    def values(self) -> list[float]:
        return [
            point.equity
            for point in self.points
        ]

    def to_dict(self) -> list[dict]:
        return [
            point.to_dict()
            for point in self.points
        ]

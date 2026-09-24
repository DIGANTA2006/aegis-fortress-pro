import inspect
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class PositionMismatch:
    symbol: str
    local_quantity: float
    exchange_quantity: float
    difference: float
    relative_difference: float
    severity: str

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "local_quantity": self.local_quantity,
            "exchange_quantity": self.exchange_quantity,
            "difference": self.difference,
            "relative_difference": self.relative_difference,
            "severity": self.severity,
        }


@dataclass
class ReconciliationReport:
    mismatches: list[PositionMismatch] = field(default_factory=list)
    checked_at: datetime = field(default_factory=datetime.utcnow)

    @property
    def is_clean(self) -> bool:
        return len(self.mismatches) == 0

    def critical_count(self) -> int:
        return sum(1 for item in self.mismatches if item.severity == "CRITICAL")

    def to_dict(self) -> dict:
        return {
            "is_clean": self.is_clean,
            "critical_count": self.critical_count(),
            "checked_at": self.checked_at.isoformat(),
            "mismatches": [item.to_dict() for item in self.mismatches],
        }


class PositionReconciler:
    def __init__(
        self,
        absolute_tolerance: float = 1e-8,
        critical_relative_difference: float = 0.20,
    ) -> None:
        self.absolute_tolerance = absolute_tolerance
        self.critical_relative_difference = critical_relative_difference

    def compare(
        self,
        local_positions: dict[str, float],
        exchange_positions: dict[str, float],
    ) -> ReconciliationReport:
        report = ReconciliationReport()
        symbols = set(local_positions) | set(exchange_positions)

        for symbol in sorted(symbols):
            local_qty = float(local_positions.get(symbol, 0.0))
            exchange_qty = float(exchange_positions.get(symbol, 0.0))
            difference = exchange_qty - local_qty

            if abs(difference) <= self.absolute_tolerance:
                continue

            denominator = max(abs(local_qty), abs(exchange_qty), self.absolute_tolerance)
            relative_difference = abs(difference) / denominator

            severity = (
                "CRITICAL"
                if relative_difference >= self.critical_relative_difference
                else "WARNING"
            )

            report.mismatches.append(
                PositionMismatch(
                    symbol=symbol,
                    local_quantity=local_qty,
                    exchange_quantity=exchange_qty,
                    difference=difference,
                    relative_difference=relative_difference,
                    severity=severity,
                )
            )

        return report

    async def reconcile_with_exchange(
        self,
        exchange: Any,
        local_positions: dict[str, float],
    ) -> ReconciliationReport:
        raw_positions = exchange.fetch_positions()
        if inspect.isawaitable(raw_positions):
            raw_positions = await raw_positions

        normalized = self.normalize_exchange_positions(raw_positions)
        return self.compare(local_positions, normalized)

    def normalize_exchange_positions(self, raw_positions: Any) -> dict[str, float]:
        if raw_positions is None:
            return {}

        if isinstance(raw_positions, dict):
            if all(isinstance(v, (int, float)) for v in raw_positions.values()):
                return {str(k): float(v) for k, v in raw_positions.items()}

            normalized: dict[str, float] = {}
            for symbol, payload in raw_positions.items():
                quantity = self._extract_quantity(payload)
                if quantity is not None:
                    normalized[str(symbol)] = quantity
            return normalized

        if isinstance(raw_positions, list):
            normalized: dict[str, float] = {}
            for payload in raw_positions:
                if not isinstance(payload, dict):
                    continue

                symbol = payload.get("symbol") or payload.get("pair")
                quantity = self._extract_quantity(payload)

                if symbol and quantity is not None:
                    normalized[str(symbol)] = quantity

            return normalized

        raise TypeError("Unsupported exchange positions payload")

    def _extract_quantity(self, payload: Any) -> float | None:
        if isinstance(payload, (int, float)):
            return float(payload)

        if not isinstance(payload, dict):
            return None

        candidates = (
            "quantity",
            "size",
            "contracts",
            "positionAmt",
            "amount",
            "net",
        )

        for key in candidates:
            value = payload.get(key)
            if isinstance(value, (int, float)):
                return float(value)
            if isinstance(value, str):
                try:
                    return float(value)
                except ValueError:
                    continue

        return None

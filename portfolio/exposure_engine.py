from dataclasses import dataclass
from typing import Dict

from models.position import Position


@dataclass
class ExposureSnapshot:
    gross_exposure: float
    net_exposure: float
    long_exposure: float
    short_exposure: float
    symbol_exposure: Dict[str, float]
    symbol_weights: Dict[str, float]

    def to_dict(self) -> dict:
        return {
            "gross_exposure": self.gross_exposure,
            "net_exposure": self.net_exposure,
            "long_exposure": self.long_exposure,
            "short_exposure": self.short_exposure,
            "symbol_exposure": self.symbol_exposure,
            "symbol_weights": self.symbol_weights,
        }


class ExposureEngine:
    def calculate(
        self,
        positions: dict[str, Position],
        mark_prices: dict[str, float],
    ) -> ExposureSnapshot:
        long_exposure = 0.0
        short_exposure = 0.0
        net_exposure = 0.0
        symbol_exposure: dict[str, float] = {}

        for symbol, position in positions.items():
            mark_price = mark_prices.get(symbol, position.average_entry)
            signed_notional = position.signed_notional(mark_price)
            absolute_notional = abs(signed_notional)

            symbol_exposure[symbol] = absolute_notional
            net_exposure += signed_notional

            if signed_notional >= 0:
                long_exposure += signed_notional
            else:
                short_exposure += abs(signed_notional)

        gross_exposure = long_exposure + short_exposure

        if gross_exposure > 0:
            symbol_weights = {
                symbol: exposure / gross_exposure
                for symbol, exposure in symbol_exposure.items()
            }
        else:
            symbol_weights = {
                symbol: 0.0
                for symbol in symbol_exposure
            }

        return ExposureSnapshot(
            gross_exposure=gross_exposure,
            net_exposure=net_exposure,
            long_exposure=long_exposure,
            short_exposure=short_exposure,
            symbol_exposure=symbol_exposure,
            symbol_weights=symbol_weights,
        )

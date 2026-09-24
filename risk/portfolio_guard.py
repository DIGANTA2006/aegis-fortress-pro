from dataclasses import dataclass

from portfolio.exposure_engine import ExposureSnapshot


@dataclass
class RiskBreach:
    code: str
    message: str
    severity: str

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "message": self.message,
            "severity": self.severity,
        }


class PortfolioGuard:
    def __init__(
        self,
        max_gross_exposure: float,
        max_net_exposure: float,
        max_symbol_weight: float,
    ) -> None:
        if max_gross_exposure <= 0:
            raise ValueError("max_gross_exposure must be positive")
        if max_net_exposure <= 0:
            raise ValueError("max_net_exposure must be positive")
        if not 0 < max_symbol_weight <= 1:
            raise ValueError("max_symbol_weight must be in (0, 1]")

        self.max_gross_exposure = max_gross_exposure
        self.max_net_exposure = max_net_exposure
        self.max_symbol_weight = max_symbol_weight

    def validate(self, snapshot: ExposureSnapshot) -> list[RiskBreach]:
        breaches: list[RiskBreach] = []

        if snapshot.gross_exposure > self.max_gross_exposure:
            breaches.append(
                RiskBreach(
                    code="GROSS_EXPOSURE_LIMIT",
                    message=(
                        f"Gross exposure {snapshot.gross_exposure:.8f} "
                        f"exceeds limit {self.max_gross_exposure:.8f}"
                    ),
                    severity="CRITICAL",
                )
            )

        if abs(snapshot.net_exposure) > self.max_net_exposure:
            breaches.append(
                RiskBreach(
                    code="NET_EXPOSURE_LIMIT",
                    message=(
                        f"Net exposure {snapshot.net_exposure:.8f} "
                        f"exceeds limit {self.max_net_exposure:.8f}"
                    ),
                    severity="CRITICAL",
                )
            )

        for symbol, weight in snapshot.symbol_weights.items():
            if weight > self.max_symbol_weight:
                breaches.append(
                    RiskBreach(
                        code="SYMBOL_WEIGHT_LIMIT",
                        message=(
                            f"{symbol} exposure weight {weight:.4f} "
                            f"exceeds limit {self.max_symbol_weight:.4f}"
                        ),
                        severity="HIGH",
                    )
                )

        return breaches

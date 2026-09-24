from dataclasses import dataclass, field

from models.order import Order, OrderSide
from portfolio.exposure_engine import ExposureEngine
from risk.portfolio_guard import PortfolioGuard


@dataclass
class RiskDecision:
    allowed: bool
    reasons: list[str] = field(default_factory=list)
    projected_gross_exposure: float = 0.0
    projected_net_exposure: float = 0.0
    projected_symbol_weight: float = 0.0

    def to_dict(self) -> dict:
        return {
            "allowed": self.allowed,
            "reasons": self.reasons,
            "projected_gross_exposure": self.projected_gross_exposure,
            "projected_net_exposure": self.projected_net_exposure,
            "projected_symbol_weight": self.projected_symbol_weight,
        }


class PreTradeRiskValidator:
    def __init__(
        self,
        exposure_engine: ExposureEngine,
        portfolio_guard: PortfolioGuard,
        max_order_notional: float,
        min_order_notional: float = 0.0,
    ) -> None:
        if max_order_notional <= 0:
            raise ValueError("max_order_notional must be positive")

        if min_order_notional < 0:
            raise ValueError("min_order_notional cannot be negative")

        if min_order_notional > max_order_notional:
            raise ValueError("min_order_notional cannot exceed max_order_notional")

        self.exposure_engine = exposure_engine
        self.portfolio_guard = portfolio_guard
        self.max_order_notional = max_order_notional
        self.min_order_notional = min_order_notional

    def validate(
        self,
        order: Order,
        reference_price: float,
        positions: dict,
        mark_prices: dict[str, float],
        min_order_notional_override: float | None = None,
    ) -> RiskDecision:
        reasons: list[str] = []

        if reference_price <= 0:
            reasons.append("Reference price must be positive")

        if order.quantity <= 0:
            reasons.append("Order quantity must be positive")

        order_notional = order.quantity * reference_price

        effective_min_order_notional = self.min_order_notional

        if min_order_notional_override is not None:
            effective_min_order_notional = max(
                effective_min_order_notional,
                min_order_notional_override,
            )

        if (
            effective_min_order_notional > 0
            and order_notional < effective_min_order_notional
        ):
            reasons.append(
                f"Order notional {order_notional:.8f} is below minimum "
                f"{effective_min_order_notional:.8f}"
            )

        if order_notional > self.max_order_notional:
            reasons.append(
                f"Order notional {order_notional:.8f} exceeds limit "
                f"{self.max_order_notional:.8f}"
            )

        snapshot = self.exposure_engine.calculate(
            positions=positions,
            mark_prices=mark_prices,
        )

        current_position = positions.get(order.symbol)
        current_signed_notional = 0.0

        if current_position is not None:
            symbol_mark = mark_prices.get(
                order.symbol,
                current_position.average_entry,
            )
            current_signed_notional = current_position.signed_notional(symbol_mark)

        incoming_signed_notional = (
            order_notional
            if order.side == OrderSide.BUY
            else -order_notional
        )

        projected_symbol_signed = (
            current_signed_notional + incoming_signed_notional
        )

        projected_net = (
            snapshot.net_exposure + incoming_signed_notional
        )

        projected_gross = (
            snapshot.gross_exposure
            - abs(current_signed_notional)
            + abs(projected_symbol_signed)
        )

        projected_symbol_weight = (
            abs(projected_symbol_signed) / projected_gross
            if projected_gross > 0
            else 0.0
        )

        if projected_gross > self.portfolio_guard.max_gross_exposure:
            reasons.append(
                f"Projected gross exposure {projected_gross:.8f} exceeds limit "
                f"{self.portfolio_guard.max_gross_exposure:.8f}"
            )

        if abs(projected_net) > self.portfolio_guard.max_net_exposure:
            reasons.append(
                f"Projected net exposure {projected_net:.8f} exceeds limit "
                f"{self.portfolio_guard.max_net_exposure:.8f}"
            )

        if projected_symbol_weight > self.portfolio_guard.max_symbol_weight:
            reasons.append(
                f"Projected symbol weight {projected_symbol_weight:.4f} exceeds limit "
                f"{self.portfolio_guard.max_symbol_weight:.4f}"
            )

        return RiskDecision(
            allowed=len(reasons) == 0,
            reasons=reasons,
            projected_gross_exposure=projected_gross,
            projected_net_exposure=projected_net,
            projected_symbol_weight=projected_symbol_weight,
        )

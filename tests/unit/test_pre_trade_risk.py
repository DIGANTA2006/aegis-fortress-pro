from models.order import (
    Order,
    OrderSide,
    OrderType,
)
from portfolio.exposure_engine import ExposureEngine
from risk.portfolio_guard import PortfolioGuard
from risk.pre_trade_risk import PreTradeRiskValidator


def test_pre_trade_risk_allows_safe_order():
    validator = PreTradeRiskValidator(
        exposure_engine=ExposureEngine(),
        portfolio_guard=PortfolioGuard(
            max_gross_exposure=5000.0,
            max_net_exposure=5000.0,
            max_symbol_weight=1.0,
        ),
        max_order_notional=2000.0,
    )

    order = Order(
        symbol="BTC/USDT",
        side=OrderSide.BUY,
        quantity=1.0,
        order_type=OrderType.MARKET,
    )

    decision = validator.validate(
        order=order,
        reference_price=1000.0,
        positions={},
        mark_prices={},
    )

    assert decision.allowed is True
    assert decision.reasons == []


def test_pre_trade_risk_rejects_oversized_order():
    validator = PreTradeRiskValidator(
        exposure_engine=ExposureEngine(),
        portfolio_guard=PortfolioGuard(
            max_gross_exposure=5000.0,
            max_net_exposure=5000.0,
            max_symbol_weight=1.0,
        ),
        max_order_notional=500.0,
    )

    order = Order(
        symbol="BTC/USDT",
        side=OrderSide.BUY,
        quantity=1.0,
        order_type=OrderType.MARKET,
    )

    decision = validator.validate(
        order=order,
        reference_price=1000.0,
        positions={},
        mark_prices={},
    )

    assert decision.allowed is False
    assert any(
        "Order notional" in reason
        for reason in decision.reasons
    )

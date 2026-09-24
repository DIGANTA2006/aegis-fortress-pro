"""Unit tests for ExecutionValidator."""
import pytest
from models.order import Order, OrderSide, OrderType
from execution.execution_validator import ExecutionValidator


def _order(**kwargs):
    defaults = dict(symbol="BTC/USDT", side=OrderSide.BUY, quantity=0.01, order_type=OrderType.MARKET)
    defaults.update(kwargs)
    return Order(**defaults)


def test_valid_market_order():
    v = ExecutionValidator()
    assert v.validate(_order()) is True


def test_missing_symbol_raises():
    v = ExecutionValidator()
    with pytest.raises(ValueError, match="Missing symbol"):
        v.validate(_order(symbol=""))


def test_zero_quantity_raises():
    v = ExecutionValidator()
    with pytest.raises(ValueError, match="Invalid quantity"):
        v.validate(_order(quantity=0))


def test_limit_order_without_price_raises():
    v = ExecutionValidator()
    with pytest.raises(ValueError, match="Limit order requires price"):
        v.validate(_order(order_type=OrderType.LIMIT, price=None))


def test_limit_order_with_price_passes():
    v = ExecutionValidator()
    assert v.validate(_order(order_type=OrderType.LIMIT, price=50000.0)) is True

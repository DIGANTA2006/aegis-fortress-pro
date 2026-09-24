"""Unit tests for Order and Trade models."""
import pytest
from models.order import Order, OrderSide, OrderType, OrderStatus
from models.trade import Trade


def test_order_creation():
    order = Order(
        symbol="BTC/USDT",
        side=OrderSide.BUY,
        quantity=0.01,
        order_type=OrderType.MARKET,
    )
    assert order.symbol == "BTC/USDT"
    assert order.status == OrderStatus.CREATED
    assert order.correlation_id is not None


def test_order_is_complete_false_on_create():
    order = Order(symbol="ETH/USDT", side=OrderSide.SELL, quantity=1.0, order_type=OrderType.MARKET)
    assert not order.is_complete()


def test_order_is_complete_true_when_filled():
    order = Order(symbol="BTC/USDT", side=OrderSide.BUY, quantity=0.1, order_type=OrderType.MARKET)
    order.status = OrderStatus.FILLED
    assert order.is_complete()


def test_order_is_complete_true_when_cancelled():
    order = Order(symbol="BTC/USDT", side=OrderSide.BUY, quantity=0.1, order_type=OrderType.MARKET)
    order.status = OrderStatus.CANCELLED
    assert order.is_complete()


def test_trade_creation():
    trade = Trade(symbol="BTC/USDT", side="BUY", quantity=0.01, price=60000.0, exchange="binance")
    assert trade.pnl == 0.0
    assert trade.fee == 0.0

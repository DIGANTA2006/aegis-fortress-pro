import pytest

from execution.order_state_machine import (
    InvalidStateTransition,
    OrderStateMachine,
)
from models.order import (
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
)


def build_order() -> Order:
    return Order(
        symbol="BTC/USDT",
        side=OrderSide.BUY,
        quantity=1.0,
        order_type=OrderType.MARKET,
    )


def test_order_state_machine_valid_lifecycle():
    order = build_order()
    machine = OrderStateMachine()

    machine.transition(
        order,
        OrderStatus.VALIDATED,
    )

    machine.transition(
        order,
        OrderStatus.ROUTED,
    )

    machine.transition(
        order,
        OrderStatus.SUBMITTED,
    )

    machine.transition(
        order,
        OrderStatus.FILLED,
    )

    assert order.status == OrderStatus.FILLED
    assert order.is_complete() is True


def test_order_state_machine_rejects_invalid_transition():
    order = build_order()
    machine = OrderStateMachine()

    with pytest.raises(InvalidStateTransition):
        machine.transition(
            order,
            OrderStatus.FILLED,
        )

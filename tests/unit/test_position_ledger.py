import pytest

from portfolio.position_ledger import PositionLedger


def test_position_ledger_weighted_average_and_realized_pnl():
    ledger = PositionLedger()

    ledger.apply_fill(
        symbol="BTC/USDT",
        side="BUY",
        quantity=2.0,
        price=100.0,
        exchange="SIM",
    )

    ledger.apply_fill(
        symbol="BTC/USDT",
        side="BUY",
        quantity=1.0,
        price=110.0,
        exchange="SIM",
    )

    position = ledger.get_position("BTC/USDT")

    assert position is not None
    assert position.quantity == pytest.approx(3.0)
    assert position.average_entry == pytest.approx(103.3333333333)

    close_trade = ledger.apply_fill(
        symbol="BTC/USDT",
        side="SELL",
        quantity=1.0,
        price=120.0,
        exchange="SIM",
    )

    position = ledger.get_position("BTC/USDT")

    assert close_trade.pnl == pytest.approx(16.6666666667)
    assert position is not None
    assert position.quantity == pytest.approx(2.0)
    assert ledger.realized_pnl() == pytest.approx(16.6666666667)


def test_position_ledger_keeps_realized_pnl_after_full_close():
    ledger = PositionLedger()

    ledger.apply_fill(
        symbol="ETH/USDT",
        side="BUY",
        quantity=1.0,
        price=100.0,
        exchange="SIM",
    )

    ledger.apply_fill(
        symbol="ETH/USDT",
        side="SELL",
        quantity=1.0,
        price=125.0,
        exchange="SIM",
    )

    assert ledger.get_position("ETH/USDT") is None
    assert ledger.realized_pnl() == pytest.approx(25.0)

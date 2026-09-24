from portfolio.position_ledger import PositionLedger


def test_position_ledger_restores_saved_open_positions():
    ledger = PositionLedger()

    ledger.restore_snapshot(
        {
            "positions": {
                "SOL/USDT": {
                    "symbol": "SOL/USDT",
                    "quantity": 0.5,
                    "average_entry": 100.0,
                    "realized_pnl": -0.01,
                    "unrealized_pnl": 0.0,
                    "updated_at": "2026-06-23T00:00:00",
                }
            },
            "trade_count": 1,
            "realized_pnl_total": -0.01,
        }
    )

    position = ledger.get_position("SOL/USDT")

    assert position is not None
    assert position.quantity == 0.5
    assert position.average_entry == 100.0
    assert ledger.realized_pnl() == -0.01

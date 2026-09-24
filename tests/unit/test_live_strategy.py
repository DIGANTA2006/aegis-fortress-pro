from portfolio.position_ledger import PositionLedger
from risk.kill_switch import KillSwitch
from models.order import OrderSide
from strategies.mean_reversion_imbalance import MeanReversionImbalanceStrategy


def build_strategy(ledger):
    return MeanReversionImbalanceStrategy(
        ledger=ledger,
        kill_switch=KillSwitch(
            max_daily_loss=1000.0,
            max_drawdown_pct=50.0,
        ),
        target_notional=100.0,
        max_position_notional=300.0,
        rolling_window=5,
        min_observations=5,
        entry_zscore=0.5,
        exit_zscore=0.1,
        imbalance_threshold=0.1,
        max_spread_bps=500.0,
        cooldown_seconds=0.0,
        order_type="MARKET",
    )


def test_strategy_generates_buy_entry_signal():
    ledger = PositionLedger()
    strategy = build_strategy(ledger)

    mids = [100.0, 101.0, 102.0, 103.0]

    for mid in mids:
        strategy.on_market_tick(
            {
                "symbol": "BTC/USDT",
                "mid_price": mid,
            }
        )

    signals = strategy.on_orderbook(
        {
            "symbol": "BTC/USDT",
            "mid_price": 90.0,
            "best_bid": 89.9,
            "best_ask": 90.1,
            "spread": 0.2,
            "imbalance": 0.5,
        }
    )

    assert len(signals) == 1
    assert signals[0].side == OrderSide.BUY
    assert signals[0].quantity > 0


def test_strategy_generates_sell_exit_for_long_position():
    ledger = PositionLedger()

    ledger.apply_fill(
        symbol="BTC/USDT",
        side="BUY",
        quantity=1.0,
        price=90.0,
        exchange="SIM",
    )

    strategy = build_strategy(ledger)

    mids = [90.0, 91.0, 92.0, 93.0]

    for mid in mids:
        strategy.on_market_tick(
            {
                "symbol": "BTC/USDT",
                "mid_price": mid,
            }
        )

    signals = strategy.on_orderbook(
        {
            "symbol": "BTC/USDT",
            "mid_price": 100.0,
            "best_bid": 99.9,
            "best_ask": 100.1,
            "spread": 0.2,
            "imbalance": 0.0,
        }
    )

    assert len(signals) == 1
    assert signals[0].side == OrderSide.SELL
    assert signals[0].quantity == 1.0
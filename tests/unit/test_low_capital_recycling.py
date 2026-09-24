from portfolio.position_ledger import PositionLedger
from risk.kill_switch import KillSwitch
from models.order import OrderSide
from strategies.mean_reversion_imbalance import MeanReversionImbalanceStrategy


def build_strategy(ledger, **overrides):
    params = dict(
        ledger=ledger,
        kill_switch=KillSwitch(
            max_daily_loss=1000.0,
            max_drawdown_pct=50.0,
        ),
        target_notional=2.0,
        max_position_notional=6.5,
        min_order_notional=6.0,
        rolling_window=5,
        min_observations=5,
        entry_zscore=0.5,
        exit_zscore=0.1,
        imbalance_threshold=0.1,
        max_spread_bps=500.0,
        cooldown_seconds=60.0,
        order_type="MARKET",
        take_profit_bps=50.0,
        stop_loss_bps=30.0,
        min_profit_after_fee_bps=15.0,
        max_hold_seconds=900.0,
        cooldown_after_exit_seconds=300.0,
        loss_cooldown_seconds=1800.0,
        bad_symbol_drop_bps=1200.0,
    )
    params.update(overrides)
    return MeanReversionImbalanceStrategy(**params)


def warm(strategy, symbol="DOGE/USDT"):
    for mid in [0.100, 0.101, 0.102, 0.103]:
        strategy.on_market_tick(
            {
                "symbol": symbol,
                "mid_price": mid,
            }
        )


def test_small_target_is_raised_to_minimum_trade_notional():
    ledger = PositionLedger()
    strategy = build_strategy(ledger)
    warm(strategy)

    signals = strategy.on_orderbook(
        {
            "symbol": "DOGE/USDT",
            "mid_price": 0.090,
            "best_bid": 0.0899,
            "best_ask": 0.0901,
            "spread": 0.0002,
            "imbalance": 0.5,
        }
    )

    assert len(signals) == 1
    assert signals[0].side == OrderSide.BUY
    assert signals[0].quantity * 0.090 >= 5.99


def test_exit_is_not_blocked_by_entry_cooldown_after_position_exists():
    ledger = PositionLedger()
    strategy = build_strategy(ledger)
    warm(strategy)

    entry = strategy.on_orderbook(
        {
            "symbol": "DOGE/USDT",
            "mid_price": 0.090,
            "best_bid": 0.0899,
            "best_ask": 0.0901,
            "spread": 0.0002,
            "imbalance": 0.5,
        }
    )
    assert entry

    ledger.apply_fill(
        symbol="DOGE/USDT",
        side="BUY",
        quantity=entry[0].quantity,
        price=0.090,
        exchange="SIM",
    )

    exit_signals = strategy.on_orderbook(
        {
            "symbol": "DOGE/USDT",
            "mid_price": 0.096,
            "best_bid": 0.0959,
            "best_ask": 0.0961,
            "spread": 0.0002,
            "imbalance": 0.0,
        }
    )

    assert len(exit_signals) == 1
    assert exit_signals[0].side == OrderSide.SELL


def test_bad_symbol_drop_blocks_new_entry():
    ledger = PositionLedger()
    strategy = build_strategy(
        ledger,
        cooldown_seconds=0.0,
        bad_symbol_drop_bps=50.0,
    )

    for mid in [1.00, 0.99, 0.98, 0.97]:
        strategy.on_market_tick(
            {
                "symbol": "BAD/USDT",
                "mid_price": mid,
            }
        )

    signals = strategy.on_orderbook(
        {
            "symbol": "BAD/USDT",
            "mid_price": 0.96,
            "best_bid": 0.959,
            "best_ask": 0.961,
            "spread": 0.002,
            "imbalance": 0.5,
        }
    )

    assert signals == []
    assert strategy.metrics()["skipped_for_bad_trend"] == 1

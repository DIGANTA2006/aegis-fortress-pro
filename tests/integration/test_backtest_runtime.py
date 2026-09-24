import json

from backtesting.backtest_runtime import BacktestRuntime
from models.order import OrderSide
from models.signal import TradeSignal


class RoundTripStrategy:
    def __init__(self) -> None:
        self.counter = 0

    def on_market_tick(self, tick: dict):
        self.counter += 1

        if self.counter == 1:
            return TradeSignal(
                symbol=tick["symbol"],
                side=OrderSide.BUY,
                quantity=1.0,
                strategy_id="round-trip",
                reason="Open test position",
            )

        if self.counter == 2:
            return TradeSignal(
                symbol=tick["symbol"],
                side=OrderSide.SELL,
                quantity=1.0,
                strategy_id="round-trip",
                reason="Close test position",
            )

        return None


def test_backtest_runtime_executes_round_trip(tmp_path):
    replay_path = tmp_path / "replay.jsonl"

    records = [
        {
            "event_type": "MARKET_TICK",
            "timestamp": "2026-01-01T00:00:00",
            "payload": {
                "exchange": "SIMULATED",
                "symbol": "BTC/USDT",
                "bid": 100.0,
                "ask": 101.0,
                "last": 100.5,
                "volume": 10.0,
            },
        },
        {
            "event_type": "MARKET_TICK",
            "timestamp": "2026-01-01T00:00:01",
            "payload": {
                "exchange": "SIMULATED",
                "symbol": "BTC/USDT",
                "bid": 105.0,
                "ask": 106.0,
                "last": 105.5,
                "volume": 10.0,
            },
        },
    ]

    with replay_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(
                json.dumps(record)
                + "\n"
            )

    runtime = BacktestRuntime(
        strategy=RoundTripStrategy(),
        replay_file=str(replay_path),
        initial_equity=10000.0,
        replay_speed=0.0,
        fee_rate=0.0,
        slippage_bps=0.0,
        max_gross_exposure=100000.0,
        max_net_exposure=100000.0,
        max_symbol_weight=1.0,
        max_order_notional=100000.0,
        max_daily_loss=10000.0,
        max_drawdown_pct=90.0,
    )

    result = runtime.run_sync()

    assert len(result.trades) == 2
    assert result.performance["trade_count"] == 2
    assert result.performance["final_equity"] > 10000.0
    assert result.performance["total_return_pct"] > 0.0

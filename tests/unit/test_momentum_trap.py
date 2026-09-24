from strategies.momentum_trap import MomentumTrapAnalyzer


def test_momentum_trap_analyzer_detects_confirmed_reclaim():
    ohlcv = []

    for index in range(60):
        price = 100 + index * 0.02
        ohlcv.append(
            [
                index * 900_000,
                price,
                price + 0.1,
                price - 0.1,
                price + 0.02,
                100,
            ]
        )

    ohlcv[-2] = [58 * 900_000, 101.0, 101.3, 100.2, 101.2, 230]
    ohlcv[-1] = [59 * 900_000, 101.2, 101.3, 101.1, 101.2, 120]

    decision = MomentumTrapAnalyzer().analyze("TEST/USDT", ohlcv)

    assert decision.should_buy is True
    assert decision.reason == "trap_reclaim"
    assert decision.confidence > 0.80
    assert decision.metrics["trap_core"] is True


def test_momentum_trap_analyzer_skips_overextended_move():
    ohlcv = []

    for index in range(60):
        price = 100 + index * 0.02
        ohlcv.append(
            [
                index * 900_000,
                price,
                price + 0.1,
                price - 0.1,
                price + 0.02,
                100,
            ]
        )

    ohlcv[-2] = [58 * 900_000, 101.0, 102.8, 100.2, 102.7, 230]
    ohlcv[-1] = [59 * 900_000, 102.7, 102.8, 102.5, 102.7, 120]

    decision = MomentumTrapAnalyzer().analyze("TEST/USDT", ohlcv)

    assert decision.should_buy is False
    assert decision.reason in {"no_entry_pattern", "trap_without_trend_confirmation", "trend_filters_failed"}
    assert decision.metrics["not_extended"] is False

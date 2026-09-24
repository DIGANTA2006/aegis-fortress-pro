"""
Load tests – validate throughput of core hot-path components.
"""
import time
from ai.liquidity_scorer import LiquidityScorer
from ai.regime_detector import RegimeDetector
from ai.strategy_selector import StrategySelector


def test_strategy_pipeline_throughput():
    """Full AI pipeline (score -> detect -> select) must complete 1000 cycles in < 2s."""
    scorer = LiquidityScorer()
    detector = RegimeDetector()
    selector = StrategySelector()
    prices = [100.0 + i * 0.01 for i in range(50)]

    start = time.time()
    for _ in range(1000):
        score = scorer.score(500, 500, 0.01)
        regime = detector.detect(prices)
        strategy = selector.select(regime)
    elapsed = time.time() - start

    assert strategy in ("MARKET_MAKING", "TREND_FOLLOWING")
    assert elapsed < 2.0, f"Pipeline too slow: {elapsed:.3f}s"


def test_liquidity_scorer_throughput():
    """LiquidityScorer must handle 50,000 calls per second."""
    scorer = LiquidityScorer()
    n = 50_000
    start = time.time()
    for i in range(n):
        scorer.score(i % 1000 + 1, i % 800 + 1, 0.001 + (i % 10) * 0.0001)
    elapsed = time.time() - start
    assert elapsed < 1.0, f"Scorer too slow: {elapsed:.3f}s for {n} calls"

"""
Stress tests for Aegis v2 core components.
Run with: pytest tests/stress/ -v --timeout=60
"""
import threading
import time
import pytest
from metrics.metrics_registry import MetricsRegistry
from ai.regime_detector import RegimeDetector
from ai.liquidity_scorer import LiquidityScorer
from backtesting.performance_metrics import PerformanceMetrics


def test_metrics_registry_concurrent_writes():
    """MetricsRegistry must handle 1000 concurrent increments without race conditions."""
    registry = MetricsRegistry()
    threads = []
    n_threads = 50
    increments_per_thread = 20

    def worker():
        for _ in range(increments_per_thread):
            registry.increment("stress.counter")

    for _ in range(n_threads):
        t = threading.Thread(target=worker)
        threads.append(t)

    for t in threads:
        t.start()
    for t in threads:
        t.join()

    expected = n_threads * increments_per_thread
    assert registry.get_counter("stress.counter") == expected


def test_regime_detector_large_price_series():
    """RegimeDetector must handle 10,000 price points within 1 second."""
    detector = RegimeDetector()
    prices = [100.0 + (i % 50) * 0.1 for i in range(10_000)]

    start = time.time()
    result = detector.detect(prices)
    elapsed = time.time() - start

    assert result in ("HIGH_VOLATILITY", "NORMAL", "UNKNOWN")
    assert elapsed < 1.0, f"Too slow: {elapsed:.2f}s"


def test_liquidity_scorer_zero_spread():
    """LiquidityScorer must not raise on zero spread (uses max guard)."""
    scorer = LiquidityScorer()
    score = scorer.score(bid_volume=1000, ask_volume=1000, spread=0.0)
    assert score > 0


def test_performance_metrics_large_trade_set():
    """PerformanceMetrics.calculate must handle 5000 trades quickly."""
    trades = [{"pnl": (i % 3) - 1.0} for i in range(5000)]

    start = time.time()
    metrics = PerformanceMetrics().calculate(trades)
    elapsed = time.time() - start

    assert "total_pnl" in metrics
    assert elapsed < 0.5, f"Too slow: {elapsed:.2f}s"


def test_metrics_histogram_high_volume():
    """Histogram should store and summarise 100k observations."""
    r = MetricsRegistry()
    for i in range(100_000):
        r.observe("tick_latency", float(i % 100))

    summary = r.histogram_summary("tick_latency")
    assert summary["count"] == 100_000
    assert summary["p99"] is not None

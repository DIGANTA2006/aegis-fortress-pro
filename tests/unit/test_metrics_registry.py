"""Unit tests for MetricsRegistry."""
from metrics.metrics_registry import MetricsRegistry


def test_counter_increment():
    r = MetricsRegistry()
    r.increment("orders.placed")
    r.increment("orders.placed", 4)
    assert r.get_counter("orders.placed") == 5.0


def test_gauge_set():
    r = MetricsRegistry()
    r.set_gauge("balance", 10000.0)
    assert r.get_gauge("balance") == 10000.0


def test_histogram_observe_and_summary():
    r = MetricsRegistry()
    for v in [1, 2, 3, 4, 5]:
        r.observe("latency_ms", float(v))
    s = r.histogram_summary("latency_ms")
    assert s["count"] == 5
    assert s["min"] == 1.0
    assert s["max"] == 5.0


def test_counter_with_labels():
    r = MetricsRegistry()
    r.increment("fills", labels={"exchange": "binance"})
    r.increment("fills", labels={"exchange": "kraken"})
    assert r.get_counter("fills", {"exchange": "binance"}) == 1.0
    assert r.get_counter("fills", {"exchange": "kraken"}) == 1.0


def test_snapshot():
    r = MetricsRegistry()
    r.increment("x", 3)
    r.set_gauge("y", 99)
    snap = r.snapshot()
    assert "counters" in snap
    assert "gauges" in snap

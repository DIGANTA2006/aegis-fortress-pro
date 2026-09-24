"""
Unit tests for the Prometheus exporter bridge.

These tests do NOT start a real HTTP server Ã¢â‚¬â€ they verify that
AegisCollector correctly translates MetricsRegistry snapshots into
prometheus_client metric families.
"""

import pytest
from metrics.metrics_registry import MetricsRegistry

try:
    from monitoring.prometheus.exporter import AegisCollector, _parse_key, _safe_name
    _HAS_PROMETHEUS = True
except ImportError:
    _HAS_PROMETHEUS = False


pytestmark = pytest.mark.skipif(
    not _HAS_PROMETHEUS,
    reason="prometheus_client not installed"
)


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def test_parse_key_no_labels():
    base, labels = _parse_key("orders_placed")
    assert base   == "orders_placed"
    assert labels == {}


def test_parse_key_with_labels():
    base, labels = _parse_key("fills{exchange=binance,side=buy}")
    assert base              == "fills"
    assert labels["exchange"] == "binance"
    assert labels["side"]     == "buy"


def test_safe_name_dots_to_underscores():
    assert _safe_name("orders.placed") == "orders_placed"


def test_safe_name_braces_stripped():
    assert _safe_name("metric{label}") == "metric_label_"


# ---------------------------------------------------------------------------
# AegisCollector
# ---------------------------------------------------------------------------

def test_collector_yields_counter():
    reg = MetricsRegistry()
    reg.increment("orders.placed", 5)

    collector = AegisCollector(reg)
    families  = list(collector.collect())

    names = [f.name for f in families]
    assert "orders_placed" in names


def test_collector_yields_gauge():
    reg = MetricsRegistry()
    reg.set_gauge("balance_usdt", 12_000.0)

    collector = AegisCollector(reg)
    families  = list(collector.collect())
    names     = [f.name for f in families]
    assert "balance_usdt" in names


def test_collector_yields_histogram_p99():
    reg = MetricsRegistry()
    for v in range(1, 101):          # 100 observations
        reg.observe("latency_ms", float(v))

    collector = AegisCollector(reg)
    families  = list(collector.collect())
    names     = [f.name for f in families]
    assert "latency_ms_p99" in names
    assert "latency_ms_count" in names


def test_collector_handles_empty_registry():
    reg       = MetricsRegistry()
    collector = AegisCollector(reg)
    families  = list(collector.collect())
    assert families == []


def test_collector_labelled_counter():
    reg = MetricsRegistry()
    reg.increment("fills", labels={"exchange": "binance"})
    reg.increment("fills", labels={"exchange": "kraken"})

    collector = AegisCollector(reg)
    families  = list(collector.collect())
    fills     = [f for f in families if f.name == "fills"]
    assert len(fills) == 1                    # one metric family
    assert len(fills[0].samples) == 2         # two label sets
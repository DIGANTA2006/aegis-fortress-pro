"""
monitoring/prometheus/exporter.py  -  AEGIS PRO v2

Bridges MetricsRegistry (in-process counters/gauges/histograms) with
prometheus_client so every metric appears at the /metrics HTTP endpoint
with zero extra instrumentation in business code.

How it works
------------
  1. AegisCollector is a custom prometheus_client Collector that is called
     by the client library every time /metrics is scraped.
  2. It reads a snapshot from MetricsRegistry and yields Prometheus metrics
     on the fly Ã¢â‚¬â€ no double-bookkeeping, no sync issues.
  3. start_metrics_server() registers the collector and opens the HTTP port.

Usage
-----
    from monitoring.prometheus.exporter import start_metrics_server
    from metrics.metrics_registry import MetricsRegistry

    registry = MetricsRegistry()
    start_metrics_server(registry, port=9090)

    # Anywhere in the codebase:
    registry.increment("orders.placed", labels={"exchange": "binance"})
    registry.set_gauge("balance_usdt", 12_345.67)
    registry.observe("order_latency_ms", 42.3)
    # -> all appear automatically at http://localhost:9090/metrics
"""

import logging
import re
import threading

log = logging.getLogger(__name__)

# prometheus_client is an optional dependency Ã¢â‚¬â€ Aegis still runs without it
try:
    from prometheus_client import (
        REGISTRY,
        CollectorRegistry,
        Counter,
        Gauge,
        Histogram,
        start_http_server,
        core as _prom_core,
    )
    from prometheus_client.core import (
        CounterMetricFamily,
        GaugeMetricFamily,
        HistogramMetricFamily,
        REGISTRY as DEFAULT_REGISTRY,
    )
    _HAS_PROMETHEUS = True
except ImportError:
    _HAS_PROMETHEUS = False
    log.warning(
        "prometheus_client not installed Ã¢â‚¬â€ metrics server disabled. "
        "Run: pip install prometheus-client"
    )


_LABEL_RE = re.compile(r"\{(.+)\}$")


def _parse_key(key: str) -> tuple[str, dict[str, str]]:
    """
    Split a MetricsRegistry key like ``orders{exchange=binance}``
    into ``("orders", {"exchange": "binance"})``.
    """
    m = _LABEL_RE.search(key)
    if not m:
        return key, {}
    base   = key[: m.start()]
    labels = {}
    for part in m.group(1).split(","):
        k, _, v = part.partition("=")
        labels[k.strip()] = v.strip()
    return base, labels


def _safe_name(raw: str) -> str:
    """Convert ``orders.placed`` Ã¢â€ â€™ ``orders_placed`` (valid Prometheus name)."""
    return re.sub(r"[^a-zA-Z0-9_]", "_", raw)


if _HAS_PROMETHEUS:

    class AegisCollector:
        """
        Custom prometheus_client Collector that pulls a fresh snapshot
        from MetricsRegistry every time /metrics is scraped.
        """

        def __init__(self, metrics_registry):
            self._registry = metrics_registry

        def describe(self):
            # Return an empty list Ã¢â‚¬â€ we describe dynamically on collect()
            return []

        def collect(self):
            snap = self._registry.snapshot()

            # ---- Counters ----
            grouped: dict[str, list[tuple[dict, float]]] = {}
            for key, value in snap.get("counters", {}).items():
                base, labels = _parse_key(key)
                grouped.setdefault(base, []).append((labels, value))

            for base, pairs in grouped.items():
                name   = _safe_name(base)
                metric = CounterMetricFamily(
                    name, f"Aegis counter: {base}", labels=list(pairs[0][0].keys())
                )
                for labels, value in pairs:
                    metric.add_metric(list(labels.values()), value)
                yield metric

            # ---- Gauges ----
            grouped = {}
            for key, value in snap.get("gauges", {}).items():
                base, labels = _parse_key(key)
                grouped.setdefault(base, []).append((labels, value))

            for base, pairs in grouped.items():
                name   = _safe_name(base)
                metric = GaugeMetricFamily(
                    name, f"Aegis gauge: {base}", labels=list(pairs[0][0].keys())
                )
                for labels, value in pairs:
                    metric.add_metric(list(labels.values()), value)
                yield metric

            # ---- Histograms (summary only Ã¢â‚¬â€ count + sum) ----
            for key in snap.get("histogram_counts", {}):
                base, labels = _parse_key(key)
                summary      = self._registry.histogram_summary(key)
                if not summary:
                    continue
                name   = _safe_name(base)
                metric = GaugeMetricFamily(
                    f"{name}_p99", f"Aegis histogram p99: {base}",
                    labels=list(labels.keys()),
                )
                metric.add_metric(list(labels.values()), summary.get("p99", 0))
                yield metric

                count_m = CounterMetricFamily(
                    f"{name}_count", f"Aegis histogram count: {base}",
                    labels=list(labels.keys()),
                )
                count_m.add_metric(list(labels.values()), summary["count"])
                yield count_m


_server_started = False
_server_lock    = threading.Lock()


def start_metrics_server(metrics_registry, port: int = 9090) -> bool:
    """
    Register AegisCollector and start the Prometheus HTTP server.

    Parameters
    ----------
    metrics_registry : MetricsRegistry
        The shared in-process registry to expose.
    port : int
        HTTP port for the /metrics endpoint (default 9090).

    Returns
    -------
    bool
        True if the server started, False if prometheus_client is missing.
    """
    global _server_started

    if not _HAS_PROMETHEUS:
        log.warning("start_metrics_server: prometheus_client not available.")
        return False

    with _server_lock:
        if _server_started:
            log.warning("start_metrics_server: already running.")
            return True

        try:
            collector = AegisCollector(metrics_registry)
            DEFAULT_REGISTRY.register(collector)
            start_http_server(port)
            _server_started = True
            log.info("Prometheus metrics server started on port %d", port)
            return True
        except Exception:
            log.exception("start_metrics_server: failed to start")
            return False
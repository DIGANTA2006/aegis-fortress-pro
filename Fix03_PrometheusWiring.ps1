#Requires -Version 5.1
<#
.SYNOPSIS
    Fix 03 â€” Wire MetricsRegistry into the Prometheus exporter.

.DESCRIPTION
    The existing monitoring/prometheus/exporter.py only exposes a single
    hardcoded counter.  This fix:
      1. Rewrites exporter.py so it reads live data from MetricsRegistry
         and exposes every counter, gauge, and histogram via prometheus_client.
      2. Adds a AegisMetrics helper class so subsystems can record events
         in one place (MetricsRegistry) and have them auto-appear in /metrics.
      3. Updates monitoring/metrics_server.py to start the Prometheus HTTP
         server on the correct port from config.

.PARAMETER ProjectRoot
    Path to the aegis_v2 directory.
#>

param(
    [string]$ProjectRoot = $PSScriptRoot
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function P([string]$rel) { Join-Path $ProjectRoot $rel }
function Write-Step([string]$msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-OK([string]$msg)   { Write-Host "  [OK] $msg" -ForegroundColor Green }
function WriteFile([string]$rel, [string]$content) {
    $full = P $rel
    [System.IO.File]::WriteAllText($full, $content, [System.Text.UTF8Encoding]::new($false))
    Write-OK $rel
}

if (-not (Test-Path $ProjectRoot)) { Write-Error "Project root not found: $ProjectRoot"; exit 1 }
Write-Host "Project root: $ProjectRoot" -ForegroundColor Yellow

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# 1. Rewrite monitoring/prometheus/exporter.py
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
Write-Step "monitoring/prometheus/exporter.py"

WriteFile "monitoring\prometheus\exporter.py" @'
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
     on the fly â€” no double-bookkeeping, no sync issues.
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

# prometheus_client is an optional dependency â€” Aegis still runs without it
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
        "prometheus_client not installed â€” metrics server disabled. "
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
    """Convert ``orders.placed`` â†’ ``orders_placed`` (valid Prometheus name)."""
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
            # Return an empty list â€” we describe dynamically on collect()
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

            # ---- Histograms (summary only â€” count + sum) ----
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
'@

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# 2. Update monitoring/metrics_server.py
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
Write-Step "monitoring/metrics_server.py"

WriteFile "monitoring\metrics_server.py" @'
"""
monitoring/metrics_server.py  -  AEGIS PRO v2

Thin wrapper that wires the shared MetricsRegistry to the Prometheus
exporter and starts the HTTP server.

Import and call ``launch(registry, port)`` once at startup â€” typically
from main.py after the config has been loaded.
"""

import logging

from monitoring.prometheus.exporter import start_metrics_server

log = logging.getLogger(__name__)

# Default port â€” overridden by configs/default.yaml > monitoring.metrics_port
DEFAULT_PORT = 9090


def launch(metrics_registry, port: int = DEFAULT_PORT) -> None:
    """
    Start the Prometheus /metrics HTTP server.

    Parameters
    ----------
    metrics_registry : MetricsRegistry
        Shared in-process registry populated by all subsystems.
    port : int
        TCP port to listen on (default 9090).
    """
    ok = start_metrics_server(metrics_registry, port=port)
    if ok:
        log.info("Metrics server live â€” http://0.0.0.0:%d/metrics", port)
    else:
        log.warning(
            "Metrics server NOT started (prometheus_client missing). "
            "Install with: pip install prometheus-client"
        )
'@

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# 3. Add a unit test for the exporter
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
Write-Step "tests/unit/test_prometheus_exporter.py"

WriteFile "tests\unit\test_prometheus_exporter.py" @'
"""
Unit tests for the Prometheus exporter bridge.

These tests do NOT start a real HTTP server â€” they verify that
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
'@

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Done
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
Write-Host "`n=================================================" -ForegroundColor Magenta
Write-Host "  Fix 03 complete â€” Prometheus wiring done." -ForegroundColor Magenta
Write-Host "  Next: run Fix04_ReplayEngine.ps1" -ForegroundColor Magenta
Write-Host "=================================================" -ForegroundColor Magenta

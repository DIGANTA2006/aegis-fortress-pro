"""
monitoring/metrics_server.py  -  AEGIS PRO v2

Thin wrapper that wires the shared MetricsRegistry to the Prometheus
exporter and starts the HTTP server.

Import and call ``launch(registry, port)`` once at startup Ã¢â‚¬â€ typically
from main.py after the config has been loaded.
"""

import logging

from monitoring.prometheus.exporter import start_metrics_server

log = logging.getLogger(__name__)

# Default port Ã¢â‚¬â€ overridden by configs/default.yaml > monitoring.metrics_port
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
        log.info("Metrics server live Ã¢â‚¬â€ http://0.0.0.0:%d/metrics", port)
    else:
        log.warning(
            "Metrics server NOT started (prometheus_client missing). "
            "Install with: pip install prometheus-client"
        )
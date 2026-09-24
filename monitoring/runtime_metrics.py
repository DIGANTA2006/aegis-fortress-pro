from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    start_http_server,
)


class RuntimeMetrics:
    def __init__(
        self,
        port: int = 9000,
    ) -> None:
        self.port = port
        self.registry = CollectorRegistry()
        self._server_started = False

        self.market_ticks_total = Counter(
            "aegis_market_ticks_total",
            "Total normalized market tick events",
            registry=self.registry,
        )

        self.orderbooks_total = Counter(
            "aegis_orderbooks_total",
            "Total normalized orderbook snapshot events",
            registry=self.registry,
        )

        self.execution_reports_total = Counter(
            "aegis_execution_reports_total",
            "Total execution report events",
            registry=self.registry,
        )

        self.risk_events_total = Counter(
            "aegis_risk_events_total",
            "Total emitted risk breach events",
            ["severity"],
            registry=self.registry,
        )

        self.stale_market_keys = Gauge(
            "aegis_stale_market_keys",
            "Count of stale market data streams",
            registry=self.registry,
        )

        self.kill_switch_triggered = Gauge(
            "aegis_kill_switch_triggered",
            "Kill switch active state: 1 triggered, 0 normal",
            registry=self.registry,
        )

        self.runtime_database_up = Gauge(
            "aegis_database_up",
            "Database connectivity state",
            registry=self.registry,
        )

    def start_server(self) -> None:
        if self._server_started:
            return

        start_http_server(
            self.port,
            registry=self.registry,
        )

        self._server_started = True

    def record_market_tick(self) -> None:
        self.market_ticks_total.inc()

    def record_orderbook(self) -> None:
        self.orderbooks_total.inc()

    def record_execution_report(self) -> None:
        self.execution_reports_total.inc()

    def record_risk_event(self, severity: str) -> None:
        self.risk_events_total.labels(
            severity=str(severity).upper()
        ).inc()

    def set_stale_market_keys(self, count: int) -> None:
        self.stale_market_keys.set(
            max(0, count)
        )

    def set_kill_switch_triggered(self, triggered: bool) -> None:
        self.kill_switch_triggered.set(
            1 if triggered else 0
        )

    def set_database_up(self, up: bool) -> None:
        self.runtime_database_up.set(
            1 if up else 0
        )

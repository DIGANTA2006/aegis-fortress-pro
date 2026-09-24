import asyncio
import logging

from core.events.execution_event import ExecutionEvent
from core.events.market_tick_event import MarketTickEvent
from core.events.orderbook_event import OrderBookEvent
from core.events.risk_event import RiskEvent
from microservices.base_service import BaseService


log = logging.getLogger(__name__)


class MonitoringService(BaseService):
    def __init__(
        self,
        event_bus,
        metrics,
        market_state_store,
        kill_switch,
        database,
        interval_seconds: float = 5.0,
    ) -> None:
        super().__init__("monitoring-service")

        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")

        self.event_bus = event_bus
        self.metrics = metrics
        self.market_state_store = market_state_store
        self.kill_switch = kill_switch
        self.database = database
        self.interval_seconds = interval_seconds

    async def on_start(self) -> None:
        self.metrics.start_server()

        self.event_bus.subscribe(
            "MARKET_TICK",
            self._on_market_tick,
        )

        self.event_bus.subscribe(
            "ORDERBOOK_SNAPSHOT",
            self._on_orderbook,
        )

        self.event_bus.subscribe(
            "EXECUTION_REPORT",
            self._on_execution_report,
        )

        self.event_bus.subscribe(
            "RISK_BREACH",
            self._on_risk_breach,
        )

        log.info("MonitoringService started")

    async def run(self) -> None:
        while self.running:
            self.heartbeat()

            stale_count = len(
                self.market_state_store.stale_keys()
            )

            self.metrics.set_stale_market_keys(
                stale_count
            )

            self.metrics.set_kill_switch_triggered(
                self.kill_switch.triggered
            )

            self.metrics.set_database_up(
                self.database.ping()
            )

            await asyncio.sleep(
                self.interval_seconds
            )

    async def _on_market_tick(
        self,
        event: MarketTickEvent,
    ) -> None:
        self.metrics.record_market_tick()

    async def _on_orderbook(
        self,
        event: OrderBookEvent,
    ) -> None:
        self.metrics.record_orderbook()

    async def _on_execution_report(
        self,
        event: ExecutionEvent,
    ) -> None:
        self.metrics.record_execution_report()

    async def _on_risk_breach(
        self,
        event: RiskEvent,
    ) -> None:
        self.metrics.record_risk_event(
            event.severity
        )

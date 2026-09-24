import asyncio
import logging

from core.events.execution_event import ExecutionEvent
from core.events.risk_event import RiskEvent
from microservices.base_service import BaseService


log = logging.getLogger(__name__)


class RiskService(BaseService):
    def __init__(
        self,
        event_bus,
        kill_switch,
    ) -> None:
        super().__init__("risk-service")

        self.event_bus = event_bus
        self.kill_switch = kill_switch

        self.execution_reports_seen = 0
        self.risk_events_emitted = 0
        self.critical_breaches = 0

    async def on_start(self) -> None:
        self.event_bus.subscribe(
            "EXECUTION_REPORT",
            self._on_execution_report,
        )

        log.info("RiskService subscribed to EXECUTION_REPORT")

    async def run(self) -> None:
        while self.running:
            self.heartbeat()
            await asyncio.sleep(1)

    async def _on_execution_report(
        self,
        event: ExecutionEvent,
    ) -> None:
        self.execution_reports_seen += 1

        fill_result = event.fill_result or {}
        breaches = fill_result.get("breaches", [])

        if not breaches:
            return

        for breach in breaches:
            severity = str(breach.get("severity", "WARNING")).upper()
            code = str(breach.get("code", "UNKNOWN_RISK_BREACH"))
            message = str(breach.get("message", "Risk breach detected"))

            if severity == "CRITICAL":
                self.critical_breaches += 1
                self.kill_switch.trigger(message)

            risk_event = RiskEvent(
                event_type="RISK_BREACH",
                correlation_id=event.correlation_id,
                severity=severity,
                code=code,
                message=message,
                metadata={
                    "execution_report": event.report,
                    "breach": breach,
                    "kill_switch": self.kill_switch.status(),
                },
            )

            await self.event_bus.publish(
                risk_event
            )

            self.risk_events_emitted += 1

            log.warning(
                "RiskService emitted risk event code=%s severity=%s message=%s",
                code,
                severity,
                message,
            )

    def metrics(self) -> dict:
        return {
            "execution_reports_seen": self.execution_reports_seen,
            "risk_events_emitted": self.risk_events_emitted,
            "critical_breaches": self.critical_breaches,
            "kill_switch": self.kill_switch.status(),
        }

    def health(self) -> dict:
        payload = super().health()
        payload["metrics"] = self.metrics()
        return payload

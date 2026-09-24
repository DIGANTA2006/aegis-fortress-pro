import asyncio
import json
import logging
from pathlib import Path

from core.events.risk_event import RiskEvent
from microservices.base_service import BaseService


log = logging.getLogger(__name__)


class RiskEventLoggerService(BaseService):
    def __init__(
        self,
        event_bus,
        log_file: str = "logs/risk_events.jsonl",
        database=None,
    ) -> None:
        super().__init__("risk-event-logger-service")

        self.event_bus = event_bus
        self.log_file = Path(log_file)
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        self.database = database

        self.events_written = 0

    async def on_start(self) -> None:
        self.event_bus.subscribe(
            "RISK_BREACH",
            self._on_risk_breach,
        )

        log.info("RiskEventLoggerService subscribed to RISK_BREACH")

    async def run(self) -> None:
        while self.running:
            self.heartbeat()
            await asyncio.sleep(1)

    async def _on_risk_breach(
        self,
        event: RiskEvent,
    ) -> None:
        payload = {
            "event_type": event.event_type,
            "correlation_id": event.correlation_id,
            "timestamp": event.timestamp.isoformat(),
            "severity": event.severity,
            "code": event.code,
            "message": event.message,
            "metadata": event.metadata,
        }

        with self.log_file.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(payload, sort_keys=True)
                + "\n"
            )

        if self.database is not None:
            self.database.record_risk_event(
                payload
            )

        self.events_written += 1

        log.warning(
            "Risk event persisted code=%s severity=%s",
            event.code,
            event.severity,
        )

    def health(self) -> dict:
        payload = super().health()
        payload["events_written"] = self.events_written
        return payload

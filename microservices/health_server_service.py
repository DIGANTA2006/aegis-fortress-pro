import asyncio
import logging

from microservices.base_service import BaseService


log = logging.getLogger(__name__)


class HealthServerService(BaseService):
    def __init__(
        self,
        health_server,
        health_aggregator,
        database,
        snapshot_interval_seconds: float = 30.0,
    ) -> None:
        super().__init__("health-server-service")

        if snapshot_interval_seconds <= 0:
            raise ValueError("snapshot_interval_seconds must be positive")

        self.health_server = health_server
        self.health_aggregator = health_aggregator
        self.database = database
        self.snapshot_interval_seconds = snapshot_interval_seconds

    async def on_start(self) -> None:
        self.health_server.start()
        log.info("Health HTTP server started")

    async def on_stop(self) -> None:
        self.health_server.stop()
        log.info("Health HTTP server stopped")

    async def run(self) -> None:
        while self.running:
            self.heartbeat()

            status = self.health_aggregator.status()

            self.database.record_health_snapshot(
                status
            )

            await asyncio.sleep(
                self.snapshot_interval_seconds
            )

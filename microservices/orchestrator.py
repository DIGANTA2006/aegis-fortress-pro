import logging


log = logging.getLogger(__name__)


class Orchestrator:
    def __init__(
        self,
        event_bus,
        task_supervisor,
        services: list,
    ) -> None:
        self.event_bus = event_bus
        self.task_supervisor = task_supervisor
        self.services = services
        self.running = False

    async def start(self) -> None:
        if self.running:
            return

        self.running = True

        self.task_supervisor.create_task(
            "event-bus",
            self.event_bus.start(),
        )

        for service in self.services:
            await service.prepare()

        for service in self.services:
            self.task_supervisor.create_task(
                service.name,
                service.run(),
            )

        log.info(
            "Orchestrator started with services: %s",
            [service.name for service in self.services],
        )

    async def stop(self) -> None:
        if not self.running:
            return

        self.running = False

        for service in self.services:
            await service.stop()

        await self.event_bus.stop()
        await self.task_supervisor.shutdown()

        log.info("Orchestrator stopped")

    def health(self) -> dict:
        return {
            "running": self.running,
            "services": {
                service.name: service.health()
                for service in self.services
            },
        }

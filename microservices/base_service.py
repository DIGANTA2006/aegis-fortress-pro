import logging
import time


log = logging.getLogger(__name__)


class BaseService:
    def __init__(self, name: str) -> None:
        self.name = name
        self.running = False
        self.started_at: float | None = None
        self.last_heartbeat: float | None = None
        self._prepared = False

    async def prepare(self) -> None:
        if self._prepared:
            return

        self.running = True
        self.started_at = time.time()
        self.last_heartbeat = self.started_at

        await self.on_start()

        self._prepared = True

        log.info("Service prepared: %s", self.name)

    async def start(self) -> None:
        await self.prepare()
        await self.run()

    async def stop(self) -> None:
        if not self.running:
            return

        self.running = False

        await self.on_stop()

        log.info("Service stopped: %s", self.name)

    async def on_start(self) -> None:
        return None

    async def on_stop(self) -> None:
        return None

    async def run(self) -> None:
        raise NotImplementedError

    def heartbeat(self) -> None:
        self.last_heartbeat = time.time()

    def health(self) -> dict:
        return {
            "name": self.name,
            "running": self.running,
            "prepared": self._prepared,
            "started_at": self.started_at,
            "last_heartbeat": self.last_heartbeat,
        }

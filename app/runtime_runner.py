import asyncio
import logging
import signal

from app.runtime_container import RuntimeContainer
from core.structured_logger import configure_logger


log = logging.getLogger(__name__)


class RuntimeRunner:
    def __init__(self) -> None:
        self.container: RuntimeContainer | None = None
        self.stop_event = asyncio.Event()

    async def run(self) -> None:
        configure_logger()

        self.container = RuntimeContainer.build()

        self._install_signal_handlers()

        await self.container.orchestrator.start()

        log.info("AEGIS runtime started")

        await self.stop_event.wait()

        log.warning("AEGIS runtime shutdown requested")

        await self.container.orchestrator.stop()

        log.info("AEGIS runtime stopped")

    def request_stop(self) -> None:
        self.stop_event.set()

    def _install_signal_handlers(self) -> None:
        loop = asyncio.get_running_loop()

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(
                    sig,
                    self.request_stop,
                )
            except (NotImplementedError, RuntimeError):
                signal.signal(
                    sig,
                    lambda *_args: self.request_stop(),
                )


def main() -> None:
    runner = RuntimeRunner()

    try:
        asyncio.run(
            runner.run()
        )
    except KeyboardInterrupt:
        pass

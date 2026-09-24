import asyncio
import logging
from collections import defaultdict


log = logging.getLogger(__name__)


class EventBus:
    def __init__(self) -> None:
        self.subscribers = defaultdict(list)
        self.queue = asyncio.Queue()
        self.running = False
        self._stop_sentinel = object()

    def subscribe(
        self,
        event_type: str,
        callback,
    ) -> None:
        self.subscribers[event_type].append(callback)

        log.info(
            "Subscribed callback to event type: %s",
            event_type,
        )

    async def publish(self, event) -> None:
        await self.queue.put(event)

    async def start(self) -> None:
        if self.running:
            return

        self.running = True
        log.info("Event bus started")

        while self.running:
            event = await self.queue.get()

            if event is self._stop_sentinel:
                break

            event_type = getattr(event, "event_type", None)

            if not event_type:
                log.warning("Discarded event without event_type")
                continue

            callbacks = self.subscribers.get(event_type, [])

            for callback in callbacks:
                try:
                    result = callback(event)

                    if asyncio.iscoroutine(result):
                        await result

                except Exception as exc:
                    log.exception(
                        "Event handler failed for %s: %s",
                        event_type,
                        exc,
                    )

        log.info("Event bus stopped")

    async def stop(self) -> None:
        if not self.running:
            return

        self.running = False
        await self.queue.put(self._stop_sentinel)

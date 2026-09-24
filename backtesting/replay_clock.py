import asyncio
from datetime import datetime


class ReplayClock:
    def __init__(
        self,
        speed: float = 0.0,
    ) -> None:
        if speed < 0:
            raise ValueError("Replay speed cannot be negative")

        self.speed = speed
        self.current_time: datetime | None = None
        self._last_event_time: datetime | None = None

    async def advance_to(
        self,
        event_time: datetime,
    ) -> None:
        if self._last_event_time is None:
            self._last_event_time = event_time
            self.current_time = event_time
            return

        if event_time < self._last_event_time:
            raise ValueError(
                "Replay event timestamp moved backwards"
            )

        delta_seconds = (
            event_time - self._last_event_time
        ).total_seconds()

        if self.speed > 0 and delta_seconds > 0:
            await asyncio.sleep(
                delta_seconds / self.speed
            )

        self._last_event_time = event_time
        self.current_time = event_time

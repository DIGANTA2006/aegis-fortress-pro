import asyncio
from collections import defaultdict

class EventBus:

    def __init__(self):
        self.listeners = defaultdict(list)

    def subscribe(self, event_name, callback):
        self.listeners[event_name].append(callback)

    async def emit(self, event_name: str, data=None) -> None:
        # Emit event; supports coroutine and normal listeners.
        if event_name not in self.listeners:
            return
        tasks = []
        for callback in self.listeners[event_name]:
            result = callback(data)
            if asyncio.iscoroutine(result):
                tasks.append(result)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

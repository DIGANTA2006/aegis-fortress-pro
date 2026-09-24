import asyncio
import logging


log = logging.getLogger(__name__)


class TaskSupervisor:
    def __init__(self):
        self.tasks = {}

    def create_task(
        self,
        name,
        coro,
    ):
        task = asyncio.create_task(
            coro
        )

        self.tasks[name] = task

        task.add_done_callback(
            lambda completed_task: self._handle_completion(
                name,
                completed_task,
            )
        )

        return task

    def _handle_completion(
        self,
        name,
        task,
    ):
        if task.cancelled():
            return

        try:
            task.result()

        except asyncio.CancelledError:
            return

        except Exception as exc:
            log.exception(
                "Task failed %s: %s",
                name,
                exc,
            )

    async def shutdown(self):
        for task in self.tasks.values():
            if not task.done():
                task.cancel()

        await asyncio.gather(
            *self.tasks.values(),
            return_exceptions=True,
        )
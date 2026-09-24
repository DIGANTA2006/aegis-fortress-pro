import time
from typing import Optional
from typing import Optional
from typing import Optional
from typing import Optional
from typing import Optional
from typing import Optional

class LatencyTracker:

    def __init__(self):
        self.start_time = None

    def start(self):
        self.start_time = time.perf_counter()

    def stop(self) -> "Optional[float]":
        # Return elapsed ms and reset, or None if not started.
        if self.start_time is None:
            return None
        elapsed_ms = (time.perf_counter() - self.start_time) * 1000
        self.start_time = None  # reset so double-stop() returns None
        return elapsed_ms

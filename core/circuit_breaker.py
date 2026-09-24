import time


class CircuitBreaker:

    def __init__(self, failure_threshold=5, recovery_timeout=60):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count = 0
        self.last_failure_time = None
        self.state = "CLOSED"

    def call_allowed(self):

        if self.state == "OPEN":

            elapsed = time.time() - self.last_failure_time

            if elapsed >= self.recovery_timeout:
                self.state = "HALF_OPEN"
                return True

            return False

        return True

    def record_success(self) -> None:
        self.failure_count = 0
        self.last_failure_time = None
        self.state = "CLOSED"

    def record_failure(self) -> None:
        self.failure_count += 1
        self.last_failure_time = time.time()
        # Re-open immediately on failure during HALF_OPEN probe
        if self.failure_count >= self.failure_threshold or self.state == "HALF_OPEN":
            self.state = "OPEN"

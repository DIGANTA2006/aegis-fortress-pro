import time
import logging

log = logging.getLogger(__name__)

class RetryEngine:

    def __init__(
        self,
        retries=5,
        base_delay=1
    ):

        self.retries = retries
        self.base_delay = base_delay

    def execute(self, func, *args, **kwargs):

        for attempt in range(self.retries):

            try:

                return func(*args, **kwargs)

            except Exception as e:

                delay = self.base_delay * (2 ** attempt)

                log.warning(
                    f'Retry {attempt+1} failed: {e}'
                )

                time.sleep(delay)

        raise RuntimeError(
            'Max retry attempts exceeded'
        )

import time


class HealthCheckManager:

    def __init__(self):

        self.checks = {}

    def update_check(
        self,
        name,
        healthy,
        metadata=None
    ):

        self.checks[name] = {

            'healthy': healthy,

            'timestamp': time.time(),

            'metadata': metadata or {}
        }

    def get_status(self):

        overall = all(

            check['healthy']

            for check in self.checks.values()
        )

        return {

            'healthy': overall,

            'checks': self.checks
        }

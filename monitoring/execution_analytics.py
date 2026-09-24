import statistics


class ExecutionAnalytics:

    def __init__(self):

        self.latencies = []
        self.slippages = []

    def record_latency(self, latency):

        self.latencies.append(latency)

    def record_slippage(self, slippage):

        self.slippages.append(slippage)

    def summary(self):

        return {

            'avg_latency': (
                statistics.mean(self.latencies)
                if self.latencies else 0
            ),

            'avg_slippage': (
                statistics.mean(self.slippages)
                if self.slippages else 0
            ),

            'max_latency': (
                max(self.latencies)
                if self.latencies else 0
            )
        }

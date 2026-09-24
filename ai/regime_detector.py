import statistics


class RegimeDetector:

    def __init__(
        self,
        volatility_threshold=0.02
    ):

        self.volatility_threshold = (
            volatility_threshold
        )

    def detect(self, prices):

        if len(prices) < 2:
            return 'UNKNOWN'

        returns = []

        for i in range(1, len(prices)):

            r = (
                prices[i] - prices[i - 1]
            ) / prices[i - 1]

            returns.append(r)

        volatility = statistics.stdev(returns)

        if volatility > self.volatility_threshold:
            return 'HIGH_VOLATILITY'

        return 'NORMAL'

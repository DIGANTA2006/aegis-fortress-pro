class StrategySelector:

    def select(
        self,
        regime
    ):

        if regime == 'HIGH_VOLATILITY':
            return 'MARKET_MAKING'

        return 'TREND_FOLLOWING'

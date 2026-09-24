class LiquidityScorer:

    def score(
        self,
        bid_volume,
        ask_volume,
        spread
    ):

        liquidity = (
            bid_volume + ask_volume
        ) / max(spread, 0.0001)

        return liquidity
